"""Tests for content-hash embedding cache."""

import pytest
from psycopg.errors import InsufficientPrivilege

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration


class CountingEmbedder:
    def __init__(self, value: float = 0.01):
        self.calls = 0
        self.texts: list[str] = []
        self.value = value

    @property
    def dimension(self) -> int:
        return 384

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.texts.extend(texts)
        return [[self.value] * self.dimension for _ in texts]


async def test_embedding_cache_avoids_recompute_across_namespaces(scale_rag):
    text = "F7 shared embedding cache marker alpha beta gamma."
    cache_key = GraphRAG._embedding_cache_key(text)
    await scale_rag.db.execute("DELETE FROM embedding_cache WHERE text_sha256 = %s", (cache_key,))

    embedder = CountingEmbedder()
    scale_rag._embedder = embedder

    await scale_rag.ingest_records(
        [{"text": text, "source_id": "scale_f7_a"}],
        namespace="scale_f7_a",
    )
    assert embedder.calls == 1
    assert embedder.texts == [text]

    await scale_rag.ingest_records(
        [{"text": text, "source_id": "scale_f7_b"}],
        namespace="scale_f7_b",
    )
    assert embedder.calls == 1
    assert embedder.texts == [text]

    row = await scale_rag.db.fetch_one(
        "SELECT count(*) AS cnt FROM embedding_cache WHERE text_sha256 = %s",
        (cache_key,),
    )
    assert row["cnt"] == 1


async def test_embedding_cache_is_scoped_by_embedding_fingerprint(scale_rag):
    text = "F7 same text but different model should miss cache."
    cache_key = GraphRAG._embedding_cache_key(text)
    await scale_rag.db.execute("DELETE FROM embedding_cache WHERE text_sha256 = %s", (cache_key,))

    first = CountingEmbedder(value=0.11)
    scale_rag._embedder = first
    scale_rag.config.embedding_model = "model-a"
    await scale_rag.ingest_records(
        [{"text": text, "source_id": "scale_f7_model_a"}],
        namespace="scale_f7_model_a",
    )
    assert first.calls == 1

    second = CountingEmbedder(value=0.22)
    scale_rag._embedder = second
    scale_rag.config.embedding_model = "model-b"
    await scale_rag.ingest_records(
        [{"text": text, "source_id": "scale_f7_model_b"}],
        namespace="scale_f7_model_b",
    )
    assert second.calls == 1

    row = await scale_rag.db.fetch_one(
        "SELECT count(*) AS cnt FROM embedding_cache WHERE text_sha256 = %s",
        (cache_key,),
    )
    assert row["cnt"] == 2


async def test_embedding_cache_table_not_enumerable_by_app_role(scale_rag):
    async with scale_rag.db.pool.connection() as conn:
        await conn.execute("BEGIN")
        await conn.execute("SET LOCAL ROLE pgrg_app")
        await conn.execute("SAVEPOINT denied_table_read")
        with pytest.raises(InsufficientPrivilege):
            await conn.execute("SELECT text_sha256 FROM embedding_cache LIMIT 1")
        await conn.execute("ROLLBACK TO SAVEPOINT denied_table_read")

        cur = await conn.execute(
            "SELECT count(*) FROM pgrg_embedding_cache_get(%s, %s::text[])", ("x", [])
        )
        row = await cur.fetchone()
        assert row[0] == 0
        await conn.rollback()
