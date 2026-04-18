"""Tests for the top_k_sweep diagnostic (SC-001 input).

top_k_sweep is an engine-only diagnostic: it re-runs the same questions at
multiple top_k values and captures what the retriever returned so a downstream
fact-recall pass can quantify whether raising k recovers missing facts.
"""
from __future__ import annotations

import pytest
from age_bakeoff.engines.base import RetrievalResponse


class _FakeEngine:
    """Records every retrieve() call + the _top_k seen at that moment."""

    def __init__(self) -> None:
        self._top_k = 10
        self.calls: list[tuple[str, int]] = []

    async def retrieve(self, question: str) -> RetrievalResponse:
        self.calls.append((question, self._top_k))
        return RetrievalResponse(
            retrieved_chunk_ids=[f"c{self._top_k}"],
            retrieved_chunk_contents=[f"content@k={self._top_k}"],
            retrieval_ms=5.0,
        )


@pytest.mark.asyncio
async def test_top_k_sweep_runs_each_k():
    from age_bakeoff.diagnostics import top_k_sweep

    class FakeEngine:
        def __init__(self):
            self._top_k = 10

        async def retrieve(self, q):
            return RetrievalResponse(
                retrieved_chunk_ids=["a"],
                retrieved_chunk_contents=["x"],
                retrieval_ms=5.0,
            )

    results = await top_k_sweep(
        engine=FakeEngine(), questions=["q1"], k_values=[5, 10, 20]
    )
    assert set(results.keys()) == {5, 10, 20}


@pytest.mark.asyncio
async def test_top_k_sweep_sets_engine_top_k_before_each_retrieve():
    """Verify the sweep drives _top_k to each value before calling retrieve."""
    from age_bakeoff.diagnostics import top_k_sweep

    engine = _FakeEngine()
    await top_k_sweep(
        engine=engine, questions=["q1", "q2"], k_values=[5, 50]
    )
    # Expect k=5 applied during both q1 and q2 calls, then k=50 for both.
    assert engine.calls == [("q1", 5), ("q2", 5), ("q1", 50), ("q2", 50)]


@pytest.mark.asyncio
async def test_top_k_sweep_captures_retrieval_payload():
    from age_bakeoff.diagnostics import top_k_sweep

    engine = _FakeEngine()
    out = await top_k_sweep(
        engine=engine, questions=["q1"], k_values=[5, 20]
    )
    assert out[5][0]["question"] == "q1"
    assert out[5][0]["chunk_ids"] == ["c5"]
    assert out[5][0]["contents"] == ["content@k=5"]
    assert out[5][0]["retrieval_ms"] == 5.0
    assert out[20][0]["chunk_ids"] == ["c20"]


@pytest.mark.asyncio
async def test_top_k_sweep_tolerates_engine_without_top_k_attr():
    """An engine lacking _top_k should still run -- the sweep just can't
    drive its retriever. This is a safety net, not a supported pattern."""
    from age_bakeoff.diagnostics import top_k_sweep

    class NoKEngine:
        async def retrieve(self, q):
            return RetrievalResponse(
                retrieved_chunk_ids=["x"],
                retrieved_chunk_contents=["y"],
                retrieval_ms=1.0,
            )

    out = await top_k_sweep(
        engine=NoKEngine(), questions=["q"], k_values=[5, 10]
    )
    assert set(out.keys()) == {5, 10}


def test_parse_k_values_rejects_non_positive():
    """k <= 0 is meaningless for retrieval; must fail loud."""
    import click

    from age_bakeoff.cli import _parse_k_values

    with pytest.raises(click.BadParameter):
        _parse_k_values("0")
    with pytest.raises(click.BadParameter):
        _parse_k_values("-5")
    with pytest.raises(click.BadParameter):
        # Mixed valid+invalid must still reject.
        _parse_k_values("5,0,10")


def test_parse_k_values_dedups_preserving_order():
    """Duplicates waste work and bloat the output; dedupe while preserving
    first-seen order so callers still get an intuitive sweep."""
    from age_bakeoff.cli import _parse_k_values

    assert _parse_k_values("5,10,5,20,10") == [5, 10, 20]
    # Idempotent on already-unique input.
    assert _parse_k_values("5,10,20") == [5, 10, 20]
