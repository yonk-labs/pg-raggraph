"""Unit tests for the optional RRF (Reciprocal Rank Fusion) mode (issue #57).

Covers config knobs, helper resolution, the fused-score expression, naive
SQL shape, the linear-unchanged guard, and the Python hybrid merge. End-to-end
ordering is covered by tests/integration/test_rrf_fusion_it.py.
"""

from __future__ import annotations

import inspect

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.retrieval import (
    _build_naive_prefilter,
    _build_naive_query,
    _build_naive_query_twostage,
    _build_naive_vector_first,
    _effective_fusion,
    _rrf_fused_base_expr,
    _rrf_merge,
)
from pg_raggraph.retrieval import query as retrieval_query


def test_fusion_defaults_to_linear():
    assert PGRGConfig().fusion == "linear"


def test_rrf_k_default_is_60():
    assert PGRGConfig().rrf_k == 60


def test_fusion_accepts_rrf():
    cfg = PGRGConfig(fusion="rrf")
    assert cfg.fusion == "rrf"


def test_fusion_rejects_unknown():
    with pytest.raises(ValueError):
        PGRGConfig(fusion="bogus")


def test_effective_fusion_none_falls_back_to_config():
    assert _effective_fusion(PGRGConfig(fusion="rrf"), None) == "rrf"
    assert _effective_fusion(PGRGConfig(), None) == "linear"


def test_effective_fusion_override_wins():
    cfg = PGRGConfig(fusion="linear")
    assert _effective_fusion(cfg, "rrf") == "rrf"
    assert _effective_fusion(cfg, "linear") == "linear"


def test_effective_fusion_invalid_raises():
    with pytest.raises(ValueError, match="Invalid fusion"):
        _effective_fusion(PGRGConfig(), "bogus")


def test_rrf_fused_base_expr_shape():
    expr = _rrf_fused_base_expr()
    assert "%(w_sem)s" in expr and "vec_rank" in expr
    assert "%(w_bm25)s" in expr and "bm25_rank" in expr
    assert "%(rrf_k)s" in expr
    assert "graph" not in expr


def test_naive_linear_sql_unchanged_shape():
    """SC-006: default (linear) path must NOT contain any RRF machinery."""
    sql, _ = _build_naive_query(PGRGConfig())  # fusion defaults to linear
    assert "rank()" not in sql
    assert "WITH scored AS" not in sql
    assert "ORDER BY score DESC" in sql


def test_naive_rrf_emits_ranked_cte():
    """SC-003: RRF path wraps the legs in a ranked CTE and fuses by rank."""
    sql, _ = _build_naive_query(PGRGConfig(), fusion="rrf")
    assert "WITH scored AS" in sql
    assert "rank() OVER (ORDER BY vec_score DESC)" in sql
    assert "rank() OVER (ORDER BY bm25_score DESC)" in sql
    assert "%(rrf_k)s" in sql
    assert "JOIN documents d ON d.id = r.document_id" in sql
    assert "ORDER BY score DESC" in sql


def test_twostage_rrf_keeps_candidate_cte_and_ranks():
    sql, _ = _build_naive_query_twostage(PGRGConfig(), fusion="rrf")
    assert "ORDER BY c.embedding <=> %(embedding)s::vector" in sql
    assert "LIMIT %(candidate_k)s" in sql
    assert "rank() OVER (ORDER BY vec_score DESC)" in sql
    assert "%(rrf_k)s" in sql


def test_twostage_linear_unchanged():
    sql, _ = _build_naive_query_twostage(PGRGConfig())
    assert "rank()" not in sql


def test_prefilter_rrf_keeps_filtered_cte_and_ranks():
    sql, _ = _build_naive_prefilter(PGRGConfig(), fusion="rrf")
    assert "WITH filtered AS" in sql
    assert "ORDER BY c.embedding" not in sql
    assert "rank() OVER (ORDER BY vec_score DESC)" in sql


def test_prefilter_linear_unchanged():
    sql, _ = _build_naive_prefilter(PGRGConfig())
    assert "rank()" not in sql


def test_vector_first_rrf_keeps_bare_hnsw_cte_and_postfilter():
    sql, _ = _build_naive_vector_first(PGRGConfig(), fusion="rrf")
    assert "LIMIT %(vector_first_k)s" in sql
    assert "rank() OVER (ORDER BY vec_score DESC)" in sql
    assert "WHERE d.namespace = %(namespace)s" in sql


def test_vector_first_linear_unchanged():
    sql, _ = _build_naive_vector_first(PGRGConfig())
    assert "rank()" not in sql


def test_query_exposes_fusion_param():
    sig = inspect.signature(retrieval_query)
    assert "fusion" in sig.parameters
    assert sig.parameters["fusion"].default is None


def test_rrf_merge_reorders_vs_max_score():
    """SC-007: a chunk strong in BOTH lists outranks a chunk that is #1 in
    one list only — which max-score dedup would not achieve."""
    local = [{"id": "B", "score": 0.99}, {"id": "A", "score": 0.80}]
    global_ = [{"id": "A", "score": 0.70}, {"id": "C", "score": 0.65}]
    fused = _rrf_merge(local, global_, k=60, top_k=3)
    ids = [r["id"] for r in fused]
    assert ids[0] == "A"
    assert all("score" in r for r in fused)
    assert fused[0]["score"] > fused[1]["score"]


def test_rrf_merge_respects_top_k():
    local = [{"id": str(i), "score": 1.0 - i / 10} for i in range(5)]
    fused = _rrf_merge(local, [], k=60, top_k=2)
    assert len(fused) == 2
