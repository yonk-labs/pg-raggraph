import os

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph import embedding_migration as em

DSN = os.environ.get("PGRG_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="requires PGRG_TEST_DSN")


async def _fresh_rag(dim, embedder):
    rag = GraphRAG(dsn=DSN, embedding_dim=dim, namespace="emig_test")
    rag._embedder = embedder
    await rag.connect()
    await rag._db.execute("DELETE FROM embedding_migration")
    return rag


class StubEmbedder:
    def __init__(self, dim):
        self.dim = dim

    async def embed(self, texts):
        return [[float((i % 7) + 1)] * self.dim for i, _ in enumerate(texts)]


@pytest.mark.asyncio
async def test_migration_010_creates_state_table():
    rag = await _fresh_rag(4, StubEmbedder(4))
    try:
        row = await rag._db.fetch_one(
            "SELECT to_regclass('embedding_migration') AS t"
        )
        assert row["t"] == "embedding_migration"
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_column_dim_reads_live_dimension():
    # Use a fresh database so the schema is bootstrapped at dim=4.
    # The shared PGRG_TEST_DSN DB may already be at a different dim (e.g. 384)
    # from other tests, so column_dim would return that value instead of 4.
    dim4_dsn = DSN.rsplit("/", 1)[0] + "/pg_raggraph_dim4" if DSN else None
    if not dim4_dsn:
        pytest.skip("requires PGRG_TEST_DSN")
    rag = GraphRAG(dsn=dim4_dsn, embedding_dim=4, namespace="emig_test")
    rag._embedder = StubEmbedder(4)
    await rag.connect()
    try:
        assert await em.column_dim(rag._db, "chunks", "embedding") == 4
        assert await em.column_dim(rag._db, "chunks", "embedding_tmp") is None
    finally:
        await rag.close()
