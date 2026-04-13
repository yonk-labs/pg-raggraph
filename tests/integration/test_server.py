"""Integration tests for FastAPI server."""

import pytest

pytestmark = pytest.mark.integration

TEST_DB = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


@pytest.fixture
async def client():
    """Create async test client for the API with lifespan."""
    from httpx import ASGITransport, AsyncClient

    from pg_raggraph.server import create_app

    app = create_app(dsn=TEST_DB, namespace="test_api")

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_status(client):
    resp = await client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "documents" in data
    assert "entities" in data


async def test_index_html(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "pg-raggraph" in resp.text


async def test_graph_endpoint(client):
    resp = await client.get("/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data


async def test_query_endpoint(client):
    resp = await client.post(
        "/query",
        data={"question": "test query", "mode": "naive"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "chunks" in data
    assert "query_mode" in data
    assert data["query_mode"] == "naive"


async def test_ask_endpoint(client):
    """ask endpoint returns answer + structured fields."""
    resp = await client.post(
        "/ask",
        data={"question": "What is pg-raggraph?", "mode": "naive"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "confidence" in data
    assert "latency_ms" in data
    assert isinstance(data["chunks"], list)
    assert isinstance(data["entities"], list)
