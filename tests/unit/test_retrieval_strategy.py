"""Unit tests for the ``retrieval_strategy`` config + per-call kwarg.

These cover helper resolution and SQL shape only. End-to-end behavior
(planner picking HNSW for vector_first, predicate-first materialization
for pre_filter) is covered separately by the bench in
``benchmarks/retrieval-strategy-bench/``.
"""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.retrieval import (
    _build_naive_prefilter,
    _build_naive_query,
    _build_naive_query_twostage,
    _build_naive_vector_first,
    _effective_retrieval_strategy,
)


# --- helper resolution ---


def test_effective_none_falls_back_to_config():
    cfg = PGRGConfig(retrieval_strategy="pre_filter")
    assert _effective_retrieval_strategy(cfg, None) == "pre_filter"


def test_effective_override_wins():
    cfg = PGRGConfig(retrieval_strategy="weighted")
    assert _effective_retrieval_strategy(cfg, "vector_first") == "vector_first"
    assert _effective_retrieval_strategy(cfg, "pre_filter") == "pre_filter"
    assert _effective_retrieval_strategy(cfg, "weighted") == "weighted"


def test_effective_invalid_override_raises():
    cfg = PGRGConfig()
    with pytest.raises(ValueError, match="Invalid retrieval_strategy"):
        _effective_retrieval_strategy(cfg, "bogus")


def test_default_is_weighted_backward_compat():
    """Default must be 'weighted' so the existing two_stage_retrieval
    flow is preserved byte-for-byte. Changing this is a breaking change."""
    assert PGRGConfig().retrieval_strategy == "weighted"


def test_default_oversample_factor():
    """Sensible default — 10x oversample for vector_first compensates for
    moderate post-filter selectivity."""
    assert PGRGConfig().retrieval_oversample_factor == 10


# --- SQL shape ---


def test_prefilter_emits_filtered_cte():
    cfg = PGRGConfig()
    sql, _ = _build_naive_prefilter(cfg)
    assert "WITH filtered AS" in sql
    assert "ORDER BY c.embedding" not in sql, (
        "pre_filter must NOT order by vector in the CTE — it materializes the "
        "full predicate-matching set first, then ranks in the outer query."
    )
    assert "FROM filtered cand" in sql
    assert "ORDER BY score DESC" in sql


def test_vector_first_emits_bare_hnsw_cte():
    cfg = PGRGConfig()
    sql, _ = _build_naive_vector_first(cfg)
    assert "WITH candidates AS" in sql
    assert "ORDER BY c.embedding <=>" in sql
    # Critical: the candidates CTE must NOT join documents — that's what
    # makes HNSW eligible. Today's _build_naive_query_twostage DOES join
    # inside the CTE, which is why the planner picks idx_chunk_doc over
    # HNSW for single-namespace deployments.
    cte_chunk = sql.split("SELECT cand.id")[0]
    assert "JOIN documents" not in cte_chunk, (
        "vector_first's candidate CTE must not JOIN documents — HNSW won't fire."
    )
    assert "LIMIT %(vector_first_k)s" in sql
    # Outer query applies the namespace + predicates as post-filter.
    assert "WHERE d.namespace = %(namespace)s" in sql


def test_vector_first_propagates_oversample_to_bind():
    """The vector_first_k bind param must be settable from outside."""
    cfg = PGRGConfig()
    sql, _ = _build_naive_vector_first(cfg)
    assert "%(vector_first_k)s" in sql


def test_weighted_strategy_uses_existing_builders():
    """weighted strategy must defer to today's _build_naive_query (or its
    two-stage variant). The router in query() picks between them based
    on config.two_stage_retrieval — same as before retrieval_strategy
    existed. Backward compatibility: no SQL change."""
    cfg = PGRGConfig(retrieval_strategy="weighted", two_stage_retrieval=False)
    # Even though strategy=weighted, the underlying SQL is unchanged.
    sql_single, _ = _build_naive_query(cfg)
    assert "WITH" not in sql_single  # single-pass, no CTE
    sql_ts, _ = _build_naive_query_twostage(cfg)
    assert "WITH candidates AS" in sql_ts


# --- composition with other filters ---


def test_prefilter_threads_memory_tier():
    """pre_filter must propagate the memory_tier WHERE clause into its CTE."""
    cfg = PGRGConfig(memory_tier="consolidated")
    sql, params = _build_naive_prefilter(cfg)
    # memory_tier_clause is applied to alias `c` (the chunk inside the CTE)
    assert "c.metadata->>'tier'" in sql
    assert params == {"memory_tier": "consolidated"}


def test_vector_first_threads_memory_tier_to_outer():
    """vector_first applies memory_tier as a post-filter on the candidate
    chunk metadata — alias `cand` in the outer SELECT."""
    cfg = PGRGConfig(memory_tier="consolidated")
    sql, params = _build_naive_vector_first(cfg)
    assert "cand.metadata->>'tier'" in sql
    assert params == {"memory_tier": "consolidated"}


def test_prefilter_threads_retracted_behavior():
    cfg = PGRGConfig(retracted_behavior="hide", evolution_tier="structural")
    sql, _ = _build_naive_prefilter(cfg)
    # retracted_behavior=hide adds NOT d.retracted to WHERE — should land
    # inside the CTE alongside the namespace filter.
    assert "NOT d.retracted" in sql
