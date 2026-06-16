"""Issue #84, part 2: caller `top_k` reaches the HTTP and MCP surfaces.

The library fix (test_caller_top_k.py) gave `query()`/`ask()` a `top_k`
override. These tests assert the shipped HTTP endpoints (`/query`, `/ask`)
and MCP tools (`pgrg_query`, `pgrg_ask`) thread it through so an external
caller can bound retrieval breadth without editing profiles.
"""

from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
NS = "test_topk_surfaces"


def _records(n: int) -> list[dict]:
    return [
        {
            "text": f"Payment service incident number {i} on the checkout path.",
            "source_id": f"doc:{i}",
        }
        for i in range(n)
    ]


@pytest.fixture
async def seeded():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)
    await rag.ingest_records(_records(6), namespace=NS)
    try:
        yield rag
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.fixture
async def client(seeded):
    from httpx import ASGITransport, AsyncClient

    from pg_raggraph.server import create_app

    app = create_app(dsn=DSN, namespace=NS)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_http_query_top_k_bounds_breadth(client):
    resp = await client.post(
        "/query",
        data={
            "question": "payment service incident",
            "mode": "naive",
            "namespace": NS,
            "top_k": 3,
        },
    )
    assert resp.status_code == 200
    assert len(resp.json()["chunks"]) == 3


async def test_http_ask_top_k_bounds_breadth(client):
    # /ask caps its response chunk list at 5; top_k=2 is under that cap, so a
    # response of exactly 2 proves retrieval breadth (not the cap) did the work.
    resp = await client.post(
        "/ask",
        data={
            "question": "payment service incident",
            "mode": "naive",
            "namespace": NS,
            "top_k": 2,
        },
    )
    assert resp.status_code == 200
    assert len(resp.json()["chunks"]) == 2


def _tool(server, name):
    return server._tool_manager._tools[name]


async def test_mcp_query_top_k_bounds_breadth(seeded):
    from pg_raggraph.mcp_server import build_server

    server = build_server(seeded)
    resp = await _tool(server, "pgrg_query").fn(
        question="payment service incident", mode="naive", namespace=NS, top_k=3
    )
    assert len(resp["chunks"]) == 3


async def test_mcp_ask_top_k_threads_through(seeded):
    from pg_raggraph.mcp_server import build_server

    server = build_server(seeded)
    resp = await _tool(server, "pgrg_ask").fn(
        question="payment service incident", mode="naive", namespace=NS, top_k=2
    )
    assert "answer" in resp
    assert len(resp.get("sources", [])) <= 2
