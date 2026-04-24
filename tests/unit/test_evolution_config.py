"""Unit tests for evolution-related PGRGConfig fields."""
from pg_raggraph.config import PGRGConfig


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
    assert c.w_super == 0.10
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
