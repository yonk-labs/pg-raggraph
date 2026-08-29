"""Regression tests for issue #84.

`query()` / `ask()` sourced retrieval breadth solely from `profile_spec.top_k`
(hardcoded 25 on every rung), so callers had no way to bound how many chunks
came back. These tests assert the explicit `top_k` kwarg now overrides the
profile breadth, and that omitting it preserves the profile default.
"""

from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def _connect(**kwargs) -> GraphRAG:
    rag = GraphRAG(dsn=DSN, **kwargs)
    await rag.connect()
    return rag


def _records(n: int) -> list[dict]:
    # Shared theme so every chunk scores on the query and fills the breadth.
    return [
        {
            "text": f"Payment service incident number {i} on the checkout path.",
            "source_id": f"doc:{i}",
        }
        for i in range(n)
    ]


async def test_query_top_k_kwarg_bounds_retrieval_breadth():
    ns = "test_topk_query"
    rag = await _connect(namespace=ns)
    try:
        await rag.delete(ns)
        await rag.ingest_records(_records(6), namespace=ns)

        # No kwarg: profile breadth (default rung caps at available 6 chunks).
        wide = await rag.query("payment service incident", mode="naive", namespace=ns)
        assert len(wide.chunks) > 3, "expected profile-default breadth without top_k"

        # Explicit kwarg bounds breadth.
        narrow = await rag.query("payment service incident", mode="naive", namespace=ns, top_k=3)
        assert len(narrow.chunks) == 3
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_ask_top_k_kwarg_threads_through_to_retrieval():
    ns = "test_topk_ask"
    rag = await _connect(namespace=ns)
    try:
        await rag.delete(ns)
        await rag.ingest_records(_records(6), namespace=ns)

        res = await rag.ask("payment service incident", mode="naive", namespace=ns, top_k=2)
        assert len(res.chunks) == 2
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_query_invalid_top_k_raises_value_error():
    ns = "test_topk_invalid"
    rag = await _connect(namespace=ns)
    try:
        with pytest.raises(ValueError):
            await rag.query("x", mode="naive", namespace=ns, top_k=0)
    finally:
        await rag.close()
