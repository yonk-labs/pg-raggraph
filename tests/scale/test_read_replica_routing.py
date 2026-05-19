"""Tests for optional read-replica routing."""

import os

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.db import Database
from pg_raggraph.models import QueryResult

pytestmark = pytest.mark.integration

TEST_DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)


class TinyEmbedder:
    @property
    def dimension(self) -> int:
        return 384

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.04] * self.dimension for _ in texts]


def _dsn_with_application_name(dsn: str, app_name: str) -> str:
    sep = "&" if "?" in dsn else "?"
    return f"{dsn}{sep}application_name={app_name}"


async def test_query_uses_read_pool_and_ingest_uses_writer_pool(monkeypatch):
    seen_apps: list[str] = []
    original_prepare = Database._prepare_connection

    async def spy_prepare(self, conn):
        await original_prepare(self, conn)
        cur = await conn.execute("SELECT current_setting('application_name')")
        row = await cur.fetchone()
        seen_apps.append(row[0])

    async def fake_retrieval_query(**kwargs):
        row = await kwargs["db"].fetch_one("SELECT current_setting('application_name') AS app")
        return QueryResult(answer=row["app"], query_mode=kwargs["mode"])

    monkeypatch.setattr(Database, "_prepare_connection", spy_prepare)
    monkeypatch.setattr("pg_raggraph.retrieval.query", fake_retrieval_query)

    rag = GraphRAG(
        _dsn_with_application_name(TEST_DSN, "pgrg_write"),
        read_dsn=_dsn_with_application_name(TEST_DSN, "pgrg_read"),
        namespace="scale_k9",
        skip_extraction=True,
    )
    rag._embedder = TinyEmbedder()
    await rag.connect()
    try:
        seen_apps.clear()
        result = await rag.query("which pool?", mode="naive", namespace="scale_k9")
        assert result.answer == "pgrg_read"
        assert "pgrg_read" in seen_apps

        seen_apps.clear()
        await rag.ingest_records(
            [{"text": "K9 writer routing content.", "source_id": "scale_k9_doc"}],
            namespace="scale_k9",
        )
        assert "pgrg_write" in seen_apps
        assert "pgrg_read" not in seen_apps
    finally:
        await rag.delete("scale_k9")
        await rag.close()
