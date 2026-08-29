"""Unit tests for the lexical entity-seed leg in graph modes (issue #105).

Local/global seeding was vector-only: ``ORDER BY embedding <=> query LIMIT
seed_k`` with no lexical participation, so opaque identifiers (case ids,
account numbers) and near-duplicate names never anchored the traversal and
the gold chunk never entered the graph-gated candidate pool. These tests
pin the SQL shape; tests/integration/test_lexical_seed_it.py proves the
retrieval consequence against a live database.
"""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.retrieval import (
    _build_global_query,
    _build_local_query,
    _lexical_seed_cte,
)


@pytest.mark.parametrize("builder", [_build_local_query, _build_global_query])
@pytest.mark.parametrize("fusion", ["linear", "rrf"])
def test_builders_include_lexical_seed_leg(builder, fusion):
    sql, _ = builder(PGRGConfig(), fusion=fusion)
    assert "lex_seeds" in sql
    assert "word_similarity(name, %(query)s)" in sql
    assert "%(seed_min_wsim)s" in sql
    assert "%(query_tokens)s" in sql


def test_local_seeds_union_capped_at_seed_k():
    """Both legs union into one seed set, capped at seed_k, best-sim first."""
    sql, _ = _build_local_query(PGRGConfig())
    seeds = sql.split("seeds AS (", 1)[1].split("neighborhood AS", 1)[0]
    assert "lex_seeds" in seeds and "vec_seeds" in seeds
    assert "LIMIT %(seed_k)s" in seeds
    assert "ORDER BY sim DESC" in seeds


def test_global_lex_seeds_feed_rel_entity_ids():
    """Lexical anchors join the global entity set directly — their chunks
    enter the pool even when no top-seed_k relationship touches them."""
    sql, _ = _build_global_query(PGRGConfig())
    rel_ids = sql.split("rel_entity_ids AS (", 1)[1].split("relevant_chunks", 1)[0]
    assert "SELECT id FROM lex_seeds" in rel_ids


def test_lexical_leg_scores_outrank_vector_leg():
    """Lexical sims are 1.0 + word_similarity — strictly above any cosine
    similarity — so verbatim name anchors always survive the seed_k cap."""
    assert "1.0 + word_similarity" in _lexical_seed_cte()


def test_seed_min_wsim_default_mirrors_pg_trgm():
    # 0.6 = pg_trgm's default word_similarity_threshold.
    assert PGRGConfig().seed_min_wsim == 0.6
