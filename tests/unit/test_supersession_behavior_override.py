"""Unit tests for per-call ``supersession_behavior`` override.

Mirror of ``test_retracted_behavior_override.py`` — same shape, same
race-safety motivation. Multi-tenant API servers can pass
``supersession_behavior="hide"`` per-call without mutating
``rag.config.supersession_behavior`` under contention.
"""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.evolution import (
    _effective_supersession_behavior,
    evolution_where_clauses,
)


def test_effective_none_falls_back_to_config():
    cfg = PGRGConfig(supersession_behavior="surface_both")
    assert _effective_supersession_behavior(cfg, None) == "surface_both"


def test_effective_override_wins():
    cfg = PGRGConfig(supersession_behavior="surface_both")
    assert _effective_supersession_behavior(cfg, "hide") == "hide"
    assert _effective_supersession_behavior(cfg, "prefer_new") == "prefer_new"
    assert _effective_supersession_behavior(cfg, "surface_both") == "surface_both"


def test_effective_invalid_override_raises():
    cfg = PGRGConfig(supersession_behavior="surface_both")
    with pytest.raises(ValueError, match="Invalid supersession_behavior"):
        _effective_supersession_behavior(cfg, "bogus")


# --- evolution_where_clauses threading ---


def test_where_override_hide_adds_supersession_filter_when_config_is_surface_both():
    """Per-call override='hide' must apply the supersession filter even
    when cfg.supersession_behavior is 'surface_both' (the default)."""
    cfg = PGRGConfig(evolution_tier="structural", supersession_behavior="surface_both")
    clauses, _ = evolution_where_clauses(cfg, supersession_behavior="hide")
    assert any("supersedes_document_id" in c for c in clauses)


def test_where_override_none_honors_config_surface_both():
    cfg = PGRGConfig(evolution_tier="structural", supersession_behavior="surface_both")
    clauses, _ = evolution_where_clauses(cfg, supersession_behavior=None)
    assert not any("supersedes_document_id" in c for c in clauses)


def test_where_override_surface_both_suppresses_config_hide():
    """Per-call override='surface_both' must NOT add the filter even when
    cfg.supersession_behavior='hide' — override goes both ways."""
    cfg = PGRGConfig(evolution_tier="structural", supersession_behavior="hide")
    clauses, _ = evolution_where_clauses(cfg, supersession_behavior="surface_both")
    assert not any("supersedes_document_id" in c for c in clauses)


def test_where_override_prefer_new_omits_filter():
    """'prefer_new' doesn't add a hard filter — it relies on the SQL
    scoring penalty in evolution_score_expr."""
    cfg = PGRGConfig(evolution_tier="structural", supersession_behavior="hide")
    clauses, _ = evolution_where_clauses(cfg, supersession_behavior="prefer_new")
    assert not any("supersedes_document_id" in c for c in clauses)


def test_where_off_tier_short_circuits_regardless_of_override():
    cfg = PGRGConfig(evolution_tier="off", supersession_behavior="surface_both")
    clauses, params = evolution_where_clauses(cfg, supersession_behavior="hide")
    assert clauses == [] and params == {}


def test_where_invalid_override_raises():
    cfg = PGRGConfig(evolution_tier="structural", supersession_behavior="surface_both")
    with pytest.raises(ValueError, match="Invalid supersession_behavior"):
        evolution_where_clauses(cfg, supersession_behavior="bogus")
