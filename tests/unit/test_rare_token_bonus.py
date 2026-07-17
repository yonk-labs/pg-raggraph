"""Unit tests for the #114 IDF-coverage rare-token bonus.

SQL-shape assertions only — ranking behavior on a real corpus is covered by
tests/integration/test_rare_token_ranking.py.
"""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.lexical import idf_coverage_sql
from pg_raggraph.retrieval import (
    _build_global_query,
    _build_local_query,
    _build_naive_prefilter,
    _build_naive_query,
    _build_naive_query_twostage,
    _build_naive_vector_first,
)

NAIVE_BUILDERS = [
    _build_naive_query,
    _build_naive_query_twostage,
    _build_naive_prefilter,
    _build_naive_vector_first,
]


def test_w_rare_default_on():
    # 0.002 calibrated on the MuSiQue/MHR retrieval A/B (2026-07-17):
    # neutral on multi-hop semantic QA, still decisive on the #114 class.
    assert PGRGConfig().w_rare == 0.002


@pytest.mark.parametrize("builder", NAIVE_BUILDERS)
@pytest.mark.parametrize("fusion", ["linear", "rrf"])
def test_naive_builders_carry_rare_bonus_by_default(builder, fusion):
    sql, _ = builder(PGRGConfig(), fusion=fusion)
    assert "%(w_rare)s" in sql
    assert "lexeme_stats" in sql  # coverage reads the migration-016 stats


@pytest.mark.parametrize("builder", NAIVE_BUILDERS)
@pytest.mark.parametrize("fusion", ["linear", "rrf"])
def test_w_rare_zero_is_a_kill_switch(builder, fusion):
    """w_rare=0 must emit byte-identical pre-#114 SQL — no bonus term, no
    stats references (under the default ts_rank backend)."""
    sql, _ = builder(PGRGConfig(w_rare=0), fusion=fusion)
    assert "%(w_rare)s" not in sql
    assert "lexeme_stats" not in sql


@pytest.mark.parametrize("builder", [_build_local_query, _build_global_query])
@pytest.mark.parametrize("fusion", ["linear", "rrf"])
def test_graph_builders_carry_rare_bonus_by_default(builder, fusion):
    """The graph-gated pool has the same near-duplicate ordering blindness —
    local/global carry the bonus too (follow-up to #114)."""
    sql, _ = builder(PGRGConfig(), fusion=fusion)
    assert "%(w_rare)s" in sql


@pytest.mark.parametrize("builder", [_build_local_query, _build_global_query])
@pytest.mark.parametrize("fusion", ["linear", "rrf"])
def test_graph_builders_kill_switch(builder, fusion):
    sql, _ = builder(PGRGConfig(w_rare=0), fusion=fusion)
    assert "%(w_rare)s" not in sql
    assert "lexeme_stats" not in sql


def test_coverage_sql_is_namespace_scoped_and_bounded():
    frag = idf_coverage_sql("cand")
    assert frag.count("%(namespace)s") == 4  # both sums scope stats by namespace
    assert "GREATEST" in frag  # div-by-zero guard when stats are empty
    assert "cand.id" in frag  # correlated on the enclosing chunk row
