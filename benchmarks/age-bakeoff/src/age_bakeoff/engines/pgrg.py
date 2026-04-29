"""pg-raggraph engine adapter — bypasses built-in ingest to preserve parity."""

from __future__ import annotations

import json
import time

from fastembed import TextEmbedding

from age_bakeoff.cost import CostTracker
from age_bakeoff.engines.base import EngineInfo, RetrievalResponse
from age_bakeoff.models import ExtractionOutput
from pg_raggraph import GraphRAG


class PgrgEngine:
    """Writes extraction output directly into pg-raggraph's schema, then
    delegates retrieval to ``GraphRAG.query()`` so the benchmark exercises
    the real retrieval code path.

    Schema columns (verified from pg-raggraph schema.sql):
      documents:     id, namespace, content_hash, source_path, metadata, created_at
      chunks:        id, document_id, content, embedding, search_vector, token_count, metadata, created_at
      entities:      id, namespace, name, entity_type, description, embedding, community_id, properties, created_at
      relationships: id, namespace, src_id, dst_id, rel_type, weight, description, properties, created_at
    """

    def __init__(
        self,
        dsn: str,
        namespace: str = "bakeoff",
        top_k: int = 10,
        hop_budget: int = 2,
        retrieval_mode: str = "hybrid",
        answer_model: str = "gpt-5-mini",
        embedding_model: str = "BAAI/bge-small-en-v1.5",
    ):
        self._namespace = namespace
        self._top_k = top_k
        self._hop_budget = hop_budget
        self._retrieval_mode = retrieval_mode
        self._answer_model = answer_model
        self._embedding_model = embedding_model
        self._embedder = TextEmbedding(model_name=embedding_model)
        self._rag = GraphRAG(dsn=dsn, namespace=namespace, embedding_dim=384)
        self._connected = False

    async def _ensure_connected(self) -> None:
        if not self._connected:
            await self._rag.connect()
            self._connected = True

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return [list(v) for v in self._embedder.embed(texts)]

    async def ingest(self, extraction: ExtractionOutput) -> None:
        await self._ensure_connected()
        ns = self._namespace

        # Wipe previous data for idempotency. delete() runs in its own
        # short transaction, before we open the long ingest transaction.
        await self._rag.delete(ns)

        # Embed all chunks and entities (CPU work, no DB).
        chunk_embs = self._embed([c.content for c in extraction.chunks])
        ent_embs = (
            self._embed([e.name + " " + e.description for e in extraction.entities])
            if extraction.entities
            else []
        )

        # F1: one Transaction holds a single connection across every INSERT,
        # eliminating ~10K-50K per-row pool checkouts and `register_vector_async`
        # calls. Per-row commits become a single COMMIT at __aexit__.
        async with self._rag.db.transaction() as tx:
            # ---- documents ----
            docs_by_id: dict[str, list[int]] = {}
            for idx, c in enumerate(extraction.chunks):
                docs_by_id.setdefault(c.document_id, []).append(idx)

            doc_pk_by_id: dict[str, int] = {}
            for doc_id in docs_by_id:
                row = await tx.fetch_one(
                    "INSERT INTO documents (namespace, source_path, content_hash) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (ns, doc_id, doc_id),
                )
                doc_pk_by_id[doc_id] = row["id"]

            # ---- chunks ----
            # Bakeoff Chunk is single-content; embedded_content mirrors content so
            # pg-raggraph's retrieval SELECT ``c.embedded_content AS content`` and
            # the FTS trigger both find something to index.
            chunk_pk_by_idx: dict[int, int] = {}
            for idx, (chunk, emb) in enumerate(zip(extraction.chunks, chunk_embs)):
                meta = dict(chunk.metadata)
                meta["sequence"] = chunk.sequence
                row = await tx.fetch_one(
                    "INSERT INTO chunks "
                    "(document_id, content, embedded_content, embedding, token_count, metadata) "
                    "VALUES (%s, %s, %s, %s::vector, %s, %s) RETURNING id",
                    (
                        doc_pk_by_id[chunk.document_id],
                        chunk.content,
                        chunk.content,
                        emb,
                        len(chunk.content.split()),
                        json.dumps(meta),
                    ),
                )
                chunk_pk_by_idx[idx] = row["id"]

            # ---- entities ----
            ent_pk_by_id: dict[str, int] = {}
            for ent, emb in zip(extraction.entities, ent_embs):
                row = await tx.fetch_one(
                    "INSERT INTO entities (namespace, name, entity_type, description, embedding, properties) "
                    "VALUES (%s, %s, %s, %s, %s::vector, %s) "
                    "ON CONFLICT (namespace, name) DO UPDATE SET description = EXCLUDED.description "
                    "RETURNING id",
                    (
                        ns,
                        ent.name,
                        ent.entity_type,
                        ent.description,
                        emb,
                        json.dumps(ent.properties),
                    ),
                )
                ent_pk_by_id[ent.id] = row["id"]

            # F2: build link rows in Python first, then one executemany per
            # table. Replaces O(C×E) and O(R×C) nested-loop round-trips with
            # in-memory substring scans + two batched inserts.

            # Inverted index: entity_name_lower -> list of (chunk_idx, chunk_pk).
            # Built in one pass over chunks; relationship linkage reuses it
            # without re-scanning chunk text.
            chunk_text_lower: list[str] = [c.content.lower() for c in extraction.chunks]

            entity_to_chunk_idxs: dict[str, list[int]] = {}
            for ent in extraction.entities:
                name_lower = ent.name.lower()
                if name_lower in entity_to_chunk_idxs:
                    continue  # entity-name dedup
                hits: list[int] = [
                    idx for idx, text in enumerate(chunk_text_lower) if name_lower in text
                ]
                entity_to_chunk_idxs[name_lower] = hits

            # ---- entity_chunks (provenance links) ----
            entity_chunk_rows: list[tuple] = []
            for ent in extraction.entities:
                ent_pk = ent_pk_by_id[ent.id]
                for chunk_idx in entity_to_chunk_idxs[ent.name.lower()]:
                    entity_chunk_rows.append(
                        (ent_pk, chunk_pk_by_idx[chunk_idx], 1.0)
                    )
            await tx.executemany(
                "INSERT INTO entity_chunks (entity_id, chunk_id, confidence) "
                "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                entity_chunk_rows,
            )

            # ---- relationships + relationship_chunks ----
            ent_id_to_name: dict[str, str] = {
                e.id: e.name.lower() for e in extraction.entities
            }
            relationship_chunk_rows: list[tuple] = []
            for rel in extraction.relationships:
                if rel.src_id not in ent_pk_by_id or rel.dst_id not in ent_pk_by_id:
                    continue
                row = await tx.fetch_one(
                    "INSERT INTO relationships (namespace, src_id, dst_id, rel_type, weight, description, properties) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        ns,
                        ent_pk_by_id[rel.src_id],
                        ent_pk_by_id[rel.dst_id],
                        rel.rel_type,
                        rel.weight,
                        rel.description,
                        json.dumps(rel.properties),
                    ),
                )
                rel_pk = row["id"]
                src_name = ent_id_to_name.get(rel.src_id, "")
                dst_name = ent_id_to_name.get(rel.dst_id, "")
                # Union of chunk indexes mentioning either endpoint, dedup'd
                src_idxs = set(entity_to_chunk_idxs.get(src_name, []))
                dst_idxs = set(entity_to_chunk_idxs.get(dst_name, []))
                for chunk_idx in src_idxs | dst_idxs:
                    relationship_chunk_rows.append(
                        (rel_pk, chunk_pk_by_idx[chunk_idx], 1.0)
                    )
            await tx.executemany(
                "INSERT INTO relationship_chunks (relationship_id, chunk_id, confidence) "
                "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                relationship_chunk_rows,
            )

    async def retrieve(self, question: str) -> RetrievalResponse:
        await self._ensure_connected()
        # Drive top_k into GraphRAG's retriever. Without this, self._top_k only
        # post-slices whatever GraphRAG returned under its own config.top_k
        # (default 10), making any top_k sweep above that degenerate on pgrg.
        self._rag.config.top_k = self._top_k
        t0 = time.perf_counter()
        result = await self._rag.query(
            question, mode=self._retrieval_mode, namespace=self._namespace
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        # QueryResult.chunks is list[ChunkResult] with .content, .chunk_id, .document_source
        chunks = result.chunks or []
        # Keep the post-slice as a safety net -- GraphRAG may return slightly
        # more than top_k in some retrieval modes.
        top = chunks[: self._top_k]
        return RetrievalResponse(
            retrieved_chunk_ids=[f"{c.document_source or 'unknown'}::{c.chunk_id}" for c in top],
            retrieved_chunk_contents=[c.content for c in top],
            retrieval_ms=elapsed_ms,
        )

    async def generate_answer(
        self,
        question: str,
        retrieved_contents: list[str],
        tracker: CostTracker | None = None,
    ) -> tuple[str, float]:
        from age_bakeoff.engines.openai_answerer import generate_answer

        t0 = time.perf_counter()
        answer = await generate_answer(
            question,
            retrieved_contents,
            model=self._answer_model,
            tracker=tracker,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return answer, elapsed_ms

    def info(self) -> EngineInfo:
        return EngineInfo(
            name="pgrg",
            embedding_model=self._embedding_model,
            answer_model=self._answer_model,
            top_k=self._top_k,
            hop_budget=self._hop_budget,
        )

    async def cleanup(self) -> None:
        if self._connected:
            await self._rag.close()
            self._connected = False
