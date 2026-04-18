"""Apache AGE engine adapter — Cypher graph + pgvector chunks."""
from __future__ import annotations

import asyncio
import json
import re
import time
from functools import partial

import psycopg
from fastembed import TextEmbedding

from age_bakeoff.cost import CostTracker
from age_bakeoff.engines.base import EngineInfo, RetrievalResponse
from age_bakeoff.models import ExtractionOutput


def _slugify(text: str) -> str:
    """Slugify a string to ``[a-z0-9_]`` — safe for Cypher string values."""
    return re.sub(r"[^a-z0-9_]", "_", text.lower())


def _strip_agtype(val: object) -> str:
    """AGE agtype values come with surrounding quotes — strip them."""
    return str(val).strip('"')


def _age_session(conn: psycopg.Connection) -> None:
    """Prepare a psycopg3 connection for AGE operations."""
    conn.execute("LOAD 'age'")
    conn.execute('SET search_path = ag_catalog, "$user", public')


class AgeEngine:
    """Writes extraction output into Apache AGE (Cypher graph) + pgvector
    chunks table, then retrieves by seeding with pgvector and expanding
    via Cypher multi-hop traversal.

    Graph operations use psycopg3 sync (wrapped in ``run_in_executor``)
    because AGE's ``LOAD 'age'`` session command and ``cypher()`` function
    calls are session-scoped and don't compose cleanly with async drivers.
    """

    def __init__(
        self,
        dsn: str,
        graph_name: str = "bakeoff",
        namespace: str = "bakeoff",
        top_k: int = 10,
        hop_budget: int = 2,
        retrieval_mode: str = "hybrid",
        answer_model: str = "gpt-5-mini",
        embedding_model: str = "BAAI/bge-small-en-v1.5",
    ):
        self._dsn = dsn
        self._graph_name = graph_name
        self._namespace = namespace
        self._top_k = top_k
        self._hop_budget = hop_budget
        self._retrieval_mode = retrieval_mode
        self._answer_model = answer_model
        self._embedding_model = embedding_model
        self._embedder = TextEmbedding(model_name=embedding_model)
        self._bootstrapped = False

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return [list(v) for v in self._embedder.embed(texts)]

    def _sync_bootstrap(self) -> None:
        """Create the chunks table (pgvector) and AGE graph (Cypher)."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS age_chunks (
                    id BIGSERIAL PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    sequence INT NOT NULL DEFAULT 0,
                    content TEXT NOT NULL,
                    embedding vector(384),
                    search_vector tsvector,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            # HNSW index for vector similarity
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_age_chunk_embed "
                "ON age_chunks USING hnsw (embedding vector_cosine_ops)"
            )
            # Full-text search index
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_age_chunk_search "
                "ON age_chunks USING gin (search_vector)"
            )
            # Trigger to auto-update search_vector
            conn.execute(
                """
                CREATE OR REPLACE FUNCTION age_update_search_vector() RETURNS trigger AS $$
                BEGIN
                    NEW.search_vector := to_tsvector('english', NEW.content);
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
            conn.execute("DROP TRIGGER IF EXISTS trg_age_chunk_search ON age_chunks")
            conn.execute(
                "CREATE TRIGGER trg_age_chunk_search "
                "BEFORE INSERT OR UPDATE OF content ON age_chunks "
                "FOR EACH ROW EXECUTE FUNCTION age_update_search_vector()"
            )
            conn.commit()

            # AGE graph setup
            _age_session(conn)
            # Drop existing graph for idempotency
            try:
                conn.execute(f"SELECT drop_graph('{self._graph_name}', true)")
                conn.commit()
            except Exception:
                conn.rollback()
                # search_path is lost after rollback — re-establish
                _age_session(conn)

            conn.execute(f"SELECT create_graph('{self._graph_name}')")
            conn.commit()

            # Create vertex and edge labels
            try:
                conn.execute(f"SELECT create_vlabel('{self._graph_name}', 'Entity')")
                conn.commit()
            except psycopg.errors.DuplicateObject:
                conn.rollback()
                _age_session(conn)

            # We'll create edge labels dynamically during ingest
        self._bootstrapped = True

    def _sync_ingest(self, extraction: ExtractionOutput) -> None:
        """Write chunks to SQL table and entities/relationships to AGE graph."""
        chunk_embs = self._embed([c.content for c in extraction.chunks])
        ent_embs = self._embed(
            [e.name + " " + e.description for e in extraction.entities]
        ) if extraction.entities else []

        with psycopg.connect(self._dsn) as conn:
            # Clear previous data for this namespace
            conn.execute(
                "DELETE FROM age_chunks WHERE namespace = %s", (self._namespace,)
            )
            conn.commit()

            # Insert chunks
            for chunk, emb in zip(extraction.chunks, chunk_embs):
                conn.execute(
                    "INSERT INTO age_chunks (namespace, document_id, sequence, content, embedding) "
                    "VALUES (%s, %s, %s, %s, %s::vector)",
                    (self._namespace, chunk.document_id, chunk.sequence, chunk.content, emb),
                )
            conn.commit()

            # Insert entities and relationships via Cypher
            _age_session(conn)

            # Create entities
            for ent, emb in zip(extraction.entities, ent_embs):
                eid = _slugify(ent.id)
                # Escape single quotes in strings for Cypher
                name = ent.name.replace("'", "\\'")
                etype = ent.entity_type.replace("'", "\\'")
                desc = ent.description.replace("'", "\\'")
                cypher = (
                    f"CREATE (n:Entity {{id: '{eid}', name: '{name}', "
                    f"entity_type: '{etype}', description: '{desc}'}}) RETURN n"
                )
                conn.execute(
                    f"SELECT * FROM cypher('{self._graph_name}', $$ {cypher} $$) AS (n agtype)"
                )
            conn.commit()

            # Collect unique edge labels and create them
            edge_labels: set[str] = set()
            for rel in extraction.relationships:
                label = _slugify(rel.rel_type).upper()
                if not label:
                    label = "RELATED_TO"
                edge_labels.add(label)

            for label in edge_labels:
                try:
                    conn.execute(
                        f"SELECT create_elabel('{self._graph_name}', '{label}')"
                    )
                    conn.commit()
                except (psycopg.errors.DuplicateObject, Exception):
                    conn.rollback()
                    # search_path is lost after rollback — re-establish
                    _age_session(conn)

            # Create relationships
            for rel in extraction.relationships:
                src = _slugify(rel.src_id)
                dst = _slugify(rel.dst_id)
                label = _slugify(rel.rel_type).upper() or "RELATED_TO"
                desc = rel.description.replace("'", "\\'")
                cypher = (
                    f"MATCH (a:Entity {{id: '{src}'}}), (b:Entity {{id: '{dst}'}}) "
                    f"CREATE (a)-[r:{label} {{description: '{desc}', weight: {rel.weight}}}]->(b) "
                    f"RETURN r"
                )
                try:
                    conn.execute(
                        f"SELECT * FROM cypher('{self._graph_name}', $$ {cypher} $$) AS (r agtype)"
                    )
                except Exception:
                    # If MATCH finds no vertices, the CREATE silently does nothing
                    pass
            conn.commit()

    def _sync_retrieve(self, question: str) -> RetrievalResponse:
        """Vector seed + Cypher expansion retrieval."""
        t0 = time.perf_counter()
        q_emb = self._embed([question])[0]

        with psycopg.connect(self._dsn) as conn:
            # Step 1: Vector seed — find top-K chunks by cosine similarity + BM25
            tsquery_terms = re.findall(r"\w+", question.lower())
            tsquery_terms = [w for w in tsquery_terms if len(w) > 2][:20]
            tsquery = " | ".join(tsquery_terms) if tsquery_terms else "empty"

            cur = conn.execute(
                """
                SELECT id, document_id, sequence, content,
                       1 - (embedding <=> %s::vector) AS vec_score,
                       ts_rank(search_vector, to_tsquery('english', %s)) AS bm25_score,
                       (0.7 * (1 - (embedding <=> %s::vector)) +
                        0.3 * ts_rank(search_vector, to_tsquery('english', %s))) AS score
                FROM age_chunks
                WHERE namespace = %s
                ORDER BY score DESC
                LIMIT %s
                """,
                (q_emb, tsquery, q_emb, tsquery, self._namespace, self._top_k),
            )
            seed_rows = cur.fetchall()
            col_names = [desc.name for desc in cur.description]

            if not seed_rows:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                return RetrievalResponse(
                    retrieved_chunk_ids=[],
                    retrieved_chunk_contents=[],
                    retrieval_ms=elapsed_ms,
                )

            seeds = [dict(zip(col_names, row)) for row in seed_rows]

            # Step 2: Entity lookup — find entities mentioned in seed chunks
            _age_session(conn)

            mentioned_entities: set[str] = set()
            for seed in seeds:
                content_lower = seed["content"].lower()
                # Query all entities and check if their name appears in any seed chunk
                try:
                    cur = conn.execute(
                        f"SELECT * FROM cypher('{self._graph_name}', $$ "
                        f"MATCH (n:Entity) RETURN n.id, n.name "
                        f"$$) AS (eid agtype, name agtype)"
                    )
                    for row in cur.fetchall():
                        ename = _strip_agtype(row[1]).lower()
                        if ename in content_lower:
                            mentioned_entities.add(_strip_agtype(row[0]))
                except Exception:
                    pass

            # Step 3: Cypher expansion — expand from mentioned entities
            expanded_entity_names: set[str] = set()
            for eid in mentioned_entities:
                try:
                    cur = conn.execute(
                        f"SELECT * FROM cypher('{self._graph_name}', $$ "
                        f"MATCH (a:Entity {{id: '{eid}'}})-[*1..{self._hop_budget}]-(b:Entity) "
                        f"RETURN b.name "
                        f"$$) AS (name agtype)"
                    )
                    for row in cur.fetchall():
                        expanded_entity_names.add(_strip_agtype(row[0]).lower())
                except Exception:
                    pass

            # Step 4: If we found expanded entities, pull in more chunks
            # that mention those entities (boost them into results)
            if expanded_entity_names:
                # Build LIKE conditions for entity name matching
                like_clauses = []
                like_params: list = [q_emb, tsquery, q_emb, tsquery, self._namespace]
                for ename in expanded_entity_names:
                    like_clauses.append("lower(content) LIKE %s")
                    like_params.append(f"%{ename}%")
                like_params.append(self._top_k * 2)

                where_clause = " OR ".join(like_clauses)
                cur = conn.execute(
                    f"""
                    SELECT id, document_id, sequence, content,
                           1 - (embedding <=> %s::vector) AS vec_score,
                           ts_rank(search_vector, to_tsquery('english', %s)) AS bm25_score,
                           (0.7 * (1 - (embedding <=> %s::vector)) +
                            0.3 * ts_rank(search_vector, to_tsquery('english', %s))) AS score
                    FROM age_chunks
                    WHERE namespace = %s AND ({where_clause})
                    ORDER BY score DESC
                    LIMIT %s
                    """,
                    like_params,
                )
                expanded_rows = cur.fetchall()
                col_names_exp = [desc.name for desc in cur.description]
                expanded = [dict(zip(col_names_exp, row)) for row in expanded_rows]

                # Merge: deduplicate by id, prefer higher score
                seen: dict[int, dict] = {}
                for row in seeds + expanded:
                    rid = row["id"]
                    if rid not in seen or row["score"] > seen[rid]["score"]:
                        seen[rid] = row
                merged = sorted(
                    seen.values(), key=lambda r: r["score"], reverse=True
                )[: self._top_k]
            else:
                merged = seeds[: self._top_k]

        elapsed_ms = (time.perf_counter() - t0) * 1000
        return RetrievalResponse(
            retrieved_chunk_ids=[
                f"{r['document_id']}::{r['sequence']}" for r in merged
            ],
            retrieved_chunk_contents=[r["content"] for r in merged],
            retrieval_ms=elapsed_ms,
        )

    async def ingest(self, extraction: ExtractionOutput) -> None:
        loop = asyncio.get_running_loop()
        if not self._bootstrapped:
            await loop.run_in_executor(None, self._sync_bootstrap)
        await loop.run_in_executor(None, self._sync_ingest, extraction)

    async def retrieve(self, question: str) -> RetrievalResponse:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_retrieve, question)

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
            name="age",
            embedding_model=self._embedding_model,
            answer_model=self._answer_model,
            top_k=self._top_k,
            hop_budget=self._hop_budget,
        )

    async def cleanup(self) -> None:
        """Drop the graph and chunks table for a clean slate."""
        loop = asyncio.get_running_loop()

        def _sync_cleanup():
            with psycopg.connect(self._dsn) as conn:
                _age_session(conn)
                try:
                    conn.execute(f"SELECT drop_graph('{self._graph_name}', true)")
                    conn.commit()
                except Exception:
                    conn.rollback()
                conn.execute(
                    "DELETE FROM age_chunks WHERE namespace = %s",
                    (self._namespace,),
                )
                conn.commit()
            self._bootstrapped = False

        await loop.run_in_executor(None, _sync_cleanup)
