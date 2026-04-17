import pytest
from age_bakeoff.cost import CostTracker, CostBudgetExceeded


def test_accumulates():
    t = CostTracker(budget_usd=1.0)
    t.record("gpt-5-mini", prompt_tokens=1000, completion_tokens=500)
    assert t.total_usd > 0
    assert t.total_usd < 1.0


def test_raises_when_over():
    t = CostTracker(budget_usd=0.0001)
    with pytest.raises(CostBudgetExceeded):
        t.record("gpt-5-mini", prompt_tokens=10000, completion_tokens=5000)


def test_unknown_model_fallback():
    t = CostTracker(budget_usd=100.0)
    t.record("unknown-model", prompt_tokens=1000, completion_tokens=500)
    assert t.total_usd > 0


def test_tracks_calls():
    t = CostTracker(budget_usd=100.0)
    t.record("gpt-5-mini", prompt_tokens=1000, completion_tokens=500)
    t.record("gpt-4o-mini", prompt_tokens=2000, completion_tokens=300)
    assert len(t.calls) == 2
    assert t.calls[0]["model"] == "gpt-5-mini"
    assert t.calls[1]["model"] == "gpt-4o-mini"
