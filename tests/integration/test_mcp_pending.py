"""Integration tests for the MCP staleness banner chokepoint (SC-003, SC-011)."""

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


def _server_for(rag):
    """Build the FastMCP server for a connected rag. Imports lazily so the
    test only requires the mcp extra when actually run."""
    from pg_raggraph.mcp_server import build_server

    return build_server(rag)


async def _call_tool(server, name: str, **kwargs):
    """Invoke a registered MCP tool by name.

    FastMCP stores tools in `server._tool_manager._tools`; that's the
    public access path for in-process testing. If the FastMCP internals
    move, adjust this — but don't go through the stdio/JSON-RPC layer
    just to run a test (too much surface area for an integration check).
    """
    tool = server._tool_manager._tools[name]
    return await tool.fn(**kwargs)


async def test_banner_appears_when_namespace_has_pending_docs():
    """SC-003: pgrg_ask against a namespace with pending docs returns a banner."""
    ns = "test_mcp_banner"
    rag = GraphRAG(dsn=DSN, namespace=ns)
    await rag.connect()
    try:
        await rag.ingest_records(
            [
                {
                    "text": "PostgreSQL is a relational database with strong concurrency.",
                    "source_id": "/repo/pg.md",
                }
            ],
            namespace=ns,
            defer_extraction=True,
        )
        server = _server_for(rag)
        response = await _call_tool(
            server, "pgrg_ask", question="What is PostgreSQL?", namespace=ns
        )

        # Banner OR footer (depending on whether the chunk hit the cited path)
        # must surface the pending doc.
        combined = (response.get("banner") or "") + (response.get("footer") or "")
        assert "⚠️" in (response.get("banner") or "") or "/repo/pg.md" in combined, (
            f"expected banner or footer mentioning /repo/pg.md; got keys={list(response)}"
        )
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_no_banner_when_namespace_has_no_pending_docs():
    """SC-005, SC-011: no pending docs ⇒ neither banner nor footer keys are present."""
    ns = "test_mcp_no_banner"
    rag = GraphRAG(dsn=DSN, namespace=ns)
    await rag.connect()
    try:
        # Synchronous ingest — docs land as 'ready'.
        await rag.ingest_records(
            [{"text": "ready doc", "source_id": "/repo/ready.md"}],
            namespace=ns,
        )
        server = _server_for(rag)
        response = await _call_tool(
            server, "pgrg_ask", question="What does ready say?", namespace=ns
        )
        assert "banner" not in response, f"unexpected banner key: {response.get('banner')!r}"
        assert "footer" not in response, f"unexpected footer key: {response.get('footer')!r}"
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_pgrg_status_also_surfaces_pending_via_footer():
    """SC-004: chokepoint touches every tool, not just retrieval ones."""
    ns = "test_mcp_status_banner"
    rag = GraphRAG(dsn=DSN, namespace=ns)
    await rag.connect()
    try:
        await rag.ingest_records(
            [{"text": "deferred", "source_id": "/repo/x.md"}],
            namespace=ns,
            defer_extraction=True,
        )
        server = _server_for(rag)
        response = await _call_tool(server, "pgrg_status", namespace=ns)
        # pgrg_status returns no chunks/sources, so the pending doc surfaces
        # through the footer, not the banner.
        assert "footer" in response
        assert "/repo/x.md" in response["footer"]
    finally:
        await rag.delete(ns)
        await rag.close()
