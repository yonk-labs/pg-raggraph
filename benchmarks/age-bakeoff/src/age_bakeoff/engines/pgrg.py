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
        db = self._rag.db
        ns = self._namespace

        # Wipe previous data for idempotency
        await self._rag.delete(ns)

        # Embed all chunks and entities
        chunk_embs = self._embed([c.content for c in extraction.chunks])
        ent_embs = (
            self._embed([e.name + " " + e.description for e in extraction.entities])
            if extraction.entities
            else []
        )

        # Group chunks by document_id
        docs_by_id: dict[str, list[int]] = {}
        for idx, c in enumerate(extraction.chunks):
            docs_by_id.setdefault(c.document_id, []).append(idx)

        # Insert documents
        doc_pk_by_id: dict[str, int] = {}
        for doc_id in docs_by_id:
            row = await db.fetch_one(
                "INSERT INTO documents (namespace, source_path, content_hash) "
                "VALUES (%s, %s, %s) RETURNING id",
                (ns, doc_id, doc_id),
            )
            doc_pk_by_id[doc_id] = row["id"]

        # Insert chunks (no sequence column in schema — use metadata for ordering).
        # Bakeoff Chunk is single-content; embedded_content mirrors content so
        # pg-raggraph's retrieval SELECT ``c.embedded_content AS content`` and
        # the FTS trigger both find something to index.
        chunk_pk_by_idx: dict[int, int] = {}
        for idx, (chunk, emb) in enumerate(zip(extraction.chunks, chunk_embs)):
            meta = dict(chunk.metadata)
            meta["sequence"] = chunk.sequence
            row = await db.fetch_one(
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

        # Insert entities (ON CONFLICT handles duplicate names within a corpus)
        ent_pk_by_id: dict[str, int] = {}
        for ent, emb in zip(extraction.entities, ent_embs):
            row = await db.fetch_one(
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

        # Build entity name -> entity PK mapping for linking chunks
        ent_name_to_pk: dict[str, int] = {}
        for ent in extraction.entities:
            ent_name_to_pk[ent.name.lower()] = ent_pk_by_id[ent.id]

        # Insert entity_chunks provenance links (required for graph retrieval).
        # Link each chunk to entities whose name appears in the chunk content.
        all_chunk_pks = list(chunk_pk_by_idx.values())
        for idx, chunk in enumerate(extraction.chunks):
            chunk_pk = chunk_pk_by_idx[idx]
            content_lower = chunk.content.lower()
            for ent in extraction.entities:
                if ent.name.lower() in content_lower:
                    await db.execute(
                        "INSERT INTO entity_chunks (entity_id, chunk_id, confidence) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (ent_pk_by_id[ent.id], chunk_pk, 1.0),
                    )

        # Build entity-id → name lookup for relationship_chunks linking
        ent_id_to_name: dict[str, str] = {e.id: e.name.lower() for e in extraction.entities}

        # Insert relationships + link to chunks that mention either endpoint
        for rel in extraction.relationships:
            if rel.src_id not in ent_pk_by_id or rel.dst_id not in ent_pk_by_id:
                continue
            row = await db.fetch_one(
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
            # Link relationship to chunks mentioning src or dst entity
            src_name = ent_id_to_name.get(rel.src_id, "")
            dst_name = ent_id_to_name.get(rel.dst_id, "")
            for idx, chunk in enumerate(extraction.chunks):
                content_lower = chunk.content.lower()
                if src_name in content_lower or dst_name in content_lower:
                    await db.execute(
                        "INSERT INTO relationship_chunks (relationship_id, chunk_id, confidence) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (rel_pk, chunk_pk_by_idx[idx], 1.0),
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
