"""Unit tests for evolution-related PGRGConfig fields."""

from datetime import datetime, timezone

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.evolution import evolution_where_clauses


def test_evolution_tier_defaults_off():
    c = PGRGConfig()
    assert c.evolution_tier == "off"


def test_evolution_scoring_weight_defaults():
    c = PGRGConfig()
    # Starting weights (pending per-corpus tuning via rag.tune_scoring_weights)
    assert c.w_sem == 0.50
    assert c.w_bm25 == 0.20
    assert c.w_graph == 0.20
    assert c.w_recent == 0.10
    assert c.w_supersession == 0.10
    assert c.temporal_half_life_years == 5.0
    assert c.lambda_supersession == 0.5


def test_retracted_behavior_default_flag():
    assert PGRGConfig().retracted_behavior == "flag"


def test_supersession_behavior_default_surface_both():
    assert PGRGConfig().supersession_behavior == "surface_both"


def test_fact_extractor_default_none():
    assert PGRGConfig().fact_extractor == "none"


def test_evolution_tier_literal_values(monkeypatch):
    # Round-trip through env var
    for value in ("off", "structural", "fact_aware", "full"):
        monkeypatch.setenv("PGRG_EVOLUTION_TIER", value)
        c = PGRGConfig()
        assert c.evolution_tier == value


def test_invalid_evolution_tier_rejected(monkeypatch):
    monkeypatch.setenv("PGRG_EVOLUTION_TIER", "bogus")
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PGRGConfig()


def test_as_of_naive_datetime_rejected():
    """Naive datetimes silently mismatch timestamptz columns — must reject at boundary."""
    cfg = PGRGConfig(evolution_tier="structural")
    with pytest.raises(ValueError, match="timezone-aware"):
        evolution_where_clauses(cfg, as_of=datetime(2023, 6, 1))


def test_as_of_aware_datetime_accepted():
    cfg = PGRGConfig(evolution_tier="structural")
    clauses, params = evolution_where_clauses(cfg, as_of=datetime(2023, 6, 1, tzinfo=timezone.utc))
    assert any("effective_from" in c for c in clauses)
    assert params["as_of"].tzinfo is not None


def test_as_of_off_tier_skips_validation():
    """Off-tier short-circuits before guards run — naive datetime is harmless there."""
    cfg = PGRGConfig(evolution_tier="off")
    clauses, params = evolution_where_clauses(cfg, as_of=datetime(2023, 6, 1))
    assert clauses == [] and params == {}
