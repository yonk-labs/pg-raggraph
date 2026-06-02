"""SC-001: GoldQuestion frozen dataclass with the locked fields.

Brief amendment (v0.5.0a5, real-verdict wiring): a fifth optional field
``gold_doc_id`` was added so the chunkshop ``{query, gold_doc_id}`` retrieval
target flows to the verdict writer for recall@10 / MRR (contract §3.1). The
field is optional (default None), so the original four-field construction is
byte-for-byte unchanged.
"""

import dataclasses

import pytest


def test_importable_from_ab_gate_top_level():
    from pg_raggraph.ab_gate import GoldQuestion  # noqa: F401


def test_importable_from_ab_gate_io():
    from pg_raggraph.ab_gate.io import GoldQuestion  # noqa: F401


def test_has_locked_fields():
    from pg_raggraph.ab_gate import GoldQuestion

    field_names = {f.name for f in dataclasses.fields(GoldQuestion)}
    assert field_names == {
        "id",
        "question",
        "gold_answer",
        "required_facts",
        "gold_doc_id",
    }, f"GoldQuestion field set drifted; got {field_names}"


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
