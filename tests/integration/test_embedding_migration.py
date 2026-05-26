import os
import pytest
from pg_raggraph import GraphRAG

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
