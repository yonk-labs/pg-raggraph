import pytest
from age_bakeoff.models import Question, QuestionClass
from age_bakeoff.scorers.fact_recall import (
    aggregate_fact_recall,
    score_fact_recall,
)


def _q(facts):
    return Question(
        id="q1",
        question="?",
        gold_answer="a",
        required_facts=facts,
        question_class=QuestionClass.single_hop,
    )


def test_full_recall():
    assert (
        score_fact_recall(
            _q(["Alice", "Kafka"]),
            ["Alice works on Ingest. Ingest depends on Kafka."],
        )
        == 1.0
    )


def test_partial():
    assert score_fact_recall(
        _q(["Alice", "Kafka", "Redis"]), ["Alice depends on Kafka."]
    ) == pytest.approx(2 / 3)


def test_zero():
    assert score_fact_recall(_q(["Zoe"]), ["Alice was here"]) == 0.0


def test_case_insensitive():
    assert (
        score_fact_recall(_q(["ALICE"]), ["alice was here"]) == 1.0
    )


def test_empty_facts():
    assert score_fact_recall(_q([]), ["anything"]) == 1.0


def test_aggregation():
    mean, lo, hi = aggregate_fact_recall([1.0, 1.0, 0.5])
    assert mean == pytest.approx(0.8333, rel=1e-3)
    assert lo <= mean <= hi


def test_aggregation_empty():
    mean, lo, hi = aggregate_fact_recall([])
    assert mean == 0.0


def test_aggregation_single():
    mean, lo, hi = aggregate_fact_recall([0.75])
    assert mean == 0.75
    assert lo == mean
    assert hi == mean
