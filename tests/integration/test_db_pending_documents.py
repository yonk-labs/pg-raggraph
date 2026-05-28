"""Integration tests for Database.list_pending_documents (SC-010)."""

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.mcp_helpers import PendingDocument

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def _rag(ns: str) -> GraphRAG:
    rag = GraphRAG(
        dsn=DSN,
        namespace=ns,
        # no LLM; extraction degrades but flag still flips
        llm_base_url="http://localhost:99999/v1",
    )
    await rag.connect()
    return rag


async def test_returns_pending_documents_in_namespace():
    """SC-010: list_pending_documents returns rows with graph_status='pending'."""
    ns = "test_lpd_basic"
    rag = await _rag(ns)
    try:
        await rag.ingest_records(
            [
                {"text": "first deferred doc", "source_id": "lpd:1"},
                {"text": "second deferred doc", "source_id": "lpd:2"},
            ],
            namespace=ns,
            defer_extraction=True,
        )
        pending = await rag.db.list_pending_documents(ns)
        assert isinstance(pending, list)
        assert all(isinstance(p, PendingDocument) for p in pending)
        assert {p.source_path for p in pending} == {"lpd:1", "lpd:2"}
        assert all(p.graph_status in ("pending", "processing") for p in pending)
        assert all(p.namespace == ns for p in pending)
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_empty_namespace_returns_empty_list():
    """No pending docs ⇒ [] (drives SC-005 at the integration layer)."""
    rag = await _rag("test_lpd_empty")
    try:
        pending = await rag.db.list_pending_documents("test_lpd_empty")
        assert pending == []
    finally:
        await rag.close()


async def test_ready_documents_are_excluded():
    """A 'ready' doc must NOT appear in list_pending_documents."""
    ns = "test_lpd_ready"
    rag = GraphRAG(dsn=DSN, namespace=ns)
    await rag.connect()
    try:
        # Synchronous ingest (default): doc lands as 'ready'.
        await rag.ingest_records(
            [{"text": "ready doc", "source_id": "lpd:ready"}],
            namespace=ns,
        )
        pending = await rag.db.list_pending_documents(ns)
        assert pending == []
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_processing_documents_are_included():
    """A doc claimed into 'processing' must appear in the pending list.

    PendingDocument names this 'pending' colloquially but the SQL filter
    covers both 'pending' and 'processing' — both mean "graph not yet
    written" from the agent's perspective.
    """
    from pg_raggraph.backfill import claim_pending

    ns = "test_lpd_processing"
    rag = await _rag(ns)
    try:
        await rag.ingest_records(
            [{"text": "claimed doc", "source_id": "lpd:proc"}],
            namespace=ns,
            defer_extraction=True,
        )
        ids = await claim_pending(rag.db, ns, batch_size=8)
        assert len(ids) == 1
        pending = await rag.db.list_pending_documents(ns)
        assert len(pending) == 1
        assert pending[0].graph_status == "processing"
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_limit_caps_returned_rows():
    """list_pending_documents respects the limit kwarg."""
    ns = "test_lpd_limit"
    rag = await _rag(ns)
    try:
        await rag.ingest_records(
            [{"text": f"doc {i}", "source_id": f"lpd:lim:{i}"} for i in range(8)],
            namespace=ns,
            defer_extraction=True,
        )
        pending = await rag.db.list_pending_documents(ns, limit=3)
        assert len(pending) == 3
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_cross_namespace_isolation():
    """A doc in namespace A must not appear when querying namespace B."""
    rag_a = await _rag("test_lpd_iso_a")
    rag_b = await _rag("test_lpd_iso_b")
    try:
        await rag_a.ingest_records(
            [{"text": "ns-a doc", "source_id": "lpd:iso:a"}],
            namespace="test_lpd_iso_a",
            defer_extraction=True,
        )
        b_pending = await rag_b.db.list_pending_documents("test_lpd_iso_b")
        assert b_pending == [], "namespace B must not see namespace A's pending docs"
    finally:
        await rag_a.delete("test_lpd_iso_a")
        await rag_a.close()
        await rag_b.close()
