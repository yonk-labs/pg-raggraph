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

DSN = os.environ.get("PGRG_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="requires PGRG_TEST_DSN")


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
