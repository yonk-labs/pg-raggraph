"""Bridge promotes per-fact temporal fields onto the relationship dict.

Migration 006 added `effective_from`/`effective_to`/`retracted`/`retracted_at`
to the `relationships` table. The bridge in `memory_bridge.py` is the only
ingest path that currently emits these — verify the row-to-relationship
mapping forwards SP-A's temporal columns onto the relationship dict that
will reach the INSERT.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pg_raggraph.memory_bridge import rows_to_records


def _base_fact_row(**overrides):
    row = {
        "session_id": "S1",
        "tier": "consolidated",
        "kind": "fact",
        "subject": "Alice",
        "predicate": "WORKS_AT",
        "object": "Acme",
        "original_content": "Alice works at Acme.",
        "embedded_content": "Alice works at Acme.",
        "embedding": "[" + ",".join(["0.1"] * 384) + "]",
        "support_span": "works at",
        "confidence": 0.9,
        "seq_num": 1,
    }
    row.update(overrides)
    return row


def test_relationship_carries_temporal_fields_from_sp_a_row():
    eff_from = datetime(2025, 1, 1, tzinfo=timezone.utc)
    eff_to = datetime(2025, 6, 1, tzinfo=timezone.utc)
    row = _base_fact_row(effective_from=eff_from, effective_to=eff_to)

    records = rows_to_records([row])
    assert len(records) == 1
    rels = records[0]["relationships"]
    assert len(rels) == 1
    rel = rels[0]
    assert rel["effective_from"] == eff_from
    assert rel["effective_to"] == eff_to
    # Retraction fields default to absent (downstream coerces to NULL/false).
    assert "retracted" not in rel or rel["retracted"] is False
    assert "retracted_at" not in rel


def test_relationship_carries_retraction_fields_from_sp_a_row():
    retracted_at = datetime(2025, 7, 15, tzinfo=timezone.utc)
    row = _base_fact_row(retracted=True, retracted_at=retracted_at)

    records = rows_to_records([row])
    rel = records[0]["relationships"][0]
    assert rel["retracted"] is True
    assert rel["retracted_at"] == retracted_at


def test_relationship_omits_temporal_fields_when_sp_a_row_lacks_them():
    """A bridge row with no temporal columns should not inject placeholders.

    The ingest path treats missing keys as None → INSERT writes NULL.
    Verifying the bridge stays silent keeps the contract minimal: the
    *only* shape that should carry temporal info is one where SP-A
    actually supplied it.
    """
    row = _base_fact_row()  # no temporal fields

    records = rows_to_records([row])
    rel = records[0]["relationships"][0]
    assert "effective_from" not in rel
    assert "effective_to" not in rel
    assert "retracted" not in rel
    assert "retracted_at" not in rel
