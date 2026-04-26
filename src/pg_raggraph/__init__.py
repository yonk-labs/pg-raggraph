"""pg-raggraph — PostgreSQL-native GraphRAG."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

__version__ = "0.3.0"

from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import QueryResult

__all__ = ["GraphRAG", "PGRGConfig", "QueryResult", "__version__"]

logger = logging.getLogger("pg_raggraph")

_NAMESPACE_RE = re.compile(r"^[a-zA-Z0-9_\-\.]{1,64}$")


def _validate_namespace(ns: str) -> None:
    if not _NAMESPACE_RE.match(ns):
        raise ValueError(
            f"Invalid namespace '{ns}'. Must be 1-64 chars, "
            "alphanumeric/hyphens/underscores/dots only."
        )


class GraphRAG:
    """Main entry point for pg-raggraph.

    Usage:
        async with GraphRAG("postgresql://localhost/mydb") as rag:
            await rag.ingest(["./docs/"])
            result = await rag.query("How does auth work?")
            for chunk in result.chunks:
                print(chunk.content)
    """

    def __init__(self, dsn: str | None = None, **kwargs):
        if dsn:
            kwargs["dsn"] = dsn
        self.config = PGRGConfig(**kwargs)
        self._db = None
        self._embedder = None
        self._llm = None  # Shared LLM provider; closed with the instance

    async def connect(self):
        from pg_raggraph.db import Database

        self._db = Database(self.config)
        try:
            await self._db.connect()
        except Exception as e:
            raise ConnectionError(
                f"Cannot connect to PostgreSQL at {self.config.dsn}. "
                f"Is the database running? Error: {e}"
            ) from e

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None
        if self._llm is not None and hasattr(self._llm, "aclose"):
            await self._llm.aclose()
            self._llm = None
        self._embedder = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    @property
    def db(self):
        if self._db is None:
            raise RuntimeError("Not connected. Call connect() or use async with.")
        return self._db

    def _get_embedder(self):
        if self._embedder is None:
            from pg_raggraph.embedding import get_embedding_provider

            self._embedder = get_embedding_provider(self.config)
        return self._embedder

    async def ingest(
        self,
        paths: list[str],
        namespace: str | None = None,
        on_progress=None,
        *,
        metadata: dict | None = None,
    ):
        """Ingest documents from file paths with parallel processing.

        Optimizations:
        - Parallel LLM extraction (extract_concurrency, default 8)
        - Batched entity embeddings (1 call instead of N)
        - Parallel document processing (doc_concurrency, default 4)
        - Content hash dedup

        Args:
            paths: File or directory paths to ingest.
            namespace: Namespace for data isolation.
            on_progress: Optional callback(message: str) for progress updates.
            metadata: Per-ingest evolution hints applied to every file in this
                call. Optional keys: ``effective_from``, ``effective_to``,
                ``retracted``, ``retracted_at``, ``retraction_reason``,
                ``version_label``, ``supersedes_document_id``. When
                ``version_label``, ``supersedes_document_id``, or
                ``retraction_reason`` is present, a ``document_versions`` row
                is also created mirroring the document's evolution metadata.
        """
        import asyncio

        from pg_raggraph.chunking import chunk_document, content_hash
        from pg_raggraph.extraction import extract_from_chunks, get_llm_provider

        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        embedder = self._get_embedder()

        def _progress(msg: str):
            logger.info(msg)
            if on_progress:
                on_progress(msg)

        # Directories to skip when walking — avoid vendored code, build artifacts,
        # model checkpoints, etc.
        SKIP_DIRS = {
            ".git",
            ".venv",
            "venv",
            "node_modules",
            "target",  # Rust build
            "dist",
            "build",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
            ".tox",
            "checkpoints",
            "models",
            ".cargo",
            ".idea",
            ".vscode",
            "site-packages",
            ".autonomy",
            "skill-output",
        }
        SUPPORTED_EXTS = (
            ".md",
            ".txt",
            ".py",
            ".ts",
            ".js",
            ".tsx",
            ".jsx",
            ".go",
            ".rs",
            ".java",
            ".rst",
        )

        # Collect and validate file paths
        file_paths = []
        for p in paths:
            if os.path.isdir(p):
                for root, dirs, files in os.walk(p):
                    # Prune skipped dirs in-place so we don't descend into them
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                    for f in files:
                        if f.endswith(SUPPORTED_EXTS):
                            file_paths.append(os.path.join(root, f))
            elif os.path.isfile(p):
                file_paths.append(p)
            else:
                raise FileNotFoundError(f"Path not found: {p}")

        if not file_paths:
            logger.warning("No supported files found in provided paths.")
            return

        _progress(f"Found {len(file_paths)} files to process.")

        # Process documents in parallel batches
        doc_sem = asyncio.Semaphore(self.config.doc_concurrency)
        # LLM is optional — without it, ingest stores chunks+embeddings only
        # (pure vector RAG mode). Reuse the shared provider if already created
        # so the connection pool is shared across ingest() calls.
        llm = None
        if not self.config.skip_extraction and self.config.llm_base_url:
            if self._llm is None:
                try:
                    self._llm = get_llm_provider(self.config)
                except Exception as e:
                    logger.warning(f"LLM provider unavailable, skipping extraction: {e}")
            llm = self._llm
        if llm is None:
            _progress("Extraction disabled — ingesting as pure vector RAG.")

        stats = {
            "ingested": 0,
            "skipped": 0,
            "failed": 0,
            "degraded": 0,
            "entities": 0,
            "rels": 0,
        }

        async def _process_file(idx: int, file_path: str):
            # Retry on transient serialization / deadlock errors from
            # concurrent ingestion. Exponential backoff, max 3 attempts.
            async with doc_sem:
                attempt = 0
                while True:
                    attempt += 1
                    try:
                        r = await self._ingest_one_file(
                            file_path,
                            ns,
                            embedder,
                            llm,
                            content_hash,
                            chunk_document,
                            extract_from_chunks,
                            metadata=metadata,
                        )
                        if r:
                            stats["ingested"] += 1
                            stats["entities"] += r["entities"]
                            stats["rels"] += r["rels"]
                            if r.get("degraded"):
                                stats["degraded"] += 1
                            deg_note = (
                                " (extraction failed, vector-only)" if r.get("degraded") else ""
                            )
                            _progress(
                                f"[{idx}/{len(file_paths)}] "
                                f"{os.path.basename(file_path)}: "
                                f"{r['entities']} entities, {r['rels']} rels{deg_note}"
                            )
                        else:
                            stats["skipped"] += 1
                        return
                    except Exception as e:
                        # Postgres deadlock = SQLSTATE 40P01, serialization = 40001.
                        # Prefer the structured sqlstate attribute (psycopg3) over
                        # string matching, which breaks on non-English PG builds.
                        sqlstate = getattr(e, "sqlstate", None)
                        msg = str(e)
                        transient = sqlstate in ("40P01", "40001") or (
                            sqlstate is None
                            and (
                                "40P01" in msg
                                or "40001" in msg
                                or "deadlock detected" in msg
                                or "could not serialize" in msg
                            )
                        )
                        if transient and attempt < 3:
                            backoff = 0.2 * (2 ** (attempt - 1))
                            logger.info(
                                f"Retry {attempt}/3 after {backoff:.1f}s for "
                                f"{file_path}: {msg[:80]}"
                            )
                            await asyncio.sleep(backoff)
                            continue
                        logger.warning(f"Failed {file_path}: {e}")
                        stats["failed"] += 1
                        return

        await asyncio.gather(*[_process_file(i + 1, fp) for i, fp in enumerate(file_paths)])

        notes = []
        if stats["failed"]:
            notes.append(f"{stats['failed']} failed")
        if stats["degraded"]:
            notes.append(f"{stats['degraded']} degraded (vector-only, extraction error)")
        suffix = f", {', '.join(notes)}" if notes else ""
        _progress(
            f"Done: {stats['ingested']} ingested, {stats['skipped']} skipped"
            f"{suffix}. "
            f"{stats['entities']} entities, {stats['rels']} relationships."
        )

    async def _ingest_one_file(
        self,
        file_path,
        ns,
        embedder,
        llm,
        content_hash_fn,
        chunk_document_fn,
        extract_from_chunks_fn,
        *,
        metadata: dict | None = None,
    ):
        """Ingest a single file with all DB writes in a single transaction.

        Using db.transaction() ensures all chunks/entities/relationships for
        one doc commit atomically, and chunk_id from INSERT is immediately
        visible to entity_chunks INSERT on the same connection (no pool
        commit propagation race).
        """
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, ValueError):
            logger.warning(f"Skipping non-UTF-8 file: {file_path}")
            return None

        # Delta check (read-only)
        c_hash = content_hash_fn(content)
        existing = await self.db.fetch_one(
            "SELECT id FROM documents WHERE namespace = %s AND content_hash = %s",
            (ns, c_hash),
        )
        if existing:
            logger.debug(f"Skipped (unchanged): {file_path}")
            return None

        # Chunk (no DB)
        chunks = chunk_document_fn(content, source_path=file_path, config=self.config)
        if not chunks:
            return {"entities": 0, "rels": 0}

        # Batch embed all chunks. Use embedded_content so the embedder sees
        # heading prefix (hierarchy strategy) or any future neighbor/summary
        # decoration; for auto strategy this equals content.
        texts = [c["embedded_content"] for c in chunks]
        chunk_embeddings = await embedder.embed(texts)

        # Extract entities/relationships via LLM (cache reads OK outside txn).
        # If llm is None, skip extraction entirely — pure vector RAG mode.
        extraction_degraded = False
        if llm is None:
            from pg_raggraph.models import ExtractionResult

            extraction_results = [ExtractionResult() for _ in chunks]
        else:
            try:
                extraction_results = await extract_from_chunks_fn(
                    chunks, llm, self.db, self.config
                )
            except Exception as e:
                logger.warning(f"Extraction failed for {file_path}, ingesting as pure vector: {e}")
                from pg_raggraph.models import ExtractionResult

                extraction_results = [ExtractionResult() for _ in chunks]
                extraction_degraded = True

        # Dedupe entities by name, build per-chunk entity/rel lists
        unique_entities = {}
        chunk_to_entities = []
        chunk_to_rels = []

        for i, extraction in enumerate(extraction_results):
            entity_names = []
            for ent in extraction.entities:
                if ent.name not in unique_entities:
                    unique_entities[ent.name] = {
                        "entity_type": ent.entity_type,
                        "description": ent.description,
                        "chunks": [i],
                    }
                else:
                    unique_entities[ent.name]["chunks"].append(i)
                    existing_desc = unique_entities[ent.name]["description"]
                    if ent.description and ent.description not in existing_desc:
                        unique_entities[ent.name]["description"] += " " + ent.description
                entity_names.append(ent.name)
            chunk_to_entities.append(entity_names)
            chunk_to_rels.append(
                [
                    (r.source, r.target, r.rel_type, r.description, r.weight)
                    for r in extraction.relationships
                ]
            )

        # Batch embed entities (no DB)
        if unique_entities:
            entity_names_list = list(unique_entities.keys())
            entity_texts = [
                f"{name} {unique_entities[name]['description']}" for name in entity_names_list
            ]
            entity_embeddings = await embedder.embed(entity_texts)
        else:
            entity_names_list = []
            entity_embeddings = []

        # All DB writes in a single transaction
        from pg_raggraph.resolution import resolve_entity

        async with self.db.transaction() as tx:
            # Incremental update: if source_path exists with a DIFFERENT hash,
            # the file has changed. Delete the stale document inside the same
            # transaction as the new insert so any failure mid-ingest rolls
            # back both the delete and the insert — the old version stays
            # visible until the new one commits. FK cascades take care of
            # chunks and the entity/relationship provenance joins. Call
            # prune_orphans() afterwards to clean up unreferenced entities.
            stale = await tx.fetch_one(
                "SELECT id FROM documents "
                "WHERE namespace = %s AND source_path = %s AND content_hash != %s",
                (ns, file_path, c_hash),
            )
            if stale:
                await tx.execute("DELETE FROM documents WHERE id = %s", (stale["id"],))
                logger.info(f"Replaced stale version of {file_path}")

            # Insert document with any caller-supplied evolution metadata.
            # ON CONFLICT uses COALESCE so a re-ingest without metadata doesn't
            # clobber previously-stored evolution fields. For `retracted` we
            # distinguish "absent from meta" (preserve prior value) from
            # "explicitly True/False" (apply the caller's value, including
            # un-retracting). COALESCE can't express this for booleans, so we
            # pass a separate `retracted_explicit` flag and gate the SET on it
            # via CASE WHEN.
            meta = metadata or {}
            eff_from = meta.get("effective_from")
            eff_to = meta.get("effective_to")
            retracted_explicit = "retracted" in meta and meta["retracted"] is not None
            # Value for fresh INSERT: the caller's value if explicit, else
            # False (matches the column DEFAULT). On UPDATE the CASE WHEN
            # below decides whether to apply it at all.
            retracted_value = bool(meta["retracted"]) if retracted_explicit else False
            version_label = meta.get("version_label")
            supersedes_doc = meta.get("supersedes_document_id")

            doc_id = await tx.insert_returning_id(
                "INSERT INTO documents "
                "(namespace, content_hash, source_path, "
                " effective_from, effective_to, retracted, version_label) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (namespace, content_hash) DO UPDATE "
                "SET source_path = EXCLUDED.source_path, "
                "    effective_from = COALESCE("
                "EXCLUDED.effective_from, documents.effective_from), "
                "    effective_to = COALESCE("
                "EXCLUDED.effective_to, documents.effective_to), "
                "    retracted = CASE WHEN %s "
                "THEN EXCLUDED.retracted ELSE documents.retracted END, "
                "    version_label = COALESCE("
                "EXCLUDED.version_label, documents.version_label) "
                "RETURNING id",
                (
                    ns,
                    c_hash,
                    file_path,
                    eff_from,
                    eff_to,
                    retracted_value,
                    version_label,
                    retracted_explicit,
                ),
            )

            # If caller supplied version info or a supersession edge, create a
            # document_versions row for authoritative multi-version tracking.
            if version_label or supersedes_doc or meta.get("retraction_reason"):
                await tx.execute(
                    "INSERT INTO document_versions "
                    "(namespace, document_id, version_label, effective_from, effective_to, "
                    " supersedes_document_id, retracted, retracted_at, retraction_reason) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        ns,
                        doc_id,
                        version_label,
                        eff_from,
                        eff_to,
                        supersedes_doc,
                        retracted_value,
                        meta.get("retracted_at"),
                        meta.get("retraction_reason"),
                    ),
                )

            # Insert all chunks
            chunk_ids = []
            for i, chunk in enumerate(chunks):
                chunk_id = await tx.insert_returning_id(
                    "INSERT INTO chunks "
                    "(document_id, content, embedded_content, embedding, token_count, metadata) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        doc_id,
                        chunk["content"],
                        chunk["embedded_content"],
                        chunk_embeddings[i],
                        chunk["token_count"],
                        json.dumps(chunk["metadata"]),
                    ),
                )
                chunk_ids.append(chunk_id)

            if not unique_entities:
                return {"entities": 0, "rels": 0}

            # Resolve and insert entities (tx duck-types the db interface)
            entity_name_to_id = {}
            for name, emb in zip(entity_names_list, entity_embeddings):
                info = unique_entities[name]
                eid = await resolve_entity(
                    name=name,
                    entity_type=info["entity_type"],
                    description=info["description"],
                    embedding=emb,
                    namespace=ns,
                    db=tx,
                    config=self.config,
                )
                entity_name_to_id[name] = eid

            # Insert entity_chunks links
            for i, chunk_id in enumerate(chunk_ids):
                if i >= len(chunk_to_entities):
                    break
                seen = set()
                for ent_name in chunk_to_entities[i]:
                    if ent_name in seen or ent_name not in entity_name_to_id:
                        continue
                    seen.add(ent_name)
                    await tx.execute(
                        "INSERT INTO entity_chunks (entity_id, chunk_id, confidence) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (entity_name_to_id[ent_name], chunk_id, 1.0),
                    )

            # Insert relationships and their chunk links
            rel_count = 0
            for i, chunk_id in enumerate(chunk_ids):
                if i >= len(chunk_to_rels):
                    break
                for rel in chunk_to_rels[i]:
                    src_id = entity_name_to_id.get(rel[0])
                    dst_id = entity_name_to_id.get(rel[1])
                    if not (src_id and dst_id):
                        continue
                    rel_id = await tx.insert_returning_id(
                        "INSERT INTO relationships "
                        "(namespace, src_id, dst_id, rel_type, weight, description) "
                        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                        (ns, src_id, dst_id, rel[2], rel[4], rel[3]),
                    )
                    await tx.execute(
                        "INSERT INTO relationship_chunks "
                        "(relationship_id, chunk_id, confidence) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (rel_id, chunk_id, 1.0),
                    )
                    rel_count += 1

        return {
            "entities": len(unique_entities),
            "rels": rel_count,
            "degraded": extraction_degraded,
        }

    async def query(
        self,
        question: str,
        mode: str = "smart",
        namespace: str | None = None,
        *,
        as_of: datetime | None = None,
        version_filter: str | None = None,
        evolution_aware: bool | None = None,
    ) -> QueryResult:
        """Query the knowledge graph.

        Modes:
            smart (default) - confidence-triggered routing (naive → boost → expand)
            naive - vector + BM25 only (fastest)
            naive_boost - naive + 1-hop graph boost re-ranking
            local - vector seed → graph expansion via entity neighbors
            global - relationship-centric retrieval
            hybrid - local + global combined

        Evolution-aware kwargs (keyword-only):
            as_of: time-travel filter — restrict to documents whose effective
                window contains this timestamp.
            version_filter: restrict to documents with matching version_label.
            evolution_aware: when False, ignore evolution_tier for this query
                (forces classic retrieval). When None, honors config.
        """
        from pg_raggraph.retrieval import query as retrieval_query

        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        embedder = self._get_embedder()
        return await retrieval_query(
            question=question,
            db=self.db,
            embedder=embedder,
            config=self.config,
            mode=mode,
            namespace=ns,
            as_of=as_of,
            version_filter=version_filter,
            evolution_aware=evolution_aware,
        )

    async def ask(
        self,
        question: str,
        mode: str = "smart",
        namespace: str | None = None,
        *,
        as_of: datetime | None = None,
        version_filter: str | None = None,
        evolution_aware: bool | None = None,
    ) -> QueryResult:
        """Query + LLM answer synthesis.

        Runs retrieval then generates a grounded natural-language answer
        using the configured LLM. Falls back to a top-chunk summary if no
        LLM is configured — library stays useful as pure vector RAG.
        """
        from pg_raggraph.answer import generate_answer

        result = await self.query(
            question,
            mode=mode,
            namespace=namespace,
            as_of=as_of,
            version_filter=version_filter,
            evolution_aware=evolution_aware,
        )
        # Reuse the shared LLM client (same pool as ingestion).
        llm = None
        if self.config.llm_base_url:
            if self._llm is None:
                try:
                    from pg_raggraph.extraction import get_llm_provider

                    self._llm = get_llm_provider(self.config)
                except Exception as e:
                    logger.warning(f"LLM provider unavailable: {e}")
            llm = self._llm
        result.answer = await generate_answer(question, result, llm, self.config)
        return result

    async def status(self, namespace: str | None = None) -> dict:
        """Get graph statistics."""
        ns = namespace or self.config.namespace
        return {
            "schema_version": int(await self.db.get_meta("schema_version") or 0),
            "embedding_dim": int(await self.db.get_meta("embedding_dim") or 0),
            "namespace": ns,
            "documents": await self.db.count("documents", ns),
            # Chunks table has no namespace column — scope via documents join.
            "chunks": (
                await self.db.fetch_one(
                    "SELECT count(*) AS cnt FROM chunks c "
                    "JOIN documents d ON d.id = c.document_id "
                    "WHERE d.namespace = %s",
                    (ns,),
                )
            )["cnt"],
            "entities": await self.db.count("entities", ns),
            "relationships": await self.db.count("relationships", ns),
        }

    async def delete(self, namespace: str):
        """Delete all data in a namespace."""
        _validate_namespace(namespace)
        await self.db.execute("DELETE FROM documents WHERE namespace = %s", (namespace,))
        await self.db.execute("DELETE FROM entities WHERE namespace = %s", (namespace,))
        await self.db.execute("DELETE FROM relationships WHERE namespace = %s", (namespace,))

    async def delete_document(self, source_path: str, namespace: str | None = None) -> int:
        """Delete a document and all its chunks by source path.

        Entities and relationships are left in place — they may be referenced
        by other documents. Use `prune_orphans()` to clean up any entities
        that become unreferenced.

        Returns number of documents deleted.
        """
        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        result = await self.db.fetch_one(
            "DELETE FROM documents WHERE namespace = %s AND source_path = %s RETURNING id",
            (ns, source_path),
        )
        return 1 if result else 0

    async def delete_entity(self, entity_id: int) -> bool:
        """Delete an entity and its relationships by id."""
        result = await self.db.fetch_one(
            "DELETE FROM entities WHERE id = %s RETURNING id", (entity_id,)
        )
        return result is not None

    async def merge_entities(self, keep_id: int, merge_ids: list[int]) -> dict:
        """Merge one or more entities into a canonical one.

        Rewrites relationships and entity_chunks to point at `keep_id`,
        deduplicates any resulting duplicate edges, drops self-loops that
        the merge creates, then deletes the merged entities. All atomic.

        Raises ValueError if keep_id appears in merge_ids (would delete the
        canonical entity) or if merge_ids is empty.
        """
        if not merge_ids:
            raise ValueError("merge_ids must not be empty")
        if keep_id in merge_ids:
            raise ValueError(
                f"keep_id {keep_id} must not appear in merge_ids — "
                "that would delete the canonical entity"
            )

        async with self.db.transaction() as tx:
            # Verify all entities exist and share a namespace. Cross-namespace
            # merges are almost always a bug.
            rows = await tx.fetch_all(
                "SELECT id, namespace FROM entities WHERE id = ANY(%s)",
                ([keep_id, *merge_ids],),
            )
            found_ids = {r["id"] for r in rows}
            missing = set([keep_id, *merge_ids]) - found_ids
            if missing:
                raise ValueError(f"entities not found: {sorted(missing)}")
            namespaces = {r["namespace"] for r in rows}
            if len(namespaces) > 1:
                raise ValueError(f"cross-namespace merge refused: {sorted(namespaces)}")

            # Repoint relationships. After rewriting src_id and dst_id, any
            # edge whose src and dst both collapse to keep_id becomes a
            # self-loop — delete those. Remaining duplicates (same src, dst,
            # rel_type after the rewrite) collapse to one row each.
            await tx.execute(
                "UPDATE relationships SET src_id = %s WHERE src_id = ANY(%s)",
                (keep_id, merge_ids),
            )
            await tx.execute(
                "UPDATE relationships SET dst_id = %s WHERE dst_id = ANY(%s)",
                (keep_id, merge_ids),
            )
            # Drop self-loops created by the merge.
            await tx.execute(
                "DELETE FROM relationships WHERE src_id = dst_id AND (src_id = %s OR dst_id = %s)",
                (keep_id, keep_id),
            )
            # Collapse duplicate edges (keep the lowest id per group).
            await tx.execute(
                "DELETE FROM relationships a USING relationships b "
                "WHERE a.id > b.id AND a.src_id = b.src_id AND "
                "a.dst_id = b.dst_id AND a.rel_type = b.rel_type AND "
                "a.namespace = b.namespace AND (a.src_id = %s OR a.dst_id = %s)",
                (keep_id, keep_id),
            )

            # Copy entity_chunks rows from merged entities to keep_id,
            # deduping via ON CONFLICT, then delete the old rows.
            await tx.execute(
                "INSERT INTO entity_chunks (entity_id, chunk_id, confidence, provenance) "
                "SELECT %s, chunk_id, confidence, provenance FROM entity_chunks "
                "WHERE entity_id = ANY(%s) "
                "ON CONFLICT DO NOTHING",
                (keep_id, merge_ids),
            )
            await tx.execute(
                "DELETE FROM entity_chunks WHERE entity_id = ANY(%s)",
                (merge_ids,),
            )

            # Delete merged entities.
            await tx.execute("DELETE FROM entities WHERE id = ANY(%s)", (merge_ids,))

        return {"kept": keep_id, "merged_count": len(merge_ids)}

    async def prune_orphans(self, namespace: str | None = None) -> dict:
        """Delete entities and relationships with no chunk links."""
        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        # Count first, then delete — gives a clean int return value that's
        # easy to assert on in tests and log in production.
        ent_row = await self.db.fetch_one(
            "SELECT count(*) AS cnt FROM entities WHERE namespace = %s "
            "AND id NOT IN (SELECT DISTINCT entity_id FROM entity_chunks)",
            (ns,),
        )
        rel_row = await self.db.fetch_one(
            "SELECT count(*) AS cnt FROM relationships WHERE namespace = %s "
            "AND id NOT IN (SELECT DISTINCT relationship_id FROM relationship_chunks)",
            (ns,),
        )
        entities_pruned = ent_row["cnt"] if ent_row else 0
        relationships_pruned = rel_row["cnt"] if rel_row else 0
        await self.db.execute(
            "DELETE FROM entities WHERE namespace = %s AND id NOT IN "
            "(SELECT DISTINCT entity_id FROM entity_chunks)",
            (ns,),
        )
        await self.db.execute(
            "DELETE FROM relationships WHERE namespace = %s AND id NOT IN "
            "(SELECT DISTINCT relationship_id FROM relationship_chunks)",
            (ns,),
        )
        return {
            "entities_pruned": entities_pruned,
            "relationships_pruned": relationships_pruned,
        }
