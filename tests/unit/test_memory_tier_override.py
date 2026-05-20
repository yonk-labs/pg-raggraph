"""Unit tests for SP-A ``memory_tier`` config + per-call override (#4).

These exercise the helper + the SQL fragment shape only. End-to-end
ingest-and-query behavior against a real `agent_memory.memory` table is
covered separately by the bridge example.
"""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.evolution import _effective_memory_tier, memory_tier_clause

# --- helper resolution ---


def test_effective_none_falls_back_to_config():
    cfg = PGRGConfig(memory_tier="consolidated")
    assert _effective_memory_tier(cfg, None) == "consolidated"


def test_effective_override_wins():
    cfg = PGRGConfig(memory_tier="consolidated")
    assert _effective_memory_tier(cfg, "provisional") == "provisional"
    assert _effective_memory_tier(cfg, "both") == "both"


def test_effective_invalid_override_raises():
    cfg = PGRGConfig(memory_tier="both")
    with pytest.raises(ValueError, match="Invalid memory_tier"):
        _effective_memory_tier(cfg, "bogus")


def test_config_default_is_both():
    """Default `both` means the filter never fires for non-memory corpora."""
    assert PGRGConfig().memory_tier == "both"


# --- SQL fragment ---


def test_both_returns_empty_no_filter():
    cfg = PGRGConfig(memory_tier="both")
    clause, params = memory_tier_clause(cfg)
    assert clause == "" and params == {}


def test_override_both_suppresses_config_filter():
    """Per-call ``both`` must bypass even a non-default config."""
    cfg = PGRGConfig(memory_tier="consolidated")
    clause, params = memory_tier_clause(cfg, override="both")
    assert clause == "" and params == {}


def test_consolidated_returns_filter_with_bind_param():
    cfg = PGRGConfig(memory_tier="consolidated")
    clause, params = memory_tier_clause(cfg, chunk_alias="c")
    assert "c.metadata->>'tier'" in clause
    assert "IS NULL" in clause, "non-memory chunks (no tier metadata) must pass through"
    assert "%(memory_tier)s" in clause
    assert params == {"memory_tier": "consolidated"}


def test_provisional_returns_filter():
    cfg = PGRGConfig(memory_tier="provisional")
    clause, params = memory_tier_clause(cfg, chunk_alias="rc")
    assert "rc.metadata->>'tier'" in clause
    assert params == {"memory_tier": "provisional"}


def test_chunk_alias_threads_into_clause():
    cfg = PGRGConfig(memory_tier="consolidated")
    for alias in ("c", "cand", "rc"):
        clause, _ = memory_tier_clause(cfg, chunk_alias=alias)
        assert f"{alias}.metadata->>'tier'" in clause


def test_override_provisional_against_config_consolidated():
    """Per-call override goes both directions like retracted_behavior."""
    cfg = PGRGConfig(memory_tier="consolidated")
    clause, params = memory_tier_clause(cfg, override="provisional")
    assert params == {"memory_tier": "provisional"}


def test_invalid_override_raises_in_clause_builder():
    cfg = PGRGConfig(memory_tier="both")
    with pytest.raises(ValueError, match="Invalid memory_tier"):
        memory_tier_clause(cfg, override="bogus")
