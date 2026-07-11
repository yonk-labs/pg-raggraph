"""Unit tests for the BM25 lexical backend (issue #96).

Covers config knobs, the backend-swapped SQL expression in every builder,
the BM25 reference math (IDF ordering, length normalization, tf saturation),
and identifier tokenization on the query side. SQL execution of the same
formula is covered by tests/integration/test_bm25_lexical_it.py.
"""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.lexical import bm25_score, bm25_score_sql, lexical_score_sql
from pg_raggraph.retrieval import (
    _build_global_query,
    _build_local_query,
    _build_naive_prefilter,
    _build_naive_query,
    _build_naive_query_twostage,
    _build_naive_vector_first,
    _to_or_tsquery,
)

# --- config knobs ---


def test_lexical_backend_defaults_to_ts_rank():
    assert PGRGConfig().lexical_backend == "ts_rank"


def test_bm25_knob_defaults():
    cfg = PGRGConfig()
    assert cfg.bm25_k1 == 1.2
    assert cfg.bm25_b == 0.75


def test_lexical_backend_accepts_bm25():
    assert PGRGConfig(lexical_backend="bm25").lexical_backend == "bm25"


def test_lexical_backend_rejects_unknown():
    with pytest.raises(ValueError):
        PGRGConfig(lexical_backend="tfidf")


# --- expression selection ---


def test_ts_rank_expression_byte_identical():
    """The default backend must reproduce the historical inline expression
    exactly — existing deployments' SQL may not change by a byte."""
    assert (
        lexical_score_sql(PGRGConfig(), "c")
        == "ts_rank(c.search_vector, to_tsquery('english', %(tsquery)s))"
    )


def test_bm25_expression_shape():
    expr = lexical_score_sql(PGRGConfig(lexical_backend="bm25"), "cand")
    assert "lexeme_stats" in expr
    assert "lexical_corpus_stats" in expr
    assert "%(bm25_k1)s" in expr and "%(bm25_b)s" in expr
    assert "pgrg_identifier_tsvector(%(query)s)" in expr  # identifier-safe query terms
    assert "cand.search_vector" in expr
    assert "ts_rank" not in expr


def test_bm25_expression_is_namespace_scoped():
    expr = bm25_score_sql("c")
    assert expr.count("%(namespace)s") == 2  # both stats joins


@pytest.mark.parametrize(
    "builder",
    [
        _build_naive_query,
        _build_naive_query_twostage,
        _build_naive_prefilter,
        _build_naive_vector_first,
    ],
)
@pytest.mark.parametrize("fusion", ["linear", "rrf"])
def test_naive_builders_swap_lexical_backend(builder, fusion):
    ts_sql, _ = builder(PGRGConfig(), fusion=fusion)
    bm_sql, _ = builder(PGRGConfig(lexical_backend="bm25"), fusion=fusion)
    assert "lexeme_stats" not in ts_sql and "ts_rank(" in ts_sql
    assert "lexeme_stats" in bm_sql and "ts_rank(" not in bm_sql


@pytest.mark.parametrize("builder", [_build_local_query, _build_global_query])
@pytest.mark.parametrize("fusion", ["linear", "rrf"])
def test_graph_builders_swap_lexical_backend(builder, fusion):
    ts_sql, _ = builder(PGRGConfig(), fusion=fusion)
    bm_sql, _ = builder(PGRGConfig(lexical_backend="bm25"), fusion=fusion)
    assert "lexeme_stats" not in ts_sql and "ts_rank(" in ts_sql
    assert "lexeme_stats" in bm_sql and "ts_rank(" not in bm_sql


# --- BM25 reference math (mirrors the SQL formula) ---


def test_idf_ordering_rare_beats_common():
    """A rare-term match must outscore a common-term match at equal tf —
    the defect ts_rank has (no corpus IDF)."""
    rare = bm25_score(tf=1, df=1, doc_count=100, doc_len=50, avg_len=50)
    common = bm25_score(tf=1, df=90, doc_count=100, doc_len=50, avg_len=50)
    assert rare > common * 10


def test_idf_common_term_cannot_win_on_tf_alone():
    """Term spam: tf=20 of a corpus-wide term still loses to tf=1 of a
    unique term (k1 saturates tf; IDF dominates)."""
    spam = bm25_score(tf=20, df=95, doc_count=100, doc_len=50, avg_len=50)
    unique = bm25_score(tf=1, df=1, doc_count=100, doc_len=50, avg_len=50)
    assert unique > spam


def test_length_normalization_penalizes_long_docs():
    short = bm25_score(tf=2, df=10, doc_count=100, doc_len=25, avg_len=50)
    long_ = bm25_score(tf=2, df=10, doc_count=100, doc_len=200, avg_len=50)
    assert short > long_


def test_tf_saturation():
    """Doubling tf must yield diminishing returns (k1 saturation)."""
    s1 = bm25_score(tf=1, df=10, doc_count=100, doc_len=50, avg_len=50)
    s2 = bm25_score(tf=2, df=10, doc_count=100, doc_len=50, avg_len=50)
    s4 = bm25_score(tf=4, df=10, doc_count=100, doc_len=50, avg_len=50)
    assert s2 - s1 > s4 - s2 > 0


def test_idf_nonnegative_under_stats_drift():
    """df > doc_count (possible only under stats drift) must not go
    negative or blow up — mirrors the SQL GREATEST guard."""
    assert bm25_score(tf=1, df=10, doc_count=5, doc_len=50, avg_len=50) >= 0.0


# --- identifier tokenization (query side) ---


def test_or_tsquery_preserves_underscore_identifiers():
    """Regression guard: Python's \\w+ keeps underscores, so the identifier
    reaches to_tsquery intact (where it becomes a lexeme phrase)."""
    assert "validate_billing_archive" in _to_or_tsquery("how does validate_billing_archive work")


def test_or_tsquery_preserves_hyphen_compounds_and_parts():
    """#102/#103: the bare \\w+ split dropped hyphens, desyncing from Postgres
    (which stores INC-0001 as 'inc' + '-0001'). Keep the compound (→ phrase that
    matches the index) AND the parts (→ recall for natural hyphenated phrases)."""
    q = _to_or_tsquery("what caused INC-0001")
    terms = q.split(" | ")
    assert "inc-0001" in terms  # compound → to_tsquery phrase 'inc' <-> '-0001'
    assert "inc" in terms and "0001" in terms  # parts preserved

    # Natural hyphenated phrase keeps part-matching recall, not a strict compound.
    mh = _to_or_tsquery("multi-hop retrieval").split(" | ")
    assert {"multi-hop", "multi", "hop", "retrieval"} <= set(mh)


def test_or_tsquery_byte_identical_for_non_hyphenated():
    """The fix must not perturb non-hyphenated queries (contract)."""
    assert _to_or_tsquery("payment service outage") == "payment | service | outage"
