"""Unit tests for per-call ``retracted_behavior`` override (#1)."""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.evolution import (
    _effective_retracted_behavior,
    evolution_score_expr,
    evolution_where_clauses,
)


def test_effective_none_falls_back_to_config():
    cfg = PGRGConfig(retracted_behavior="flag")
    assert _effective_retracted_behavior(cfg, None) == "flag"


def test_effective_override_wins():
    cfg = PGRGConfig(retracted_behavior="flag")
    assert _effective_retracted_behavior(cfg, "hide") == "hide"
    assert _effective_retracted_behavior(cfg, "surface_both") == "surface_both"


def test_effective_invalid_override_raises():
    cfg = PGRGConfig(retracted_behavior="flag")
    with pytest.raises(ValueError, match="Invalid retracted_behavior"):
        _effective_retracted_behavior(cfg, "bogus")


# --- evolution_where_clauses ---


def test_where_override_hide_adds_filter_when_config_is_flag():
    """Per-call override='hide' must apply the retracted filter even when
    cfg.retracted_behavior is "flag" — this is the dx-poc use case where one
    GraphRAG instance serves multiple tenants with different policies."""
    cfg = PGRGConfig(evolution_tier="structural", retracted_behavior="flag")
    clauses, _ = evolution_where_clauses(cfg, retracted_behavior="hide")
    assert any("NOT d.retracted" in c for c in clauses)


def test_where_override_none_honors_config_flag():
    cfg = PGRGConfig(evolution_tier="structural", retracted_behavior="flag")
    clauses, _ = evolution_where_clauses(cfg, retracted_behavior=None)
    assert not any("NOT d.retracted" in c for c in clauses)


def test_where_override_flag_suppresses_config_hide():
    """Per-call override="flag" must NOT add the filter even when
    cfg.retracted_behavior="hide" — override goes both ways."""
    cfg = PGRGConfig(evolution_tier="structural", retracted_behavior="hide")
    clauses, _ = evolution_where_clauses(cfg, retracted_behavior="flag")
    assert not any("NOT d.retracted" in c for c in clauses)


def test_where_override_surface_both_suppresses_config_hide():
    cfg = PGRGConfig(evolution_tier="structural", retracted_behavior="hide")
    clauses, _ = evolution_where_clauses(cfg, retracted_behavior="surface_both")
    assert not any("NOT d.retracted" in c for c in clauses)


def test_where_off_tier_short_circuits_regardless_of_override():
    """When tier is off, no clauses regardless of override — preserves
    classic-retrieval byte-stability."""
    cfg = PGRGConfig(evolution_tier="off", retracted_behavior="flag")
    clauses, params = evolution_where_clauses(cfg, retracted_behavior="hide")
    assert clauses == [] and params == {}


# --- evolution_score_expr ---


def test_score_expr_override_hide_wraps_with_retraction_multiplier():
    cfg = PGRGConfig(evolution_tier="structural", retracted_behavior="flag")
    base = "1.0"
    expr = evolution_score_expr(base, cfg, retracted_behavior="hide")
    # "hide" path multiplies the body by the retraction filter expression.
    assert "CASE WHEN d.retracted" in expr


def test_score_expr_override_flag_omits_retraction_multiplier():
    cfg = PGRGConfig(evolution_tier="structural", retracted_behavior="hide")
    base = "1.0"
    expr = evolution_score_expr(base, cfg, retracted_behavior="flag")
    # Override beats config: "flag" path omits the retraction multiplier.
    assert "CASE WHEN d.retracted" not in expr


def test_score_expr_none_override_honors_config():
    cfg = PGRGConfig(evolution_tier="structural", retracted_behavior="hide")
    base = "1.0"
    expr = evolution_score_expr(base, cfg, retracted_behavior=None)
    # None falls back to config="hide" → multiplier present.
    assert "CASE WHEN d.retracted" in expr


def test_score_expr_off_tier_ignores_override():
    """Off-tier returns the bare base_score_sql regardless of override."""
    cfg = PGRGConfig(evolution_tier="off", retracted_behavior="flag")
    assert evolution_score_expr("1.0", cfg, retracted_behavior="hide") == "1.0"


def test_score_expr_invalid_override_raises():
    cfg = PGRGConfig(evolution_tier="structural", retracted_behavior="flag")
    with pytest.raises(ValueError, match="Invalid retracted_behavior"):
        evolution_score_expr("1.0", cfg, retracted_behavior="bogus")


def test_where_invalid_override_raises():
    cfg = PGRGConfig(evolution_tier="structural", retracted_behavior="flag")
    with pytest.raises(ValueError, match="Invalid retracted_behavior"):
        evolution_where_clauses(cfg, retracted_behavior="bogus")
