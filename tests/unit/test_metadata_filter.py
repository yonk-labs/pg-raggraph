"""Unit tests for metadata filter classification (SC-301)."""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.metadata_filter import classify_filters


def test_soft_and_hard_split():
    cfg = PGRGConfig(structured_metadata_fields=["source", "tenant"])
    soft, hard = classify_filters(
        {"soft": {"topic": "billing"}, "hard": {"source": "handbook"}}, cfg
    )
    assert soft == {"topic": "billing"}
    assert hard == {"source": "handbook"}


def test_hard_filter_on_non_structured_field_rejected():
    cfg = PGRGConfig(structured_metadata_fields=["source"])
    with pytest.raises(ValueError, match="not a structured field"):
        classify_filters({"hard": {"keywords": "secrets"}}, cfg)


def test_none_returns_empty():
    assert classify_filters(None, PGRGConfig()) == ({}, {})


def test_clause_builder_shapes():
    from pg_raggraph.metadata_filter import metadata_filter_clauses

    cfg = PGRGConfig(structured_metadata_fields=["source"])
    soft_sql, where_sql, params = metadata_filter_clauses(
        {"topic": "billing"}, {"source": "handbook"}, cfg
    )
    assert soft_sql.startswith(" + ") and "CASE WHEN" in soft_sql
    assert "metadata->>" in where_sql
    # round-trip: empty in → empty out
    assert metadata_filter_clauses({}, {}, cfg) == ("", "", {})


def test_prompt_signals_are_soft_only():
    from pg_raggraph.metadata_filter import prompt_derived_soft

    cfg = PGRGConfig(prompt_metadata_signals=True, structured_metadata_fields=["category"])
    soft = prompt_derived_soft("show me finance reports about revenue", cfg)
    assert isinstance(soft, dict)
    # Whatever it returns is destined for the SOFT pool only — there is no hard
    # path through this function, so it can never exclude a chunk.


def test_prompt_signals_off_by_default():
    from pg_raggraph.metadata_filter import prompt_derived_soft

    assert prompt_derived_soft("finance reports", PGRGConfig()) == {}
