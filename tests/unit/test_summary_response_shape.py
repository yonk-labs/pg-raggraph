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


def test_adaptive_length_scales_with_context_tokens():
    cfg = PGRGConfig(
        summary_max_length=2000,
        summary_max_length_ceiling=64_000,
        summary_target_compression_ratio=0.18,
    )
    assert summary_mod.adaptive_summary_length(10, cfg, context_tokens=1_000) == 2000
    mid = summary_mod.adaptive_summary_length(10, cfg, context_tokens=20_000)
    high = summary_mod.adaptive_summary_length(10, cfg, context_tokens=100_000)
    assert 2000 < mid < high <= 64_000


def test_adaptive_length_monotonic_nondecreasing():
    cfg = PGRGConfig()
    vals = [summary_mod.adaptive_summary_length(n, cfg) for n in range(1, 40)]
    assert vals == sorted(vals)


def test_context_gate_and_fact_count_scale():
    cfg = PGRGConfig(summary_min_context_tokens=8_000, summary_max_facts=10)
    assert not summary_mod.should_summarize_context(2_500, cfg)
    assert summary_mod.should_summarize_context(8_000, cfg)
    assert summary_mod.adaptive_fact_count(8_000, cfg) == 10
    assert summary_mod.adaptive_fact_count(28_000, cfg) > 10
    assert summary_mod.adaptive_fact_count(1_000_000, cfg) == cfg.summary_max_facts_ceiling
