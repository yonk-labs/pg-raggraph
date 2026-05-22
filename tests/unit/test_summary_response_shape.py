"""Unit tests for result_id + adaptive summary length (SC-204)."""

from __future__ import annotations

from pg_raggraph import summary as summary_mod
from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import QueryResult


def test_query_result_has_result_id_default_none():
    assert QueryResult().result_id is None


def test_adaptive_length_floor_and_ceiling():
    cfg = PGRGConfig()
    floor = cfg.summary_max_length
    ceil = cfg.summary_max_length_ceiling
    assert summary_mod.adaptive_summary_length(1, cfg) == floor
    assert summary_mod.adaptive_summary_length(cfg.summary_length_floor_chunks, cfg) == floor
    assert summary_mod.adaptive_summary_length(cfg.summary_length_ceiling_chunks, cfg) == ceil
    assert summary_mod.adaptive_summary_length(10_000, cfg) == ceil


def test_adaptive_length_monotonic_nondecreasing():
    cfg = PGRGConfig()
    vals = [summary_mod.adaptive_summary_length(n, cfg) for n in range(1, 40)]
    assert vals == sorted(vals)
