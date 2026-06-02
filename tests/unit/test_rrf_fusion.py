"""Unit tests for the optional RRF (Reciprocal Rank Fusion) mode (issue #57).

Covers config knobs, helper resolution, the fused-score expression, naive
SQL shape, the linear-unchanged guard, and the Python hybrid merge. End-to-end
ordering is covered by tests/integration/test_rrf_fusion_it.py.
"""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig


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


from pg_raggraph.retrieval import _effective_fusion, _rrf_fused_base_expr


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


from pg_raggraph.retrieval import _build_naive_query


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
