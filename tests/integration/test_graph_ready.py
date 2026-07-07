"""Integration tests for the ingest-completion signal (issue #92).

Deferred ingest -> not ready -> drain -> ready, plus the timeout path.
Uses the no-extractor drain (docs flip straight to 'ready' with an empty
graph), same as test_backfill.py.
"""

import asyncio
import os

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.backfill import claim_pending, extract_documents

pytestmark = pytest.mark.integration

DSN = (
    os.environ.get("PGRG_TEST_DSN")
    or os.environ.get("PGRG_DSN")
    or "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
)


async def _make_rag(namespace: str) -> GraphRAG:
    rag = GraphRAG(
        dsn=DSN,
        namespace=namespace,
        # No extractor at all — extract_documents marks deferred docs 'ready'
        # with an empty graph, which is all readiness signaling needs. Must
        # be truly empty: an unreachable URL counts as per-chunk extraction
        # FAILURE (issue #93) and would mark docs 'failed' instead.
        llm_base_url="",
    )
    await rag.connect()
    return rag


async def _drain(rag: GraphRAG, namespace: str) -> None:
    ids = await claim_pending(rag.db, namespace, 16)
    await extract_documents(rag, ids, namespace=namespace)


async def test_deferred_ingest_not_ready_then_drain_then_ready():
    ns = "test_gr_cycle"
    rag = await _make_rag(ns)
    try:
        records = [
            {"text": f"readiness doc {i} body text", "source_id": f"gr:cycle:{i}"}
            for i in range(3)
        ]
        await rag.ingest_records(records, namespace=ns, defer_extraction=True)

        # Mid-backfill: pending docs -> not ready, on every surface.
        assert await rag.graph_ready(ns) is False
        st = await rag.status(ns)
        assert st["graph_ready"] is False
        assert st["graph_status"]["pending"] == 3

        await _drain(rag, ns)

        # Drained: ready everywhere; wait returns immediately with the summary.
        assert await rag.graph_ready(ns) is True
        summary = await rag.wait_for_graph_ready(ns, timeout=5.0, poll_interval=0.1)
        assert summary["pending"] == 0
        assert summary["processing"] == 0
        assert summary["ready"] == 3
        st = await rag.status(ns)
        assert st["graph_ready"] is True
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_wait_for_graph_ready_timeout():
    ns = "test_gr_timeout"
    rag = await _make_rag(ns)
    try:
        await rag.ingest_records(
            [{"text": "doc that never drains", "source_id": "gr:timeout:1"}],
            namespace=ns,
            defer_extraction=True,
        )
        with pytest.raises(TimeoutError) as exc_info:
            await rag.wait_for_graph_ready(ns, timeout=0.3, poll_interval=0.1)
        assert "pending" in str(exc_info.value)
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_wait_for_graph_ready_unblocks_on_concurrent_drain():
    """The poll loop actually loops: a drain landing mid-wait unblocks it."""
    ns = "test_gr_concurrent"
    rag = await _make_rag(ns)
    try:
        await rag.ingest_records(
            [{"text": "doc drained concurrently", "source_id": "gr:conc:1"}],
            namespace=ns,
            defer_extraction=True,
        )

        async def _drain_later():
            await asyncio.sleep(0.3)
            await _drain(rag, ns)

        summary, _ = await asyncio.gather(
            rag.wait_for_graph_ready(ns, timeout=30.0, poll_interval=0.1),
            _drain_later(),
        )
        assert summary["ready"] == 1
        assert summary["pending"] == 0
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_empty_namespace_is_trivially_ready():
    ns = "test_gr_empty"
    rag = await _make_rag(ns)
    try:
        assert await rag.graph_ready(ns) is True
        summary = await rag.wait_for_graph_ready(ns, timeout=1.0)
        # 'degraded' key added by issue #93 (overlay on 'ready').
        assert summary == {
            "pending": 0,
            "processing": 0,
            "ready": 0,
            "failed": 0,
            "degraded": 0,
        }
    finally:
        await rag.close()
