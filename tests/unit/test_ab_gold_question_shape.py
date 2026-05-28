"""SC-001: GoldQuestion frozen dataclass with the four locked fields."""

import dataclasses

import pytest


def test_importable_from_ab_gate_top_level():
    from pg_raggraph.ab_gate import GoldQuestion  # noqa: F401


def test_importable_from_ab_gate_io():
    from pg_raggraph.ab_gate.io import GoldQuestion  # noqa: F401


def test_has_four_locked_fields():
    from pg_raggraph.ab_gate import GoldQuestion

    field_names = {f.name for f in dataclasses.fields(GoldQuestion)}
    assert field_names == {"id", "question", "gold_answer", "required_facts"}, (
        f"GoldQuestion must have exactly the 4 locked fields; got {field_names}"
    )


def test_is_frozen():
    from pg_raggraph.ab_gate import GoldQuestion

    g = GoldQuestion(id="q1", question="Q?", gold_answer="A", required_facts=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        g.id = "q2"  # type: ignore[misc]


def test_required_facts_defaults_to_none():
    from pg_raggraph.ab_gate import GoldQuestion

    g = GoldQuestion(id="q1", question="Q?", gold_answer="A")
    assert g.required_facts is None


def test_gold_answer_defaults_to_none():
    from pg_raggraph.ab_gate import GoldQuestion

    g = GoldQuestion(id="q1", question="Q?")
    assert g.gold_answer is None
    assert g.required_facts is None
