"""Smoke + unit tests for external_corpora loaders.

Live download tests are gated behind ``BAKEOFF_EXTERNAL_LIVE=1`` so the default
pytest run stays offline. Unit tests on the subset-selection + schema
normalization run without any network.
"""
from __future__ import annotations

import os

import pytest

from age_bakeoff.extraction import external_corpora as ec


def test_stratified_subset_balances_classes():
    items = [{"q": f"q{i}", "cls": c} for c in ("A", "B", "C") for i in range(10)]
    picked = ec._stratified_subset(items, class_key="cls", n=6, seed=42)
    assert len(picked) == 6
    counts = {"A": 0, "B": 0, "C": 0}
    for p in picked:
        counts[p["cls"]] += 1
    # 6 / 3 classes = 2 each
    assert counts == {"A": 2, "B": 2, "C": 2}


def test_stratified_subset_seed_stable():
    items = [{"q": f"q{i}", "cls": c} for c in ("A", "B") for i in range(20)]
    a = ec._stratified_subset(items, class_key="cls", n=8, seed=42)
    b = ec._stratified_subset(items, class_key="cls", n=8, seed=42)
    assert [p["q"] for p in a] == [p["q"] for p in b]


def test_stratified_subset_returns_all_when_n_exceeds():
    items = [{"q": "q1", "cls": "A"}, {"q": "q2", "cls": "B"}]
    picked = ec._stratified_subset(items, class_key="cls", n=10, seed=42)
    assert len(picked) == 2


def test_stratified_subset_handles_missing_class_key():
    items = [{"q": "q1"}, {"q": "q2", "cls": "B"}]
    picked = ec._stratified_subset(items, class_key="cls", n=2, seed=42)
    assert len(picked) == 2


def test_corpus_loaders_registry_is_complete():
    expected = {
        "graphrag-bench-medical",
        "graphrag-bench-novel",
        "ms-hotpotqa",
        "ms-kevin-scott",
        "ms-msft-multi",
        "ms-msft-single",
    }
    assert set(ec.CORPUS_LOADERS) == expected


def test_load_corpus_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown corpus"):
        ec.load_corpus("not-a-corpus")


# ---------------------------------------------------------------------------
# Live download tests — opt-in
# ---------------------------------------------------------------------------

LIVE = os.environ.get("BAKEOFF_EXTERNAL_LIVE") == "1"


@pytest.mark.skipif(not LIVE, reason="Set BAKEOFF_EXTERNAL_LIVE=1 to run live")
def test_load_ms_kevin_scott_live_smoke():
    docs, qs = ec.load_ms_kevin_scott()
    assert len(docs) > 0
    assert len(qs) > 0
    for d in docs:
        assert "id" in d and "content" in d and "title" in d and "metadata" in d
    for q in qs:
        assert "id" in q and "question" in q and "gold_answer" in q


@pytest.mark.skipif(not LIVE, reason="Set BAKEOFF_EXTERNAL_LIVE=1 to run live")
def test_load_graphrag_bench_medical_live_smoke():
    docs, qs = ec.load_graphrag_bench("medical", n_questions=10, seed=42)
    assert len(docs) > 0
    assert len(qs) == 10
    classes = {q.get("question_class") for q in qs}
    # 10 questions should span >= 2 classes after stratification
    assert len(classes) >= 2
