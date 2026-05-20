"""Pins the fixes for issues #17 and #18.

Both bugs were variants of the same mistake: treating ``version_label``
(caller-supplied opaque content) like an evolution-scoring signal that
should be hidden when ``evolution_tier == "off"``. It isn't.

- #17: ``ChunkResult.version_label`` was always None at tier=off even
       when ``documents.version_label`` was populated.
- #18: ``GraphRAG.ask(..., version_filter="3.12")`` silently no-op'd at
       tier=off because the WHERE clause builder short-circuited the
       whole list.

Both fixes: version fields are content-scoping, not scoring. They emit
regardless of tier. Scoring fields (retracted, effective_from /
effective_to, superseded_by_id) remain tier-gated as before.
"""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.evolution import evolution_where_clauses

# --- #18: version_filter emits at tier=off ---


def test_version_filter_emits_at_tier_off() -> None:
    """The whole point of the fix: WHERE d.version_label = '3.12' lands
    in the clause list even when tier=off."""
    cfg = PGRGConfig(evolution_tier="off")
    clauses, params = evolution_where_clauses(cfg, version_filter="3.12")
    assert any("version_label" in c for c in clauses)
    assert params.get("version_filter") == "3.12"


def test_version_filter_emits_at_tier_structural() -> None:
    """Tier-on path must still emit version_filter (no regression)."""
    cfg = PGRGConfig(evolution_tier="structural")
    clauses, params = evolution_where_clauses(cfg, version_filter="3.12")
    assert any("version_label" in c for c in clauses)
    assert params.get("version_filter") == "3.12"


def test_version_filter_none_at_tier_off_returns_empty() -> None:
    """No version_filter + tier=off → still no clauses (the short-circuit
    intent is preserved: tier=off means no scoring filters)."""
    cfg = PGRGConfig(evolution_tier="off")
    clauses, params = evolution_where_clauses(cfg, version_filter=None)
    assert clauses == []
    assert params == {}


def test_scoring_filters_still_tier_gated_at_off() -> None:
    """retracted_behavior=hide + tier=off must NOT emit a clause —
    scoring filters remain tier-gated. The fix only un-gates
    version_filter, not the scoring path."""
    cfg = PGRGConfig(
        evolution_tier="off",
        retracted_behavior="hide",
        supersession_behavior="hide",
    )
    clauses, _ = evolution_where_clauses(cfg, version_filter=None)
    assert not any("retracted" in c for c in clauses)
    assert not any("supersedes_document_id" in c for c in clauses)


def test_version_filter_at_off_does_not_drag_in_scoring_filters() -> None:
    """Critical: version_filter at tier=off must NOT cause scoring
    filters to also emit. Only the explicit version_filter clause."""
    cfg = PGRGConfig(
        evolution_tier="off",
        retracted_behavior="hide",
        supersession_behavior="hide",
    )
    clauses, _ = evolution_where_clauses(cfg, version_filter="3.12")
    # Exactly one clause: the version_filter.
    assert len(clauses) == 1
    assert "version_label" in clauses[0]


def test_version_filter_doc_alias_threads_through() -> None:
    """The doc_alias parameter must reach the version_label clause —
    some builders use 'd', others might use 'doc'."""
    cfg = PGRGConfig(evolution_tier="off")
    clauses, _ = evolution_where_clauses(cfg, doc_alias="d_alias", version_filter="3.12")
    assert any("d_alias.version_label" in c for c in clauses)


def test_version_filter_with_evolution_aware_false() -> None:
    """The per-call evolution_aware=False override forces effective
    tier=off — version_filter must still apply (same logic)."""
    cfg = PGRGConfig(evolution_tier="structural")
    clauses, params = evolution_where_clauses(cfg, evolution_aware=False, version_filter="3.12")
    assert any("version_label" in c for c in clauses)
    assert params.get("version_filter") == "3.12"


# --- #17: ChunkResult.version_label tier-independence (SQL side) ---


def test_all_builders_select_version_label() -> None:
    """Sanity: every retrieval SQL builder must SELECT d.version_label
    so the row dict contains it for the ChunkResult projection. If a
    future builder drops this column, #17 regresses silently."""
    from pg_raggraph.retrieval import (
        _build_global_query,
        _build_local_query,
        _build_naive_prefilter,
        _build_naive_query,
        _build_naive_query_twostage,
        _build_naive_vector_first,
    )

    cfg = PGRGConfig()
    for builder in (
        _build_naive_query,
        _build_naive_query_twostage,
        _build_naive_prefilter,
        _build_naive_vector_first,
        _build_local_query,
        _build_global_query,
    ):
        sql_str, _ = builder(cfg)
        assert "version_label" in sql_str, (
            f"{builder.__name__} dropped d.version_label from SELECT — "
            "would regress issue #17 (ChunkResult.version_label silently None)"
        )


@pytest.mark.parametrize("tier", ["off", "structural", "fact_aware"])
def test_chunkresult_projection_treats_version_label_as_tier_independent(
    tier: str,
) -> None:
    """Pin the issue #17 fix at the source level: a future refactor that
    re-gates version_label by ``evo_on`` will loudly fail this test."""
    import inspect

    from pg_raggraph import retrieval

    src = inspect.getsource(retrieval.query)
    bad_pattern = 'version_label=(row.get("version_label") if evo_on'
    assert bad_pattern not in src, (
        "retrieval.query() re-gated version_label by evo_on — this "
        "reintroduces issue #17. version_label is caller-supplied opaque "
        "data, should be tier-independent."
    )
    good_pattern = 'version_label=row.get("version_label")'
    assert good_pattern in src, (
        "retrieval.query() should project version_label directly (issue #17)."
    )
    _ = tier  # tier parameter communicates the invariant holds across tiers
