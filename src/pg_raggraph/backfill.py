"""Background extraction primitive — drains documents.graph_status='pending'.

The thesis matches the rest of pg-raggraph: single Postgres database, no broker.
Queue claims use ``SELECT … FOR UPDATE SKIP LOCKED`` so concurrent workers
never claim the same row, and per-document extraction commits in one
transaction so failure leaves no half-graph behind.

Two surfaces consume this module:
  * ``pgrg extract`` (CLI) — short-lived backfill drains
  * ``pgrg extract --daemon`` — long-running service with graceful shutdown

Both share ``claim_pending`` + ``extract_documents`` as the only primitives.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pg_raggraph import GraphRAG

logger = logging.getLogger("pg_raggraph.backfill")

# How many staged docs' content to read per query in backfill_code_graph.
# One query per doc is an N+1 round-trip pattern (~10% of backfill wall-time at
# scale); batching cuts that ~64x while keeping peak memory O(batch docs'
# content), not O(corpus). The chunkshop symbol index (held by CorpusCodeGraph)
# stays the dominant, unavoidable resident — this only bounds the content we
# hold in flight, preserving the #76 memory ethos.
_CONTENT_READ_BATCH = 64


@dataclass
class ExtractStats:
    """Per-call extraction outcome — what was claimed vs what succeeded.

    ``degraded`` counts docs that flipped to 'ready' with partial yield —
    some chunks errored but others produced entities (issue #93). Their
    failure summary is preserved in ``documents.graph_error``.
    ``chunks_failed`` is the total errored chunks across the whole call.
    """

    claimed: int = 0
    ready: int = 0
    failed: int = 0
    degraded: int = 0
    chunks_failed: int = 0
    entities: int = 0
    relationships: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)


class ExtractionFailedError(RuntimeError):
    """Every entity-bearing path for a doc errored — zero yield, N chunks failed.

    Raised by ``_extract_one`` so ``extract_documents`` marks the doc
    'failed' (retryable via ``pgrg extract --include-failed``) instead of
    silently flipping it to 'ready' with a hollow graph (issue #93).
    """

    def __init__(self, message: str, chunks_failed: int = 0):
        super().__init__(message)
        self.chunks_failed = chunks_failed


@dataclass
class CodeGraphStats:
    """Per-call code-graph backfill outcome.

    ``docs`` is staged docs resolved, ``edges`` the relationships written,
    ``namespaces`` how many namespaces had staged work, ``skipped`` docs left
    in place because chunkshop's extractor was unavailable.
    """

    namespaces: int = 0
    docs: int = 0
    edges: int = 0
    skipped: int = 0


async def claim_pending(db, namespace: str | None, batch_size: int) -> list[int]:
    """Atomically claim up to ``batch_size`` pending docs and flip them to
    ``processing``.

    Uses ``SELECT … FOR UPDATE SKIP LOCKED`` so a peer claim_pending call
    running concurrently never sees these rows. The flip-to-processing and the
    SELECT happen in one transaction — once we COMMIT, the claimed rows are
    visible (as 'processing') to everyone but no longer eligible for a peer's
    'pending'-filtered SELECT.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")

    async with db.transaction() as tx:
        if namespace is None:
            rows = await tx.fetch_all(
                "SELECT id FROM documents "
                "WHERE graph_status = 'pending' "
                "ORDER BY created_at "
                "LIMIT %s "
                "FOR UPDATE SKIP LOCKED",
                (batch_size,),
            )
        else:
            rows = await tx.fetch_all(
                "SELECT id FROM documents "
                "WHERE namespace = %s AND graph_status = 'pending' "
                "ORDER BY created_at "
                "LIMIT %s "
                "FOR UPDATE SKIP LOCKED",
                (namespace, batch_size),
            )
        ids = [r["id"] for r in rows]
        if not ids:
            return []
        await tx.execute(
            "UPDATE documents SET graph_status = 'processing' WHERE id = ANY(%s)",
            (ids,),
        )
    return ids


async def release_processing(
    db,
    *,
    namespace: str | None = None,
    doc_ids: list[int] | None = None,
) -> None:
    """Return 'processing' rows to 'pending' — crash-recovery reaper.

    Precedence (most specific wins):
      * ``doc_ids`` set  → reap exactly those rows (used by recovery scripts).
      * ``namespace`` set → reap every 'processing' row in that namespace.
        This is what `pgrg extract` calls at startup, so a peer worker
        running against a DIFFERENT namespace doesn't have its claims
        stolen.
      * neither set     → reap every 'processing' row in the database.
        DANGEROUS in multi-worker / multi-namespace deployments: a peer
        worker mid-extract loses its claim, a different worker re-claims
        the same doc, and (until relationships have ON CONFLICT) the
        graph gains duplicate edges. Logs a warning when used this way.

    Without a reaper, a worker that died mid-extract would leave its claimed
    rows invisible to future workers. Run on worker startup (or as a periodic
    janitor) to recover.
    """
    if doc_ids is not None:
        if not doc_ids:
            return
        await db.execute(
            "UPDATE documents SET graph_status = 'pending' "
            "WHERE id = ANY(%s) AND graph_status = 'processing'",
            (doc_ids,),
        )
        return
    if namespace is not None:
        await db.execute(
            "UPDATE documents SET graph_status = 'pending' "
            "WHERE namespace = %s AND graph_status = 'processing'",
            (namespace,),
        )
        return
    logger.warning(
        "release_processing called with no namespace and no doc_ids — "
        "this reaps every 'processing' row in the database and can steal "
        "claims from peer workers. Pass a namespace to scope safely."
    )
    await db.execute(
        "UPDATE documents SET graph_status = 'pending' WHERE graph_status = 'processing'"
    )


async def extract_documents(
    rag: GraphRAG,
    doc_ids: list[int],
    *,
    namespace: str | None = None,
) -> ExtractStats:
    """Extract entities/relationships for each doc id, atomic per doc.

    Loads stored chunks, runs the configured extractor (lede_spacy or the LLM
    pipeline depending on config), resolves entities, writes
    entities/relationships, and flips ``graph_status='ready'`` — all in one
    transaction per doc. On exception the transaction rolls back and a
    separate small UPDATE marks the doc as 'failed' with the error captured
    in ``graph_error``.

    Docs run in parallel, bounded by ``rag.config.doc_concurrency`` (same
    knob the synchronous ingest fan-out honors). One doc failing never
    affects its siblings.

    Idempotent on relationships after PR-002 (migration 013 + ON CONFLICT).
    Re-running on a 'ready' doc is also safe — the relationships INSERT
    falls through to the existing row's id via ON CONFLICT DO UPDATE.
    Callers should still claim via ``claim_pending`` rather than passing
    arbitrary ids; the docstring caveat is just about which path is the
    documented happy one.

    ``namespace`` is purely for metric labeling (``pgrg.backfill.extract``).
    The actual namespace each doc lives in is loaded from the doc row, so
    passing the wrong label here does NOT route writes wrong — just labels
    metrics wrong.
    """
    stats = ExtractStats()
    if not doc_ids:
        return stats

    t0 = time.perf_counter()

    # Docs fan out in parallel, bounded by doc_concurrency (GAP-007) — each
    # doc is already an independent transaction and claims came through SKIP
    # LOCKED, so parallel docs are safe by construction. return_exceptions
    # isolates failures: one doc's exception never cancels its siblings.
    sem = asyncio.Semaphore(max(1, rag.config.doc_concurrency))

    async def _one(doc_id: int):
        async with sem:
            return await _extract_one(rag, doc_id)

    results = await asyncio.gather(*(_one(d) for d in doc_ids), return_exceptions=True)

    # Aggregate post-gather in doc_ids order — counters and stats.errors stay
    # deterministic regardless of task completion order.
    for doc_id, res in zip(doc_ids, results):
        stats.claimed += 1
        if not isinstance(res, BaseException):
            per_doc = res
            stats.ready += 1
            stats.entities += per_doc["entities"]
            stats.relationships += per_doc["rels"]
            stats.chunks_failed += per_doc.get("chunks_failed", 0)
            if per_doc.get("chunks_failed"):
                stats.degraded += 1
        else:
            e = res
            stats.failed += 1
            stats.chunks_failed += getattr(e, "chunks_failed", 0)
            # ExtractionFailedError already reads "extraction failed on
            # N/M chunks: …" — don't prefix the class name.
            err = str(e) if isinstance(e, ExtractionFailedError) else f"{type(e).__name__}: {e}"
            stats.errors.append((doc_id, err))
            logger.warning("Extraction failed for doc %s: %s", doc_id, err)
            try:
                await rag.db.execute(
                    "UPDATE documents SET graph_status = 'failed', graph_error = %s WHERE id = %s",
                    (err[:2000], doc_id),
                )
            except Exception as flip_err:
                logger.error("Failed to mark doc %s as failed: %s", doc_id, flip_err)

    # One metric event per call covers the whole batch. Per-doc events would
    # explode log volume for the common case where a batch is many cheap
    # extractions — operators want claim/extract/queue_depth aggregates.
    emit = getattr(rag, "_emit_metric", None)
    if emit is not None:
        emit(
            "pgrg.backfill.extract",
            namespace=namespace,
            claimed=stats.claimed,
            ready=stats.ready,
            failed=stats.failed,
            degraded=stats.degraded,
            chunks_failed=stats.chunks_failed,
            entities=stats.entities,
            relationships=stats.relationships,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
    return stats


async def backfill_code_graph(
    rag: GraphRAG,
    namespace: str | None,
    *,
    batch_size: int = 5000,
) -> CodeGraphStats:
    """Rebuild the chunkshop code graph for docs staged by deferred ingest (#81).

    A per-namespace corpus pass: re-parse each staged code doc into a shared
    ``CorpusCodeGraph`` (spilling call sites the #76 way), then call the existing
    ``rag._write_corpus_code_graph`` resolver to write the CALLS/INHERITS/
    IMPLEMENTS edges, then delete the staged rows.

    Cross-file resolution is namespace-scoped (symbols never cross namespaces),
    so ``namespace=None`` runs one independent pass per namespace found in
    ``code_backfill_stage``.

    Resumable: staged rows are deleted only after the resolve succeeds, so a
    crash mid-pass leaves them for a re-run (edge upserts are idempotent). This
    is a single-worker corpus *finalize* — concurrent runs over one namespace are
    correct but duplicate work. It never touches ``documents.graph_status``;
    generic entity backfill (``extract_documents``) owns that independently.
    """
    import uuid

    from pg_raggraph.chunkshop_bridge import CorpusCodeGraph

    stats = CodeGraphStats()

    if namespace is None:
        ns_rows = await rag.db.fetch_all(
            "SELECT DISTINCT namespace FROM code_backfill_stage ORDER BY namespace"
        )
        target_namespaces = [r["namespace"] for r in ns_rows]
    else:
        target_namespaces = [namespace]

    # chunkshop availability is namespace-invariant — probe it once. A FRESH
    # CorpusCodeGraph is still built per namespace below: each namespace is an
    # independent corpus, so sharing one extractor would cross-pollinate symbol
    # indexes across tenants. When unavailable, staged rows are left in place
    # (counted as skipped) for a later run and a single summary warning is
    # emitted after the loop rather than one per namespace.
    chunkshop_ok = CorpusCodeGraph().available

    for ns in target_namespaces:
        id_rows = await rag.db.fetch_all(
            "SELECT document_id FROM code_backfill_stage WHERE namespace = %s "
            "ORDER BY document_id",
            (ns,),
        )
        doc_ids = [r["document_id"] for r in id_rows]
        if not doc_ids:
            continue
        stats.namespaces += 1

        if not chunkshop_ok:
            stats.skipped += len(doc_ids)
            continue

        ccg = CorpusCodeGraph()
        run_id = uuid.uuid4().hex
        t0 = time.perf_counter()
        # Read staged content in bounded batches (not one row per doc — that's an
        # N+1 round-trip pattern). Peak content held is O(_CONTENT_READ_BATCH
        # docs), never O(corpus text) — the #76 memory ethos. Concurrently
        # deleted rows simply don't come back in the batch (no per-row guard
        # needed). Accumulation order doesn't affect the resolved edge set (the
        # symbol index is a union), so within-batch ORDER BY is just determinism.
        for start in range(0, len(doc_ids), _CONTENT_READ_BATCH):
            id_batch = doc_ids[start : start + _CONTENT_READ_BATCH]
            rows = await rag.db.fetch_all(
                "SELECT content, language, source_path FROM code_backfill_stage "
                "WHERE document_id = ANY(%s) ORDER BY document_id",
                (id_batch,),
            )
            for row in rows:
                calls = await ccg.accumulate(
                    row["content"], source_path=row["source_path"], language=row["language"]
                )
                if calls:
                    await rag._spill_code_calls(ns, run_id, calls)

        n_rels = 0
        if ccg.count:
            n_rels = await rag._write_corpus_code_graph(ns, ccg, run_id, batch_size=batch_size)

        await rag.db.execute(
            "DELETE FROM code_backfill_stage WHERE document_id = ANY(%s)",
            (doc_ids,),
        )
        stats.docs += len(doc_ids)
        stats.edges += n_rels

        emit = getattr(rag, "_emit_metric", None)
        if emit is not None:
            emit(
                "pgrg.backfill.code_graph",
                namespace=ns,
                docs=len(doc_ids),
                edges=n_rels,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

    if stats.skipped:
        logger.warning(
            "chunkshop code extractor unavailable; left %d staged code doc(s) "
            "across %d namespace(s) for a later run — re-run "
            "`pgrg backfill-code-graph` once chunkshop is installed",
            stats.skipped,
            stats.namespaces,
        )

    return stats


async def _extract_one(rag: GraphRAG, doc_id: int) -> dict:
    """Single-doc extraction. Raises on any extraction-pipeline error.

    Keep this as the only place that knows how to drive the extraction
    pipeline against already-stored chunks — _ingest_one_content has its own
    inline copy because it also has to write chunks first. The duplication is
    intentional: the ingest path is one big atomic transaction; the backfill
    path is post-hoc and operates on persisted chunks.
    """
    from pg_raggraph import _json_default
    from pg_raggraph.extraction import (
        config_with_prompt,
        extract_from_chunks,
        get_llm_provider,
        resolve_extraction_prompt,
    )
    from pg_raggraph.lede_extraction import ensure_lede_available, select_extractor
    from pg_raggraph.resolution import resolve_entity

    doc = await rag.db.fetch_one(
        "SELECT namespace, metadata FROM documents WHERE id = %s", (doc_id,)
    )
    if not doc:
        raise ValueError(f"document {doc_id} not found")
    ns = doc["namespace"]
    # #94: extract with the prompt this doc was ingested under (stamped into
    # documents.metadata at ingest), falling back to the namespace map, then
    # the worker's global config — the drain must not need the caller to
    # re-specify. An unknown stamped name raises → doc lands in 'failed'
    # with the error recorded, not silently extracted with the wrong prompt.
    prompt_name = resolve_extraction_prompt(
        rag.config,
        namespace=ns,
        stamped=(doc["metadata"] or {}).get("extraction_prompt"),
    )
    extract_config = config_with_prompt(rag.config, prompt_name)

    chunk_rows = await rag.db.fetch_all(
        "SELECT id, content, embedded_content, token_count, metadata "
        "FROM chunks WHERE document_id = %s ORDER BY id",
        (doc_id,),
    )
    chunk_ids = [r["id"] for r in chunk_rows]
    chunks = [
        {
            "content": r["content"],
            "embedded_content": r["embedded_content"] or r["content"],
            "token_count": r["token_count"] or 0,
            "metadata": r["metadata"] or {},
        }
        for r in chunk_rows
    ]

    # No chunks → nothing to extract; record terminal state and move on.
    if not chunks:
        await _mark_ready(rag, doc_id)
        return {"entities": 0, "rels": 0}

    lede_fn, _needs_llm = select_extractor(rag.config)
    llm = None
    if lede_fn is not None:
        ensure_lede_available()
        extract_fn = lede_fn
    else:
        extract_fn = extract_from_chunks
    # llm+lede sets both lede_fn AND _needs_llm — it still wants the
    # provider; without one it degrades to its deterministic leg.
    if _needs_llm and not rag.config.skip_extraction and rag.config.llm_base_url:
        if rag._llm is None:
            rag._llm = get_llm_provider(rag.config)
        llm = rag._llm
    if lede_fn is None and llm is None:
        # No extractor configured — pure-vector mode. Flip to ready since
        # there's nothing meaningful to backfill.
        await _mark_ready(rag, doc_id)
        return {"entities": 0, "rels": 0}

    extraction_results = await extract_fn(chunks, llm, rag.db, extract_config)

    # Yield accounting (issue #93): errored chunks return failure-marked
    # results indistinguishable from empty ones by shape alone. Count them
    # so error-driven emptiness never masquerades as a clean 'ready'.
    chunks_failed = sum(1 for r in extraction_results if r.failed)
    failure_summary = None
    if chunks_failed:
        first_error = next(
            (r.error for r in extraction_results if r.failed and r.error),
            "unknown error",
        )
        failure_summary = (
            f"extraction failed on {chunks_failed}/{len(chunks)} chunks: {first_error}"
        )

    unique_entities: dict[str, dict] = {}
    chunk_to_entities: list[list[str]] = []
    chunk_to_rels: list[list[tuple]] = []
    for extraction in extraction_results:
        names: list[str] = []
        for ent in extraction.entities:
            if ent.name not in unique_entities:
                unique_entities[ent.name] = {
                    "entity_type": ent.entity_type,
                    "description": ent.description,
                    "properties": {},
                }
            else:
                existing_desc = unique_entities[ent.name]["description"]
                if ent.description and ent.description not in existing_desc:
                    unique_entities[ent.name]["description"] += " " + ent.description
            names.append(ent.name)
        chunk_to_entities.append(names)
        chunk_to_rels.append(
            [
                (
                    r.source,
                    r.target,
                    r.rel_type,
                    r.description,
                    r.weight,
                )
                for r in extraction.relationships
            ]
        )

    if not unique_entities:
        if chunks_failed:
            # Zero yield AND errored chunks → 'failed', not 'ready'. A doc
            # that legitimately contains no entities (no chunk errored)
            # stays plain ready below — zero yield alone is not an error.
            raise ExtractionFailedError(failure_summary, chunks_failed=chunks_failed)
        await _mark_ready(
            rag,
            doc_id,
            extraction_meta=_yield_meta(len(chunks), 0, 0, 0),
        )
        return {"entities": 0, "rels": 0, "chunks_failed": 0}

    embedder = rag._get_embedder()
    # Sorted, not insertion order: concurrent doc transactions (GAP-007
    # parallel fan-out) resolving shared entities take row locks in
    # resolve_entity — a deterministic order prevents ABBA deadlocks.
    names_list = sorted(unique_entities.keys())
    entity_texts = [f"{name} {unique_entities[name]['description']}" for name in names_list]
    entity_embeddings = await rag._embed_texts_with_cache(entity_texts, embedder)

    rel_count = 0
    async with rag.db.transaction() as tx:
        entity_name_to_id: dict[str, int] = {}
        for name, emb in zip(names_list, entity_embeddings):
            info = unique_entities[name]
            eid = await resolve_entity(
                name=name,
                entity_type=info["entity_type"],
                description=info["description"],
                embedding=emb,
                namespace=ns,
                db=tx,
                config=rag.config,
                properties=info.get("properties") or {},
            )
            entity_name_to_id[name] = eid

        for i, chunk_id in enumerate(chunk_ids):
            if i >= len(chunk_to_entities):
                break
            seen: set[str] = set()
            for ent_name in chunk_to_entities[i]:
                if ent_name in seen or ent_name not in entity_name_to_id:
                    continue
                seen.add(ent_name)
                await tx.execute(
                    "INSERT INTO entity_chunks (entity_id, chunk_id, confidence) "
                    "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (entity_name_to_id[ent_name], chunk_id, 1.0),
                )

        for i, chunk_id in enumerate(chunk_ids):
            if i >= len(chunk_to_rels):
                break
            for rel in chunk_to_rels[i]:
                src_id = entity_name_to_id.get(rel[0])
                dst_id = entity_name_to_id.get(rel[1])
                if not (src_id and dst_id):
                    continue
                # ON CONFLICT … DO UPDATE preserves the existing row's id (so
                # relationship_chunks below still resolves) and keeps the
                # strongest weight seen across extractions. Idempotent under
                # crash-recovery re-extraction (PR-002 / migration 013).
                rel_id = await tx.insert_returning_id(
                    "INSERT INTO relationships "
                    "(namespace, src_id, dst_id, rel_type, weight, description, "
                    "effective_from, effective_to, retracted, retracted_at, properties) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) "
                    "ON CONFLICT (namespace, src_id, dst_id, rel_type) DO UPDATE "
                    "SET weight = GREATEST(relationships.weight, EXCLUDED.weight) "
                    "RETURNING id",
                    (
                        ns,
                        src_id,
                        dst_id,
                        rel[2],
                        rel[4],
                        rel[3],
                        None,
                        None,
                        False,
                        None,
                        json.dumps({}, default=_json_default),
                    ),
                )
                await tx.execute(
                    "INSERT INTO relationship_chunks "
                    "(relationship_id, chunk_id, confidence) "
                    "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (rel_id, chunk_id, 1.0),
                )
                rel_count += 1

        # Partial yield with errored chunks → still 'ready' (the graph that
        # DID extract is usable) but graph_error preserves the failure
        # summary so status surfaces can show the degradation (issue #93).
        # Clean extraction keeps the pre-existing graph_error = NULL.
        await tx.execute(
            "UPDATE documents SET graph_status = 'ready', "
            "graph_extracted_at = now(), graph_error = %s, "
            "metadata = metadata || %s::jsonb "
            "WHERE id = %s",
            (
                failure_summary[:2000] if failure_summary else None,
                json.dumps(
                    _yield_meta(len(chunks), chunks_failed, len(unique_entities), rel_count)
                ),
                doc_id,
            ),
        )

    return {
        "entities": len(unique_entities),
        "rels": rel_count,
        "chunks_failed": chunks_failed,
    }


def _yield_meta(chunks: int, chunks_failed: int, entities: int, relationships: int) -> dict:
    """Per-doc extraction yield persisted to documents.metadata JSONB (#93)."""
    return {
        "extraction": {
            "chunks": chunks,
            "chunks_failed": chunks_failed,
            "entities": entities,
            "relationships": relationships,
        }
    }


async def _mark_ready(rag: GraphRAG, doc_id: int, extraction_meta: dict | None = None) -> None:
    if extraction_meta is None:
        await rag.db.execute(
            "UPDATE documents SET graph_status = 'ready', "
            "graph_extracted_at = now(), graph_error = NULL "
            "WHERE id = %s",
            (doc_id,),
        )
        return
    await rag.db.execute(
        "UPDATE documents SET graph_status = 'ready', "
        "graph_extracted_at = now(), graph_error = NULL, "
        "metadata = metadata || %s::jsonb "
        "WHERE id = %s",
        (json.dumps(extraction_meta), doc_id),
    )
