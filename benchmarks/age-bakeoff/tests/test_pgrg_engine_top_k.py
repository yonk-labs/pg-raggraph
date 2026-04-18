"""Unit-level tests for PgrgEngine's top_k wiring.

The sibling ``test_pgrg_engine.py`` is integration-only (module-level
``skipif`` gate on Docker PG being reachable), which makes it awkward to
host tests that don't need a live DB. This module carries the unit-level
behaviors so they run in any environment.
"""
from __future__ import annotations

import pytest

from age_bakeoff.engines.base import RetrievalResponse
from age_bakeoff.engines.pgrg import PgrgEngine


class _FakeQueryResult:
    """Minimal stand-in for pg_raggraph.models.QueryResult."""

    def __init__(self) -> None:
        self.chunks: list = []


@pytest.mark.asyncio
async def test_retrieve_drives_top_k_into_graphrag_config(monkeypatch):
    """``PgrgEngine.retrieve()`` must set ``self._rag.config.top_k`` to
    ``self._top_k`` BEFORE calling ``_rag.query``. Without this, GraphRAG
    retrieves under its own default (10) and our ``_top_k`` merely
    post-slices, so any sweep above k=10 is degenerate on pgrg.
    """
    engine = PgrgEngine(
        dsn="postgresql://invalid:invalid@localhost:0/test",
        namespace="unit_test",
        top_k=7,
    )

    # Short-circuit the connection path -- we only exercise retrieve() logic.
    async def _noop_connect(self):  # type: ignore[no-redef]
        self._connected = True

    monkeypatch.setattr(PgrgEngine, "_ensure_connected", _noop_connect)

    captured: dict[str, int] = {}

    async def _capture_query(question, mode, namespace):
        # Snapshot the top_k that GraphRAG would see at query time.
        captured["top_k_at_query"] = engine._rag.config.top_k
        return _FakeQueryResult()

    monkeypatch.setattr(engine._rag, "query", _capture_query)

    # First call with the constructor-provided top_k=7.
    await engine.retrieve("q1")
    assert captured["top_k_at_query"] == 7

    # Simulate a sweep bumping _top_k; retrieve() must propagate it.
    engine._top_k = 42
    await engine.retrieve("q2")
    assert captured["top_k_at_query"] == 42

    # And back down to a lower value -- also must propagate (not merely
    # post-slice), so the retriever actually narrows its candidate set.
    engine._top_k = 3
    await engine.retrieve("q3")
    assert captured["top_k_at_query"] == 3
