"""Tests for report aggregation and generation."""
from __future__ import annotations

import pytest

from age_bakeoff.models import QuestionClass, RunResult
from age_bakeoff.report.aggregate import (
    group_by_engine,
    group_by_engine_and_class,
    latency_percentiles,
)
from age_bakeoff.report.generator import generate_report
from age_bakeoff.scorers.llm_judge import JudgeVerdict


def _result(
    engine="pgrg",
    corpus="test",
    question_id="q1",
    retrieval_ms=10.0,
    answer_ms=100.0,
):
    return RunResult(
        engine=engine,
        corpus=corpus,
        question_id=question_id,
        run_number=1,
        cold=True,
        retrieval_ms=retrieval_ms,
        answer_ms=answer_ms,
        retrieved_chunk_ids=["c1"],
        generated_answer="answer",
    )


def test_latency_percentiles():
    results = [_result(retrieval_ms=i * 10.0) for i in range(1, 11)]
    p = latency_percentiles(results)
    assert p["p50"] == pytest.approx(55.0, abs=1.0)
    assert p["mean"] == pytest.approx(55.0)
    assert p["n"] == 10


def test_latency_percentiles_empty():
    p = latency_percentiles([])
    assert p["n"] == 0
    assert p["p50"] == 0.0


def test_latency_skips_negative():
    results = [_result(retrieval_ms=-1.0), _result(retrieval_ms=50.0)]
    p = latency_percentiles(results)
    assert p["n"] == 1
    assert p["mean"] == 50.0


def test_group_by_engine():
    results = [
        _result(engine="pgrg"),
        _result(engine="age"),
        _result(engine="pgrg"),
    ]
    grouped = group_by_engine(results)
    assert len(grouped["pgrg"]) == 2
    assert len(grouped["age"]) == 1


def test_group_by_engine_and_class():
    results = [
        _result(engine="pgrg", question_id="q1"),
        _result(engine="pgrg", question_id="q2"),
        _result(engine="age", question_id="q1"),
    ]
    qc = {
        "q1": QuestionClass.factual,
        "q2": QuestionClass.multi_hop_bridging,
    }
    grouped = group_by_engine_and_class(results, qc)
    assert QuestionClass.factual in grouped["pgrg"]
    assert QuestionClass.multi_hop_bridging in grouped["pgrg"]
    assert len(grouped["pgrg"][QuestionClass.factual]) == 1


def test_generate_report_basic():
    results = [
        _result(engine="pgrg", corpus="acme", retrieval_ms=10.0),
        _result(engine="age", corpus="acme", retrieval_ms=15.0),
    ]
    report = generate_report({"acme": results})
    assert "# AGE vs pg-raggraph Bake-off Report" in report
    assert "acme" in report
    assert "pgrg" in report
    assert "age" in report
    assert "Retrieval Latency" in report


def test_generate_report_with_fact_recall():
    results = [
        _result(engine="pgrg", corpus="acme"),
        _result(engine="age", corpus="acme"),
    ]
    fact_recall = {
        "acme": {
            "pgrg": {"q1": 1.0},
            "age": {"q1": 0.5},
        }
    }
    report = generate_report({"acme": results}, fact_recall_by_corpus=fact_recall)
    assert "Fact Recall" in report
    assert "1.000" in report
    assert "0.500" in report


def test_generate_report_with_judge():
    results = [_result(engine="pgrg", corpus="acme")]
    judge = {
        "acme": {
            "pgrg": {"q1": JudgeVerdict.fully_correct},
        }
    }
    report = generate_report(
        {"acme": results}, judge_by_corpus=judge
    )
    assert "LLM Judge" in report
    assert "Fully Correct" in report


def test_generate_report_writes_file(tmp_path):
    results = [_result(engine="pgrg", corpus="acme")]
    out = tmp_path / "REPORT.md"
    report = generate_report({"acme": results}, output_path=out)
    assert out.exists()
    assert out.read_text() == report


def test_where_age_wins_section():
    results = [
        _result(engine="pgrg", corpus="acme", retrieval_ms=50.0),
        _result(engine="age", corpus="acme", retrieval_ms=10.0),
    ]
    report = generate_report({"acme": results})
    assert "Where AGE Wins" in report
    assert "faster" in report
