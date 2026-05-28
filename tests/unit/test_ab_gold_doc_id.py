"""gold_doc_id threading + chunkshop-format gold loader (real-verdict wiring).

The shipped #48/#49 gold loader expected a ``{questions: [...]}`` dict with
``gold_answer``; chunkshop's real gold files are a top-level list of
``{query, gold_doc_id}``. Recall@10 / MRR (contract §3.1) are computed against
``gold_doc_id``, so it must flow gold-file → GoldQuestion → ABCaseResult →
compute_verdict. These tests lock that wiring.
"""

from __future__ import annotations

from pathlib import Path

from pg_raggraph.ab_gate.io import ABCaseResult, ABRunnerOutput, GoldQuestion
from pg_raggraph.ab_gate.runner import load_gold_questions


def test_gold_question_carries_optional_gold_doc_id():
    gq = GoldQuestion(id="q1", question="who?", gold_doc_id="doc-42")
    assert gq.gold_doc_id == "doc-42"
    # Backward-compatible default
    assert GoldQuestion(id="q2", question="x").gold_doc_id is None


def test_abcaseresult_carries_gold_doc_id_and_roundtrips():
    case = ABCaseResult(
        question_id="q1",
        question="who?",
        gold_answer=None,
        retrieved=[],
        latency_ms=1.0,
        gold_doc_id="doc-42",
    )
    out = ABRunnerOutput(corpus_id="c", mode="naive_vector", results=[case])
    restored = ABRunnerOutput.from_dict(out.to_dict())
    assert restored.results[0].gold_doc_id == "doc-42"
    # Default stays None when absent from the dict (older payloads)
    legacy = ABRunnerOutput.from_dict(
        {
            "corpus_id": "c",
            "mode": "naive_vector",
            "results": [
                {
                    "question_id": "q1",
                    "question": "who?",
                    "gold_answer": None,
                    "retrieved": [],
                    "latency_ms": 1.0,
                }
            ],
        }
    )
    assert legacy.results[0].gold_doc_id is None


def test_load_gold_questions_parses_chunkshop_list_format(tmp_path: Path):
    """Top-level list of {query, gold_doc_id} → GoldQuestions with auto ids."""
    p = tmp_path / "gold-chunkshop.yaml"
    p.write_text(
        '- { query: "Who wrote the majority opinion in Bostock?", '
        'gold_doc_id: "case-2019_bostock-decision" }\n'
        '- { query: "Apple v. Pepper antitrust standing", '
        'gold_doc_id: "case-2018_apple-overview" }\n'
    )
    gold = load_gold_questions(p)
    assert len(gold) == 2
    assert gold[0].question.startswith("Who wrote")
    assert gold[0].gold_doc_id == "case-2019_bostock-decision"
    assert gold[1].gold_doc_id == "case-2018_apple-overview"
    # Auto-generated stable ids
    assert gold[0].id != gold[1].id
    assert all(g.id for g in gold)


def test_load_gold_questions_still_parses_dict_format(tmp_path: Path):
    """Regression: the original {questions: [...]} dict format still works."""
    p = tmp_path / "gold-dict.yaml"
    p.write_text("questions:\n  - id: q1\n    question: What did X do?\n    gold_answer: Y.\n")
    gold = load_gold_questions(p)
    assert len(gold) == 1
    assert gold[0].id == "q1"
    assert gold[0].gold_answer == "Y."
    assert gold[0].gold_doc_id is None
