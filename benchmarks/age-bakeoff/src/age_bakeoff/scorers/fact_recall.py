"""Deterministic fact-recall scorer -- pure string matching, no LLM."""
from __future__ import annotations

import statistics

from age_bakeoff.models import Question


def score_fact_recall(
    question: Question, retrieved_contents: list[str]
) -> float:
    """Score how many required_facts appear in the retrieved content."""
    if not question.required_facts:
        return 1.0
    haystack = " \n ".join(retrieved_contents).lower()
    hits = sum(
        1 for fact in question.required_facts if fact.lower() in haystack
    )
    return hits / len(question.required_facts)


def aggregate_fact_recall(
    scores: list[float],
) -> tuple[float, float, float]:
    """Return (mean, ci_low, ci_high) with 95% CI."""
    if not scores:
        return 0.0, 0.0, 0.0
    mean = statistics.mean(scores)
    if len(scores) < 2:
        return mean, mean, mean
    sd = statistics.stdev(scores)
    margin = 1.96 * sd / (len(scores) ** 0.5)
    return mean, max(0.0, mean - margin), min(1.0, mean + margin)
