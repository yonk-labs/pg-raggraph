import yaml
import pytest
from age_bakeoff.models import QuestionClass
from age_bakeoff.questions.schema import load_question_set


def test_enforces_30(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        yaml.safe_dump(
            {
                "corpus": "acme",
                "questions": [
                    {
                        "id": "q1",
                        "question": "?",
                        "gold_answer": "a",
                        "required_facts": ["a"],
                        "question_class": "semantic",
                    }
                ],
            }
        )
    )
    with pytest.raises(ValueError, match="30"):
        load_question_set(bad)


def test_enforces_bridging_minimum(tmp_path):
    qs = [
        {
            "id": f"q{i}",
            "question": "?",
            "gold_answer": "a",
            "required_facts": ["a"],
            "question_class": "semantic",
        }
        for i in range(30)
    ]
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"corpus": "acme", "questions": qs}))
    with pytest.raises(ValueError, match="multi_hop_bridging"):
        load_question_set(bad)


def test_valid_set_loads(tmp_path):
    qs = [
        {
            "id": f"q{i}",
            "question": "?",
            "gold_answer": "a",
            "required_facts": ["a"],
            "question_class": "multi_hop_bridging" if i < 5 else "semantic",
        }
        for i in range(30)
    ]
    good = tmp_path / "good.yaml"
    good.write_text(yaml.safe_dump({"corpus": "acme", "questions": qs}))
    qset = load_question_set(good)
    assert len(qset.questions) == 30


def test_duplicate_ids_rejected(tmp_path):
    qs = [
        {
            "id": "same-id",
            "question": "?",
            "gold_answer": "a",
            "required_facts": ["a"],
            "question_class": "multi_hop_bridging" if i < 5 else "semantic",
        }
        for i in range(30)
    ]
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"corpus": "acme", "questions": qs}))
    with pytest.raises(ValueError, match="Duplicate"):
        load_question_set(bad)


def test_loose_mode_accepts_any_count(tmp_path):
    qs = [
        {
            "id": f"q{i}",
            "question": "?",
            "gold_answer": "a",
            "required_facts": ["a"],
            "question_class": "semantic",
        }
        for i in range(3)
    ]
    f = tmp_path / "loose.yaml"
    f.write_text(yaml.safe_dump({"corpus": "test", "questions": qs}))
    qset = load_question_set(f, strict=False)
    assert len(qset.questions) == 3
