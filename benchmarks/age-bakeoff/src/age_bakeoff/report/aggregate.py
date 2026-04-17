"""Aggregation helpers -- pure, deterministic, no I/O."""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Iterable

from age_bakeoff.models import QuestionClass, RunResult


def latency_percentiles(
    results: Iterable[RunResult], metric: str = "retrieval_ms"
) -> dict[str, float]:
    """Compute p50/p95/p99/mean for a latency metric."""
    values = sorted(
        getattr(r, metric) for r in results if getattr(r, metric) >= 0
    )
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0, "n": 0}

    def _pct(p: float) -> float:
        if len(values) == 1:
            return values[0]
        idx = (len(values) - 1) * p
        lo, hi = int(idx), min(int(idx) + 1, len(values) - 1)
        return values[lo] * (1 - (idx - lo)) + values[hi] * (idx - lo)

    return {
        "p50": _pct(0.50),
        "p95": _pct(0.95),
        "p99": _pct(0.99),
        "mean": statistics.mean(values),
        "n": len(values),
    }


def group_by_engine_and_class(
    results: list[RunResult],
    question_class_by_id: dict[str, QuestionClass],
) -> dict[str, dict[QuestionClass, list[RunResult]]]:
    """Group results by engine name, then question class."""
    grouped: dict[str, dict[QuestionClass, list[RunResult]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in results:
        qc = question_class_by_id.get(r.question_id)
        if qc:
            grouped[r.engine][qc].append(r)
    return {k: dict(v) for k, v in grouped.items()}


def group_by_engine(
    results: list[RunResult],
) -> dict[str, list[RunResult]]:
    """Group results by engine name."""
    grouped: dict[str, list[RunResult]] = defaultdict(list)
    for r in results:
        grouped[r.engine].append(r)
    return dict(grouped)
