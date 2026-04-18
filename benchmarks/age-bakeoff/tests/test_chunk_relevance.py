"""Tests for per-chunk LLM-judged relevance scorer (SC-001 input)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_score_chunk_relevance_returns_per_chunk_relevance():
    from age_bakeoff.scorers.chunk_relevance import score_chunk_relevance

    # Structure mirrors the nested-class shape in the plan's test. The plan's
    # verbatim snippet uses `class Choice: message = Msg()` inside another class
    # body, which fails at class-body scope lookup; we build equivalent attrs
    # with SimpleNamespace so the assertion we actually care about still runs.
    class FakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"relevances": [1.0, 0.5, 0.0]}'
                        )
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=100, completion_tokens=20
                ),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    scores = await score_chunk_relevance(
        client=client,
        question="q",
        chunks=["c1", "c2", "c3"],
        model="gpt-5-mini",
    )
    assert scores == [1.0, 0.5, 0.0]


@pytest.mark.asyncio
async def test_score_chunk_relevance_empty_chunks_returns_empty_without_calling():
    from age_bakeoff.scorers.chunk_relevance import score_chunk_relevance

    class ExplodingCompletions:
        async def create(self, **kwargs):
            raise AssertionError("should not call OpenAI for empty chunks")

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=ExplodingCompletions())
    )
    assert await score_chunk_relevance(
        client=client, question="q", chunks=[], model="gpt-5-mini"
    ) == []


@pytest.mark.asyncio
async def test_score_chunk_relevance_pads_short_response():
    from age_bakeoff.scorers.chunk_relevance import score_chunk_relevance

    class FakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"relevances": [1.0]}'
                        )
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=10, completion_tokens=5
                ),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    scores = await score_chunk_relevance(
        client=client,
        question="q",
        chunks=["a", "b", "c"],
        model="gpt-5-mini",
    )
    assert scores == [1.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_score_chunk_relevance_truncates_long_response():
    from age_bakeoff.scorers.chunk_relevance import score_chunk_relevance

    class FakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"relevances": [0.1, 0.2, 0.3, 0.4, 0.5]}'
                        )
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=10, completion_tokens=5
                ),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    scores = await score_chunk_relevance(
        client=client,
        question="q",
        chunks=["a", "b"],
        model="gpt-5-mini",
    )
    assert scores == [0.1, 0.2]


@pytest.mark.asyncio
async def test_score_chunk_relevance_records_cost_when_tracker_supplied():
    from age_bakeoff.cost import CostTracker
    from age_bakeoff.scorers.chunk_relevance import score_chunk_relevance

    class FakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"relevances": [1.0, 0.0]}'
                        )
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=400, completion_tokens=80
                ),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    tracker = CostTracker(budget_usd=10.0)
    scores = await score_chunk_relevance(
        client=client,
        question="q",
        chunks=["x", "y"],
        model="gpt-5-mini",
        tracker=tracker,
    )
    assert scores == [1.0, 0.0]
    assert tracker.total_usd > 0
    assert len(tracker.calls) == 1
    assert tracker.calls[0]["prompt_tokens"] == 400
    assert tracker.calls[0]["completion_tokens"] == 80


def test_diagnose_context_relevance_merges_cost_across_subcommands(tmp_path):
    """Running gold-strictness then context-relevance should accumulate cost in
    cost-diagnose.json rather than overwriting."""
    import json

    from age_bakeoff.cli import _merge_diagnose_cost

    cost_path = tmp_path / "cost-diagnose.json"
    cost_path.write_text(
        json.dumps(
            {
                "total_usd": 0.42,
                "budget_usd": 50.0,
                "by_model": {
                    "gpt-5-mini": {
                        "calls": 7,
                        "usd": 0.42,
                        "prompt_tokens": 1200,
                        "completion_tokens": 500,
                    }
                },
            }
        )
    )

    from age_bakeoff.cost import CostTracker

    tracker = CostTracker(budget_usd=50.0)
    # Seed from prior (simulating what _merge_diagnose_cost does at command start)
    prior_total = _merge_diagnose_cost(cost_path, tracker, phase="load")
    assert prior_total == pytest.approx(0.42)
    assert tracker.total_usd == pytest.approx(0.42)

    # Simulate a new call added during this command
    tracker.record("gpt-5-mini", 1000, 200)
    post_call_total = tracker.total_usd

    # Finalize: merge calls from prior file and save
    _merge_diagnose_cost(cost_path, tracker, phase="save")

    saved = json.loads(cost_path.read_text())
    # Total reflects prior + new call
    assert saved["total_usd"] == pytest.approx(post_call_total)
    # Prior per-model counts are preserved (not duplicated) and the new call is added
    by_model = saved["by_model"]["gpt-5-mini"]
    assert by_model["calls"] == 8  # 7 prior + 1 new
    assert by_model["prompt_tokens"] == 1200 + 1000
    assert by_model["completion_tokens"] == 500 + 200
