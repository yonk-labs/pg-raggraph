"""Unit tests for the vector_first recall-shortfall warning + metric.

When ``retrieval_strategy='vector_first'`` returns fewer chunks than
``top_k`` after the post-filter step, the bridge emits two paired
signals: a human-readable WARNING on ``pg_raggraph.retrieval`` and a
structured metric event on ``pg_raggraph.metrics``. This module pins:

1. The WARNING fires when rows_returned < top_k.
2. The message text contains enough context for an operator to act
   (oversample_factor, the actual k that was queried, the mitigation).
3. The WARNING is at WARNING level — not INFO, not ERROR.
4. A paired metric event lands on ``pg_raggraph.metrics`` with
   ``shortfall_ratio`` for observability stacks to alert on.
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


# --- metric emission (paired with the WARNING) ---


def test_metric_event_fires_on_shortfall(caplog):
    """A pgrg.vector_first.recall_shortfall metric event lands on the
    pg_raggraph.metrics logger alongside the human-readable warning.
    Observability stacks can route the two independently."""
    with caplog.at_level(logging.INFO, logger="pg_raggraph.metrics"):
        _warn_vector_first_recall_shortfall(
            rows_returned=3,
            top_k=10,
            oversample_k=100,
            oversample_factor=10,
        )
    metric_records = [r for r in caplog.records if r.name == "pg_raggraph.metrics"]
    assert len(metric_records) == 1, (
        f"expected 1 metric event, got {len(metric_records)}: {metric_records}"
    )
    rec = metric_records[0]
    assert rec.levelname == "INFO"
    assert rec.getMessage() == "pgrg.vector_first.recall_shortfall"
    # `extra=` dict surfaces as attributes on the LogRecord; verify the
    # operator-actionable fields are present.
    assert rec.event == "pgrg.vector_first.recall_shortfall"
    assert rec.rows_returned == 3
    assert rec.top_k == 10
    assert rec.oversample_k == 100
    assert rec.oversample_factor == 10
    assert rec.shortfall_ratio == 0.3


def test_metric_shortfall_ratio_zero_when_total_miss(caplog):
    """0 rows returned out of 10 requested → ratio 0.0. Critical signal —
    operators alert when aggregated ratio percentiles dip."""
    with caplog.at_level(logging.INFO, logger="pg_raggraph.metrics"):
        _warn_vector_first_recall_shortfall(
            rows_returned=0, top_k=10, oversample_k=100, oversample_factor=10
        )
    rec = next(r for r in caplog.records if r.name == "pg_raggraph.metrics")
    assert rec.shortfall_ratio == 0.0


def test_metric_shortfall_ratio_handles_top_k_zero(caplog):
    """Defensive: if a caller somehow asks for top_k=0 (shouldn't happen),
    division-by-zero must not raise. Ratio falls back to 0.0."""
    with caplog.at_level(logging.INFO, logger="pg_raggraph.metrics"):
        _warn_vector_first_recall_shortfall(
            rows_returned=0, top_k=0, oversample_k=0, oversample_factor=10
        )
    rec = next(r for r in caplog.records if r.name == "pg_raggraph.metrics")
    assert rec.shortfall_ratio == 0.0
