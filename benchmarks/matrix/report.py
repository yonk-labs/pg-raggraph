"""Summarize llm-judge matrix results into baseline-relative tables."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _group_key(row: dict[str, Any]) -> str:
    settings = row["settings"]
    if settings.get("config_label"):
        return str(settings["config_label"])
    return f"{settings['context_strategy']}:top_k={int(settings['top_k'])}"


def _summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_group_key(row)].append(row)

    out: dict[str, dict[str, Any]] = {}
    for key, group in groups.items():
        n = len(group)
        first_settings = group[0]["settings"]
        out[key] = {
            "label": key,
            "dataset": first_settings.get("dataset", ""),
            "shape_id": first_settings.get("shape_id", ""),
            "arm": first_settings.get("arm", ""),
            "chunk_strategy": first_settings.get("chunk_strategy", ""),
            "chunk_max_tokens": first_settings.get("chunk_max_tokens", ""),
            "chunk_overlap_tokens": first_settings.get("chunk_overlap_tokens", ""),
            "embedding_model": first_settings.get("embedding_model", ""),
            "retrieval_mode": first_settings.get("retrieval_mode", ""),
            "retrieval_strategy": first_settings.get("retrieval_strategy", ""),
            "rerank": first_settings.get("rerank", False),
            "top_k": first_settings.get("top_k", ""),
            "context_strategy": first_settings.get("context_strategy", ""),
            "n": n,
            "passed": sum(1 for row in group if row["passed"]),
            "pass_rate": sum(1 for row in group if row["passed"]) / n if n else 0.0,
            "avg_score": sum(float(row["score"]) for row in group) / n if n else 0.0,
            "avg_context_tokens": _avg(row["metadata"].get("context_tokens", 0) for row in group),
            "avg_source_tokens": _avg(row["metadata"].get("source_tokens", 0) for row in group),
            "avg_answer_ms": _avg(
                (row["metadata"].get("answer_generation") or {}).get("latency_ms", 0)
                for row in group
            ),
            "avg_judge_ms": _avg(row.get("latency_ms", 0) for row in group),
            "errors": sum(1 for row in group if row.get("verdict") == "ERROR"),
        }
    return out


def _avg(values) -> float:
    vals = [float(value or 0) for value in values]
    return sum(vals) / len(vals) if vals else 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _delta_pct(value: float, baseline: float) -> str:
    if not baseline:
        return "n/a"
    return f"{(value - baseline) / baseline * 100:+.1f}%"


def _savings(value: float, baseline: float) -> str:
    if not baseline:
        return "n/a"
    return f"{(1 - value / baseline) * 100:+.1f}%"


def _find_baseline(summary: dict[str, dict[str, Any]], selector: str) -> dict[str, Any] | None:
    if selector in summary:
        return summary[selector]
    terms = [term for term in selector.split(":") if term]
    for label, stats in summary.items():
        haystack = f"{label}|{stats['context_strategy']}|top_k={stats['top_k']}"
        if all(term in haystack for term in terms):
            return stats
    return None


def write_report(
    *,
    rows_path: Path,
    out_path: Path,
    rag_baseline: str,
    full_doc_baseline: str,
) -> None:
    rows = _load_rows(rows_path)
    summary = _summarize(rows)
    rag = _find_baseline(summary, rag_baseline)
    full = _find_baseline(summary, full_doc_baseline)

    ranked = sorted(
        summary.items(),
        key=lambda item: (
            -item[1]["pass_rate"],
            -item[1]["avg_score"],
            item[1]["avg_context_tokens"],
        ),
    )

    lines = [
        "# Matrix Result Report",
        "",
        f"- Source: `{rows_path}`",
        f"- Cases: {len(rows)}",
        f"- Classic RAG baseline: `{rag_baseline}`",
        f"- Full-document baseline: `{full_doc_baseline}`",
        "",
        "## Top Configurations",
        "",
        "| rank | label | n | pass rate | avg score | avg ctx tokens | token savings vs RAG | token savings vs full-doc |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, (label, stats) in enumerate(ranked[:10], 1):
        rag_savings = _savings(
            stats["avg_context_tokens"], rag["avg_context_tokens"] if rag else 0
        )
        full_savings = _savings(
            stats["avg_context_tokens"], full["avg_context_tokens"] if full else 0
        )
        lines.append(
            f"| {idx} | {label} | {stats['n']} | "
            f"{_pct(stats['pass_rate'])} | {stats['avg_score']:.3f} | "
            f"{stats['avg_context_tokens']:.0f} | {rag_savings} | {full_savings} |"
        )

    lines.extend(
        [
            "",
            "## Full Table",
            "",
            "| label | dataset | chunker | mode | top_k | context | n | pass | avg score | avg source tokens | avg ctx tokens | answer ms | judge ms | score vs RAG | token savings vs RAG | token savings vs full-doc | errors |",
            "|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for label, stats in sorted(summary.items()):
        score_delta = _delta_pct(stats["avg_score"], rag["avg_score"] if rag else 0)
        rag_savings = _savings(
            stats["avg_context_tokens"], rag["avg_context_tokens"] if rag else 0
        )
        full_savings = _savings(
            stats["avg_context_tokens"], full["avg_context_tokens"] if full else 0
        )
        lines.append(
            f"| {label} | {stats['dataset']} | "
            f"{stats['chunk_strategy']} {stats['chunk_max_tokens']}/{stats['chunk_overlap_tokens']} | "
            f"{stats['retrieval_mode']}:{stats['retrieval_strategy']}:rerank={int(bool(stats['rerank']))} | "
            f"{stats['top_k']} | {stats['context_strategy']} | "
            f"{stats['n']} | {stats['passed']}/{stats['n']} | "
            f"{stats['avg_score']:.3f} | {stats['avg_source_tokens']:.0f} | "
            f"{stats['avg_context_tokens']:.0f} | {stats['avg_answer_ms']:.0f} | "
            f"{stats['avg_judge_ms']:.0f} | {score_delta} | {rag_savings} | "
            f"{full_savings} | {stats['errors']} |"
        )

    lines.extend(
        [
            "",
            "## Failed Or Partial Cases",
            "",
        ]
    )
    misses = [row for row in rows if not row.get("passed")]
    if not misses:
        lines.append("- None")
    else:
        for row in misses:
            settings = row["settings"]
            lines.append(
                f"- `{row['id']}`: {row['verdict']} score={row['score']}; "
                f"context={settings['context_strategy']} top_k={settings['top_k']}; "
                f"{row['rationale']}"
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="write a baseline-relative matrix report")
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--rag-baseline", default="classic_chunks:top_k=25")
    parser.add_argument("--full-baseline", default="full_selected_docs:top_k=25")
    args = parser.parse_args(argv)
    write_report(
        rows_path=args.results,
        out_path=args.out,
        rag_baseline=args.rag_baseline,
        full_doc_baseline=args.full_baseline,
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
