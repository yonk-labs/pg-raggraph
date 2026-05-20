"""Unit tests for the vector_first recall-shortfall warning.

When ``retrieval_strategy='vector_first'`` returns fewer chunks than
``top_k`` after the post-filter step, the bridge logs a structured
warning so the silent low-recall case is visible. This module pins:

1. The warning fires when rows_returned < top_k.
2. The message text contains enough context for an operator to act
   (oversample_factor, the actual k that was queried, the mitigation).
3. The warning is at WARNING level — not INFO, not ERROR.
"""

from __future__ import annotations

import logging

from pg_raggraph.retrieval import _warn_vector_first_recall_shortfall


def test_warning_fires_at_warning_level(caplog):
    with caplog.at_level(logging.WARNING, logger="pg_raggraph.retrieval"):
        _warn_vector_first_recall_shortfall(
            rows_returned=3,
            top_k=10,
            oversample_k=100,
            oversample_factor=10,
        )
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelname == "WARNING"
    assert record.name == "pg_raggraph.retrieval"


def test_warning_message_includes_recall_facts(caplog):
    """An operator reading logs must learn: how many rows came back, what
    was requested, what the HNSW seed size was, and what to do about it."""
    with caplog.at_level(logging.WARNING, logger="pg_raggraph.retrieval"):
        _warn_vector_first_recall_shortfall(
            rows_returned=2,
            top_k=10,
            oversample_k=100,
            oversample_factor=10,
        )
    msg = caplog.records[0].getMessage()
    assert "returned 2 rows" in msg
    assert "requested 10" in msg
    assert "HNSW seeded 100 candidates" in msg
    # Mitigation guidance must be present.
    assert "retrieval_oversample_factor" in msg
    assert "pre_filter" in msg
    # Cookbook anchor for the operator to dig deeper.
    assert "retrieval-strategy.md" in msg


def test_warning_extreme_shortfall_still_renders(caplog):
    """Edge case: post-filter trims to zero. Message still well-formed."""
    with caplog.at_level(logging.WARNING, logger="pg_raggraph.retrieval"):
        _warn_vector_first_recall_shortfall(
            rows_returned=0,
            top_k=10,
            oversample_k=100,
            oversample_factor=10,
        )
    msg = caplog.records[0].getMessage()
    assert "returned 0 rows" in msg
    assert "requested 10" in msg
