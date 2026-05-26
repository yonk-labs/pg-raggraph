"""Integration tests for the online embedding-model migration.

The migration is database-wide and destructive (it renames the live embedding
columns and retypes the shared embedding_cache), so it cannot run against the
shared integration database that other suites isolate by namespace. Each test
here gets its own throwaway database via the ``fresh_db`` fixture.
"""

import os
import uuid

import psycopg
import pytest

from pg_raggraph import GraphRAG
from pg_raggraph import embedding_migration as em

DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
pytestmark = pytest.mark.integration


def _swap_db(dsn: str, dbname: str) -> str:
    """Return ``dsn`` with its database name replaced (assumes no query string)."""
    return f"{dsn.rpartition('/')[0]}/{dbname}"


@pytest.fixture
def fresh_db():
    """Create a throwaway database with pgvector + pg_trgm; drop it after.

    Yields a DSN pointing at the new database. The embedding migration mutates
    table-wide schema, so isolation per test is required.
    """
    name = f"emig_{uuid.uuid4().hex[:12]}"
    admin = _swap_db(DSN, "postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    new_dsn = _swap_db(DSN, name)
    with psycopg.connect(new_dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    try:
        yield new_dsn
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


async def _fresh_rag(dsn: str, dim: int, embedder):
    rag = GraphRAG(dsn=dsn, embedding_dim=dim, namespace="emig_test")
    rag._embedder = embedder
    await rag.connect()
    return rag


class StubEmbedder:
    def __init__(self, dim):
        self.dim = dim

    async def embed(self, texts):
        return [[float((i % 7) + 1)] * self.dim for i, _ in enumerate(texts)]


@pytest.mark.asyncio
async def test_migration_010_creates_state_table(fresh_db):
    rag = await _fresh_rag(fresh_db, 4, StubEmbedder(4))
    try:
        row = await rag._db.fetch_one("SELECT to_regclass('embedding_migration') AS t")
        assert row["t"] == "embedding_migration"
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_column_dim_reads_live_dimension(fresh_db):
    rag = await _fresh_rag(fresh_db, 4, StubEmbedder(4))
    try:
        assert await em.column_dim(rag._db, "chunks", "embedding") == 4
        assert await em.column_dim(rag._db, "chunks", "embedding_tmp") is None
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_prepare_adds_tmp_columns_and_state(fresh_db):
    rag = await _fresh_rag(fresh_db, 4, StubEmbedder(4))
    try:
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        assert await em.column_dim(rag._db, "chunks", "embedding_tmp") == 6
        assert await em.column_dim(rag._db, "entities", "embedding_tmp") == 6
        state = await em.get_state(rag._db)
        assert state["target_dim"] == 6
        assert state["target_model"] == "stub-6"
        assert state["phase"] == "prepared"
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_status_reports_phase_and_remaining(fresh_db):
    rag = await _fresh_rag(fresh_db, 4, StubEmbedder(4))
    try:
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        st = await em.status(rag._db)
        assert st["active"] is True
        assert st["phase"] == "prepared"
        assert st["remaining"] == {"chunks": 0, "entities": 0}
        assert st["indexed"] == {"chunks": False, "entities": False}
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_status_inactive_when_no_migration(fresh_db):
    rag = await _fresh_rag(fresh_db, 4, StubEmbedder(4))
    try:
        st = await em.status(rag._db)
        assert st["active"] is False
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_backfill_fills_tmp_with_target_dim(fresh_db):
    rag = await _fresh_rag(fresh_db, 4, StubEmbedder(4))
    try:
        await rag.ingest_records(
            [{"text": "Ada Lovelace wrote the first algorithm.", "source_id": "d1"}]
        )
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        n = await em.backfill(rag._db, StubEmbedder(6), batch_size=2)
        assert n > 0
        assert await em._remaining_null(rag._db, "chunks") == 0
        row = await rag._db.fetch_one(
            "SELECT vector_dims(embedding_tmp) AS d FROM chunks "
            "WHERE embedding_tmp IS NOT NULL LIMIT 1"
        )
        assert row["d"] == 6
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_build_index_creates_tmp_hnsw(fresh_db):
    rag = await _fresh_rag(fresh_db, 4, StubEmbedder(4))
    try:
        await rag.ingest_records(
            [{"text": "Ada Lovelace wrote the first algorithm.", "source_id": "d1"}]
        )
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        await em.backfill(rag._db, StubEmbedder(6), batch_size=8)
        await em.build_index(rag._db)
        assert await em._index_exists(rag._db, "idx_chunk_embed_tmp")
        assert await em._index_exists(rag._db, "idx_entity_embed_tmp")
        st = await em.status(rag._db)
        assert st["phase"] == "indexed"
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_cutover_swaps_columns_and_retypes_cache(fresh_db):
    rag = await _fresh_rag(fresh_db, 4, StubEmbedder(4))
    try:
        await rag.ingest_records(
            [{"text": "Ada Lovelace wrote the first algorithm.", "source_id": "d1"}]
        )
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        await em.backfill(rag._db, StubEmbedder(6), batch_size=8)
        await em.build_index(rag._db)
        await em.cutover(rag._db)
        assert await em.column_dim(rag._db, "chunks", "embedding") == 6
        assert await em.column_dim(rag._db, "chunks", "embedding_old") == 4
        assert await em.column_dim(rag._db, "embedding_cache", "embedding") == 6
        assert await em._index_exists(rag._db, "idx_chunk_embed")
        st = await em.status(rag._db)
        assert st["phase"] == "cutover"
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_cutover_refused_before_index_and_backfill(fresh_db):
    rag = await _fresh_rag(fresh_db, 4, StubEmbedder(4))
    try:
        await rag.ingest_records(
            [{"text": "Ada Lovelace wrote the first algorithm.", "source_id": "d1"}]
        )
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        with pytest.raises(RuntimeError, match="not ready"):
            await em.cutover(rag._db)
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_finalize_drops_old_and_clears_state(fresh_db):
    rag = await _fresh_rag(fresh_db, 4, StubEmbedder(4))
    try:
        await rag.ingest_records(
            [{"text": "Ada Lovelace wrote the first algorithm.", "source_id": "d1"}]
        )
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        await em.backfill(rag._db, StubEmbedder(6), batch_size=8)
        await em.build_index(rag._db)
        await em.cutover(rag._db)
        await em.finalize(rag._db)
        assert await em.column_dim(rag._db, "chunks", "embedding_old") is None
        assert await em.get_state(rag._db) is None
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_finalize_refused_before_cutover(fresh_db):
    rag = await _fresh_rag(fresh_db, 4, StubEmbedder(4))
    try:
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        with pytest.raises(RuntimeError, match="cutover"):
            await em.finalize(rag._db)
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_connect_raises_on_dim_mismatch(fresh_db):
    # bootstrap at dim 4
    rag = await _fresh_rag(fresh_db, 4, StubEmbedder(4))
    await rag.close()
    # reconnect declaring a different dim -> guard must raise
    bad = GraphRAG(dsn=fresh_db, embedding_dim=5, namespace="emig_test")
    bad._embedder = StubEmbedder(5)
    with pytest.raises(ValueError, match="embedding_dim"):
        await bad.connect()


@pytest.mark.asyncio
async def test_backfill_from_chunkshop_sink_matches_by_metadata(fresh_db):
    rag = await _fresh_rag(fresh_db, 4, StubEmbedder(4))
    try:
        await rag.ingest_records(
            [
                {
                    "text": "alpha",
                    "source_id": "chunkshop:docX",
                    "metadata": {"source": "chunkshop", "chunkshop_doc_id": "docX"},
                    "pre_chunked": [
                        {
                            "content": "alpha",
                            "embedding": [1.0, 1.0, 1.0, 1.0],
                            "metadata": {"chunkshop_doc_id": "docX", "chunkshop_seq_num": 0},
                        }
                    ],
                }
            ]
        )
        await em.prepare(
            rag._db,
            target_model="stub-6",
            target_dim=6,
            backfill_source="chunkshop_sink",
        )
        sink_rows = [
            {
                "chunkshop_doc_id": "docX",
                "chunkshop_seq_num": 0,
                "embedding": [9.0] * 6,
            }
        ]
        n = await em.backfill_from_sink(rag._db, sink_rows, entity_embedder=StubEmbedder(6))
        assert n >= 1
        assert await em._remaining_null(rag._db, "chunks") == 0
        row = await rag._db.fetch_one(
            "SELECT vector_dims(embedding_tmp) AS d FROM chunks "
            "WHERE embedding_tmp IS NOT NULL LIMIT 1"
        )
        assert row["d"] == 6
    finally:
        await rag.close()
