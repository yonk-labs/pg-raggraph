"""SC-018: load_gold_questions parses the chunkshop gold-scotus.yaml shape verbatim."""

from pathlib import Path

import pytest

from pg_raggraph.ab_gate import GoldQuestion, load_gold_questions

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ab_gate" / "gold-scotus-sample.yaml"


def test_loads_scotus_fixture():
    questions = load_gold_questions(FIXTURE)
    assert isinstance(questions, list)
    assert all(isinstance(q, GoldQuestion) for q in questions)
    assert len(questions) == 3
    ids = [q.id for q in questions]
    assert ids == ["scotus_q1", "scotus_q2", "scotus_q3"]


def test_required_facts_parsed_as_tuples():
    questions = load_gold_questions(FIXTURE)
    q1 = questions[0]
    assert q1.required_facts is not None
    assert len(q1.required_facts) == 1
    triple = q1.required_facts[0]
    assert isinstance(triple, tuple)
    assert triple == ("Bostock v. Clayton County", "interprets", "Title VII")


def test_question_without_required_facts_gets_none():
    questions = load_gold_questions(FIXTURE)
    q3 = questions[2]
    assert q3.required_facts is None


def test_question_without_gold_answer_gets_none(tmp_path: Path):
    yaml_path = tmp_path / "minimal.yaml"
    yaml_path.write_text("questions:\n  - id: m1\n    question: 'just a question?'\n")
    questions = load_gold_questions(yaml_path)
    assert len(questions) == 1
    assert questions[0].gold_answer is None
    assert questions[0].required_facts is None


def test_missing_file_raises_filenotfounderror():
    with pytest.raises(FileNotFoundError):
        load_gold_questions(Path("/tmp/definitely-not-here.yaml"))


def test_empty_questions_list_returns_empty(tmp_path: Path):
    yaml_path = tmp_path / "empty.yaml"
    yaml_path.write_text("questions: []\n")
    assert load_gold_questions(yaml_path) == []
