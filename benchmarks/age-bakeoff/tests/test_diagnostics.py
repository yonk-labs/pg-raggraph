"""Tests for quality research diagnostics (SC-001 inputs)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_sample_gold_alternative_phrasings_uses_judge():
    from age_bakeoff.diagnostics import sample_gold_alternative_phrasings

    class FakeClient:
        def __init__(self):
            async def create(**kwargs):
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content='{"alternatives": ["alt 1", "alt 2"]}'
                            )
                        )
                    ],
                    usage=SimpleNamespace(
                        prompt_tokens=10, completion_tokens=20
                    ),
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    out = await sample_gold_alternative_phrasings(
        client=FakeClient(),
        question="q",
        gold_answer="a",
        n=2,
        model="gpt-5-mini",
    )
    assert len(out) == 2


@pytest.mark.asyncio
async def test_sample_gold_alternative_phrasings_records_cost():
    from age_bakeoff.cost import CostTracker
    from age_bakeoff.diagnostics import sample_gold_alternative_phrasings

    class FakeClient:
        def __init__(self):
            async def create(**kwargs):
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content='{"alternatives": ["x", "y", "z"]}'
                            )
                        )
                    ],
                    usage=SimpleNamespace(
                        prompt_tokens=100, completion_tokens=200
                    ),
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    tracker = CostTracker(budget_usd=10.0)
    out = await sample_gold_alternative_phrasings(
        client=FakeClient(),
        question="q",
        gold_answer="a",
        n=3,
        model="gpt-5-mini",
        tracker=tracker,
    )
    assert len(out) == 3
    assert tracker.total_usd > 0
    assert len(tracker.calls) == 1
    assert tracker.calls[0]["model"] == "gpt-5-mini"
    assert tracker.calls[0]["prompt_tokens"] == 100
    assert tracker.calls[0]["completion_tokens"] == 200


@pytest.mark.asyncio
async def test_sample_gold_alternative_phrasings_truncates_to_n():
    from age_bakeoff.diagnostics import sample_gold_alternative_phrasings

    class FakeClient:
        def __init__(self):
            async def create(**kwargs):
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content='{"alternatives": ["a", "b", "c", "d", "e"]}'
                            )
                        )
                    ],
                    usage=SimpleNamespace(
                        prompt_tokens=1, completion_tokens=1
                    ),
                )

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    out = await sample_gold_alternative_phrasings(
        client=FakeClient(),
        question="q",
        gold_answer="a",
        n=2,
        model="gpt-5-mini",
    )
    assert out == ["a", "b"]
