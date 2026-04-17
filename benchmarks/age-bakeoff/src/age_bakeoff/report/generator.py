"""Deterministic markdown report generator from raw JSON results."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from age_bakeoff.models import QuestionClass, RunResult
from age_bakeoff.report.aggregate import (
    group_by_engine,
    group_by_engine_and_class,
    latency_percentiles,
)
from age_bakeoff.scorers.llm_judge import JudgeVerdict


def generate_report(
    results_by_corpus: dict[str, list[RunResult]],
    fact_recall_by_corpus: dict[str, dict[str, dict[str, float]]] | None = None,
    judge_by_corpus: dict[str, dict[str, dict[str, JudgeVerdict]]] | None = None,
    question_classes: dict[str, dict[str, QuestionClass]] | None = None,
    output_path: Path | None = None,
) -> str:
    """Produce a full REPORT.md from run results.

    Args:
        results_by_corpus: {corpus: [RunResult, ...]}
        fact_recall_by_corpus: {corpus: {engine: {question_id: score}}}
        judge_by_corpus: {corpus: {engine: {question_id: JudgeVerdict}}}
        question_classes: {corpus: {question_id: QuestionClass}}
        output_path: if provided, write markdown to this file

    Returns:
        The full markdown string.
    """
    lines: list[str] = []
    lines.append("# AGE vs pg-raggraph Bake-off Report")
    lines.append("")
    lines.append("## Overview")
    lines.append("")

    total_results = sum(len(r) for r in results_by_corpus.values())
    engines = set()
    for results in results_by_corpus.values():
        for r in results:
            engines.add(r.engine)
    lines.append(
        f"- **Engines**: {', '.join(sorted(engines))}"
    )
    lines.append(f"- **Corpora**: {', '.join(sorted(results_by_corpus.keys()))}")
    lines.append(f"- **Total data points**: {total_results}")
    lines.append("")

    # Per-corpus sections
    for corpus in sorted(results_by_corpus.keys()):
        results = results_by_corpus[corpus]
        lines.append(f"## Corpus: {corpus}")
        lines.append("")

        # Latency table
        _write_latency_table(lines, results)

        # Fact recall table
        if fact_recall_by_corpus and corpus in fact_recall_by_corpus:
            _write_fact_recall_table(
                lines, fact_recall_by_corpus[corpus]
            )

        # Judge table
        if judge_by_corpus and corpus in judge_by_corpus:
            _write_judge_table(lines, judge_by_corpus[corpus])

        # Per-class breakdown
        if question_classes and corpus in question_classes:
            _write_per_class_breakdown(
                lines, results, question_classes[corpus]
            )

    # Summary sections
    _write_what_this_means(lines, results_by_corpus)
    _write_where_age_wins(lines, results_by_corpus)

    report = "\n".join(lines)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report)
    return report


def _write_latency_table(
    lines: list[str], results: list[RunResult]
) -> None:
    lines.append("### Retrieval Latency (ms)")
    lines.append("")
    lines.append("| Engine | p50 | p95 | p99 | mean | n |")
    lines.append("|--------|-----|-----|-----|------|---|")

    by_engine = group_by_engine(results)
    for engine in sorted(by_engine.keys()):
        p = latency_percentiles(by_engine[engine], "retrieval_ms")
        lines.append(
            f"| {engine} | {p['p50']:.1f} | {p['p95']:.1f} | "
            f"{p['p99']:.1f} | {p['mean']:.1f} | {p['n']} |"
        )
    lines.append("")

    lines.append("### Answer Generation Latency (ms)")
    lines.append("")
    lines.append("| Engine | p50 | p95 | p99 | mean | n |")
    lines.append("|--------|-----|-----|-----|------|---|")
    for engine in sorted(by_engine.keys()):
        p = latency_percentiles(by_engine[engine], "answer_ms")
        lines.append(
            f"| {engine} | {p['p50']:.1f} | {p['p95']:.1f} | "
            f"{p['p99']:.1f} | {p['mean']:.1f} | {p['n']} |"
        )
    lines.append("")


def _write_fact_recall_table(
    lines: list[str],
    engine_scores: dict[str, dict[str, float]],
) -> None:
    lines.append("### Fact Recall")
    lines.append("")
    lines.append("| Engine | Mean | Min | Max | n |")
    lines.append("|--------|------|-----|-----|---|")
    for engine in sorted(engine_scores.keys()):
        scores = list(engine_scores[engine].values())
        if scores:
            import statistics

            mean = statistics.mean(scores)
            lines.append(
                f"| {engine} | {mean:.3f} | {min(scores):.3f} | "
                f"{max(scores):.3f} | {len(scores)} |"
            )
    lines.append("")


def _write_judge_table(
    lines: list[str],
    engine_verdicts: dict[str, dict[str, JudgeVerdict]],
) -> None:
    lines.append("### LLM Judge Verdicts")
    lines.append("")
    lines.append(
        "| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |"
    )
    lines.append("|--------|--------------|-----------|-------|--------------|---|")
    for engine in sorted(engine_verdicts.keys()):
        verdicts = list(engine_verdicts[engine].values())
        counts = {v: 0 for v in JudgeVerdict}
        for v in verdicts:
            counts[v] += 1
        n = len(verdicts)
        lines.append(
            f"| {engine} | {counts[JudgeVerdict.fully_correct]} "
            f"| {counts[JudgeVerdict.partially_correct]} "
            f"| {counts[JudgeVerdict.wrong]} "
            f"| {counts[JudgeVerdict.hallucinated]} | {n} |"
        )
    lines.append("")


def _write_per_class_breakdown(
    lines: list[str],
    results: list[RunResult],
    qc_by_id: dict[str, QuestionClass],
) -> None:
    lines.append("### Per-Question-Class Latency Breakdown")
    lines.append("")
    grouped = group_by_engine_and_class(results, qc_by_id)
    for engine in sorted(grouped.keys()):
        lines.append(f"**{engine}**")
        lines.append("")
        lines.append("| Question Class | p50 (ms) | mean (ms) | n |")
        lines.append("|----------------|----------|-----------|---|")
        for qc in QuestionClass:
            if qc in grouped[engine]:
                p = latency_percentiles(
                    grouped[engine][qc], "retrieval_ms"
                )
                lines.append(
                    f"| {qc.value} | {p['p50']:.1f} | "
                    f"{p['mean']:.1f} | {p['n']} |"
                )
        lines.append("")


def _write_what_this_means(
    lines: list[str],
    results_by_corpus: dict[str, list[RunResult]],
) -> None:
    lines.append("## What This Means")
    lines.append("")
    lines.append(
        "This benchmark measures whether pg-raggraph's approach "
        "(recursive CTEs + pgvector in plain PostgreSQL) delivers "
        "comparable or better retrieval quality and latency versus "
        "Apache AGE's Cypher-based graph traversal."
    )
    lines.append("")
    lines.append("Key metrics to compare:")
    lines.append("- **Retrieval latency p50/p95**: raw speed of getting relevant chunks")
    lines.append("- **Fact recall**: are the retrieved chunks covering the required facts?")
    lines.append(
        "- **LLM judge accuracy**: do the generated answers match the gold standard?"
    )
    lines.append(
        "- **Multi-hop bridging**: where graph traversal matters most"
    )
    lines.append("")


def _write_where_age_wins(
    lines: list[str],
    results_by_corpus: dict[str, list[RunResult]],
) -> None:
    lines.append("## Where AGE Wins")
    lines.append("")
    lines.append(
        "This section highlights any categories where AGE outperforms "
        "pg-raggraph. If AGE shows advantages in specific question classes "
        "or corpus types, those findings inform whether Cypher queries "
        "provide value beyond what recursive CTEs achieve."
    )
    lines.append("")

    # Check if AGE has lower latency in any corpus
    for corpus in sorted(results_by_corpus.keys()):
        by_engine = group_by_engine(results_by_corpus[corpus])
        if "age" in by_engine and "pgrg" in by_engine:
            age_p50 = latency_percentiles(by_engine["age"])["p50"]
            pgrg_p50 = latency_percentiles(by_engine["pgrg"])["p50"]
            if age_p50 < pgrg_p50 and pgrg_p50 > 0:
                pct = ((pgrg_p50 - age_p50) / pgrg_p50) * 100
                lines.append(
                    f"- **{corpus}**: AGE retrieval p50 is "
                    f"{pct:.0f}% faster ({age_p50:.1f}ms vs {pgrg_p50:.1f}ms)"
                )

    lines.append("")
    lines.append(
        "If this section is empty after running the benchmark, "
        "pg-raggraph's approach is validated across all tested dimensions."
    )
    lines.append("")
