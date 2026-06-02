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


def _lede_available() -> bool:
    try:
        import lede  # noqa: F401
        import lede_spacy  # noqa: F401
        import spacy

        spacy.load("en_core_web_sm")
        return True
    except Exception:
        return False


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


@pytest.mark.skipif(
    not _lede_available(),
    reason="lede_spacy + en_core_web_sm required for deterministic in-process extraction",
)
async def test_pending_then_drained_lifecycle():
    """SC-003 + SC-005 + brief E2E: full pending → drained transition.

    1. Ingest a doc with defer_extraction=True.
    2. Query via MCP pgrg_ask. Expect a banner naming the doc.
    3. Drain via backfill.extract_documents (the same primitive
       `pgrg extract` uses; calling it directly skips the subprocess).
    4. Query again. Expect no banner key.
    """
    from pg_raggraph.backfill import claim_pending, extract_documents

    ns = "test_mcp_lifecycle"
    rag = GraphRAG(
        dsn=DSN,
        namespace=ns,
        fact_extractor="lede_spacy",  # deterministic, no LLM endpoint needed
        llm_base_url="",
    )
    await rag.connect()
    try:
        await rag.ingest_records(
            [
                {
                    "text": (
                        "NASA launched Saturn V from Kennedy Space Center. "
                        "Neil Armstrong walked on the Moon."
                    ),
                    "source_id": "/repo/apollo.md",
                }
            ],
            namespace=ns,
            defer_extraction=True,
        )

        server = _server_for(rag)

        # Pre-drain: banner or footer should mention the doc.
        pre = await _call_tool(
            server, "pgrg_ask", question="Who walked on the Moon?", namespace=ns
        )
        pre_combined = (pre.get("banner") or "") + (pre.get("footer") or "")
        assert "/repo/apollo.md" in pre_combined, (
            f"pre-drain: expected /repo/apollo.md in banner/footer; got {pre}"
        )

        # Drain.
        ids = await claim_pending(rag.db, ns, batch_size=8)
        assert len(ids) == 1
        stats = await extract_documents(rag, ids, namespace=ns)
        assert stats.ready == 1
        assert stats.failed == 0

        # Post-drain: no banner/footer keys.
        post = await _call_tool(
            server, "pgrg_ask", question="Who walked on the Moon?", namespace=ns
        )
        assert "banner" not in post, f"post-drain: unexpected banner: {post.get('banner')!r}"
        assert "footer" not in post, f"post-drain: unexpected footer: {post.get('footer')!r}"
    finally:
        await rag.delete(ns)
        await rag.close()
