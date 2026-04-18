import json

import pytest
from age_bakeoff.cost import CostBudgetExceeded, CostTracker, load_tally_reports


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


def test_tally_report_summarises_by_model():
    t = CostTracker(budget_usd=1.0)
    t.record("gpt-5-mini", 1000, 500)
    t.record("gpt-5-mini", 500, 250)
    t.record("gpt-4o-mini", 1000, 500)

    report = t.tally_report()
    assert report["total_usd"] == pytest.approx(t.total_usd, rel=1e-6)
    assert "gpt-5-mini" in report["by_model"]
    assert report["by_model"]["gpt-5-mini"]["calls"] == 2
    assert report["by_model"]["gpt-4o-mini"]["calls"] == 1


def test_load_tally_reports_aggregates_per_command_files(tmp_path):
    # Simulate a `run` command writing its cost file...
    run_report = {
        "total_usd": 1.25,
        "budget_usd": 50.0,
        "by_model": {
            "gpt-5-mini": {
                "calls": 2,
                "usd": 1.25,
                "prompt_tokens": 5000,
                "completion_tokens": 1000,
            }
        },
    }
    (tmp_path / "cost-run.json").write_text(json.dumps(run_report))

    # ...followed by a `judge` command writing its own.
    judge_report = {
        "total_usd": 0.75,
        "budget_usd": 50.0,
        "by_model": {
            "gpt-5-mini": {
                "calls": 3,
                "usd": 0.50,
                "prompt_tokens": 2000,
                "completion_tokens": 500,
            },
            "gpt-4o-mini": {
                "calls": 1,
                "usd": 0.25,
                "prompt_tokens": 1500,
                "completion_tokens": 250,
            },
        },
    }
    (tmp_path / "cost-judge.json").write_text(json.dumps(judge_report))

    combined = load_tally_reports(tmp_path)

    assert combined["total_usd"] == pytest.approx(2.00, rel=1e-6)
    assert combined["budget_usd"] == 50.0

    # Per-command breakdown preserved.
    assert set(combined["by_command"].keys()) == {"run", "judge"}
    assert combined["by_command"]["run"]["total_usd"] == pytest.approx(1.25)
    assert combined["by_command"]["judge"]["total_usd"] == pytest.approx(0.75)

    # Per-model totals aggregate across files.
    assert combined["by_model"]["gpt-5-mini"]["calls"] == 5
    assert combined["by_model"]["gpt-5-mini"]["usd"] == pytest.approx(1.75)
    assert combined["by_model"]["gpt-5-mini"]["prompt_tokens"] == 7000
    assert combined["by_model"]["gpt-5-mini"]["completion_tokens"] == 1500
    assert combined["by_model"]["gpt-4o-mini"]["calls"] == 1
    assert combined["by_model"]["gpt-4o-mini"]["usd"] == pytest.approx(0.25)


def test_load_tally_reports_empty_dir(tmp_path):
    combined = load_tally_reports(tmp_path)
    assert combined["total_usd"] == 0.0
    assert combined["budget_usd"] is None
    assert combined["by_command"] == {}
    assert combined["by_model"] == {}
