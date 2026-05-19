"""Tests for per-call ingest concurrency bounds."""

import asyncio
from types import SimpleNamespace

import pytest

from pg_raggraph import GraphRAG


class _TinyEmbedder:
    async def embed(self, texts):
        return [[0.0, 0.0, 0.0] for _ in texts]


@pytest.mark.asyncio
async def test_ingest_records_max_concurrent_docs_bounds_per_doc_work():
    rag = GraphRAG(skip_extraction=True, doc_concurrency=8)
    rag._db = SimpleNamespace(tenant=lambda ns: _TenantContext())
    rag._embedder = _TinyEmbedder()
    current = 0
    peak = 0

    async def fake_ingest_one_content(*args, **kwargs):
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.01)
        current -= 1
        return {"entities": 0, "rels": 0}

    rag._ingest_one_content = fake_ingest_one_content

    await rag.ingest_records(
        [{"text": f"doc {i}", "source_id": f"d{i}"} for i in range(10)],
        namespace="scale_backpressure",
        max_concurrent_docs=2,
    )

    assert peak == 2


@pytest.mark.asyncio
async def test_ingest_records_rejects_invalid_max_concurrent_docs():
    rag = GraphRAG(skip_extraction=True)
    rag._db = SimpleNamespace(tenant=lambda ns: _TenantContext())
    rag._embedder = _TinyEmbedder()

    with pytest.raises(ValueError, match="max_concurrent_docs"):
        await rag.ingest_records(
            [{"text": "doc", "source_id": "d"}],
            max_concurrent_docs=0,
        )


class _TenantContext:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return None
