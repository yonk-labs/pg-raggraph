"""Unit tests for the ingest-completion signal (issue #92).

No database: `_graph_status_summary` is stubbed and `_db` is replaced with
a tenant-only stand-in, so these exercise the readiness derivation and the
wait/timeout loop, not the SQL.
"""

from contextlib import contextmanager

import pytest

from pg_raggraph import GraphRAG, _is_graph_ready


class _TenantOnlyDB:
    """Stand-in for Database: the readiness paths only use tenant()."""

    @contextmanager
    def tenant(self, namespace):
        yield


def _make_rag(summaries: list[dict]) -> GraphRAG:
    """GraphRAG whose _graph_status_summary pops from `summaries`.

    The last element is sticky so the poll loop can keep reading it.
    """
    rag = GraphRAG(dsn="postgresql://unused:unused@localhost:1/unused")
    rag._db = _TenantOnlyDB()

    async def _fake_summary(namespace: str) -> dict[str, int]:
        return summaries.pop(0) if len(summaries) > 1 else summaries[0]

    rag._graph_status_summary = _fake_summary
    return rag


def test_is_graph_ready_derivation():
    assert _is_graph_ready({"pending": 0, "processing": 0, "ready": 5, "failed": 0})
    # 'failed' is terminal — it must not block readiness.
    assert _is_graph_ready({"pending": 0, "processing": 0, "ready": 3, "failed": 2})
    # 'degraded' (issue #93) is an overlay on 'ready' — degraded docs ARE
    # ready and must not block readiness either.
    assert _is_graph_ready({"pending": 0, "processing": 0, "ready": 3, "failed": 0, "degraded": 3})
    # Empty namespace is trivially ready.
    assert _is_graph_ready({"pending": 0, "processing": 0, "ready": 0, "failed": 0})
    assert not _is_graph_ready({"pending": 1, "processing": 0, "ready": 0, "failed": 0})
    assert not _is_graph_ready({"pending": 0, "processing": 1, "ready": 4, "failed": 0})


async def test_graph_ready_bool():
    rag = _make_rag([{"pending": 2, "processing": 0, "ready": 0, "failed": 0}])
    assert await rag.graph_ready("ns1") is False

    rag = _make_rag([{"pending": 0, "processing": 0, "ready": 2, "failed": 1}])
    assert await rag.graph_ready("ns1") is True


async def test_wait_for_graph_ready_polls_until_drained():
    rag = _make_rag(
        [
            {"pending": 2, "processing": 0, "ready": 0, "failed": 0},
            {"pending": 0, "processing": 1, "ready": 1, "failed": 0},
            {"pending": 0, "processing": 0, "ready": 2, "failed": 0},
        ]
    )
    summary = await rag.wait_for_graph_ready("ns1", timeout=5.0, poll_interval=0.01)
    assert summary == {"pending": 0, "processing": 0, "ready": 2, "failed": 0}


async def test_wait_for_graph_ready_timeout_carries_summary():
    stuck = {"pending": 3, "processing": 1, "ready": 0, "failed": 0}
    rag = _make_rag([stuck])
    with pytest.raises(TimeoutError) as exc_info:
        await rag.wait_for_graph_ready("ns1", timeout=0.05, poll_interval=0.01)
    # The current summary must be visible to the caller.
    assert str(stuck["pending"]) in str(exc_info.value)
    assert "pending" in str(exc_info.value)
    assert "ns1" in str(exc_info.value)


async def test_wait_for_graph_ready_validates_namespace():
    rag = _make_rag([{"pending": 0, "processing": 0, "ready": 0, "failed": 0}])
    with pytest.raises(ValueError):
        await rag.wait_for_graph_ready("bad namespace!", timeout=0.1)
    with pytest.raises(ValueError):
        await rag.graph_ready("bad namespace!")
