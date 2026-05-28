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

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pg_raggraph import GraphRAG

logger = logging.getLogger("pg_raggraph.backfill")


@dataclass
class ExtractStats:
    """Per-call extraction outcome — what was claimed vs what succeeded."""

    claimed: int = 0
    ready: int = 0
    failed: int = 0
    entities: int = 0
    relationships: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)


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
    for doc_id in doc_ids:
        stats.claimed += 1
        try:
            per_doc = await _extract_one(rag, doc_id)
            stats.ready += 1
            stats.entities += per_doc["entities"]
            stats.relationships += per_doc["rels"]
        except Exception as e:
            stats.failed += 1
            err = f"{type(e).__name__}: {e}"
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
            entities=stats.entities,
            relationships=stats.relationships,
            latency_ms=(time.perf_counter() - t0) * 1000,
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
    from pg_raggraph.extraction import extract_from_chunks, get_llm_provider
    from pg_raggraph.lede_extraction import ensure_lede_available, select_extractor
    from pg_raggraph.resolution import resolve_entity

    doc = await rag.db.fetch_one("SELECT namespace FROM documents WHERE id = %s", (doc_id,))
    if not doc:
        raise ValueError(f"document {doc_id} not found")
    ns = doc["namespace"]

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
    if lede_fn is not None:
        ensure_lede_available()
        extract_fn = lede_fn
        llm = None
    elif not rag.config.skip_extraction and rag.config.llm_base_url:
        if rag._llm is None:
            rag._llm = get_llm_provider(rag.config)
        llm = rag._llm
        extract_fn = extract_from_chunks
    else:
        # No extractor configured — pure-vector mode. Flip to ready since
        # there's nothing meaningful to backfill.
        await _mark_ready(rag, doc_id)
        return {"entities": 0, "rels": 0}

    extraction_results = await extract_fn(chunks, llm, rag.db, rag.config)

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
        await _mark_ready(rag, doc_id)
        return {"entities": 0, "rels": 0}

    embedder = rag._get_embedder()
    names_list = list(unique_entities.keys())
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

        await tx.execute(
            "UPDATE documents SET graph_status = 'ready', "
            "graph_extracted_at = now(), graph_error = NULL "
            "WHERE id = %s",
            (doc_id,),
        )

    return {"entities": len(unique_entities), "rels": rel_count}


async def _mark_ready(rag: GraphRAG, doc_id: int) -> None:
    await rag.db.execute(
        "UPDATE documents SET graph_status = 'ready', "
        "graph_extracted_at = now(), graph_error = NULL "
        "WHERE id = %s",
        (doc_id,),
    )
