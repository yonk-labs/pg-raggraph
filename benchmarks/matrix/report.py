"""Summarize llm-judge matrix results into baseline-relative tables."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _group_key(row: dict[str, Any]) -> tuple[str, int]:
    settings = row["settings"]
    return (settings["context_strategy"], int(settings["top_k"]))


def _summarize(rows: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_group_key(row)].append(row)

    out: dict[tuple[str, int], dict[str, Any]] = {}
    for key, group in groups.items():
        n = len(group)
        out[key] = {
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


def write_report(
    *,
    rows_path: Path,
    out_path: Path,
    rag_baseline: tuple[str, int],
    full_doc_baseline: tuple[str, int],
) -> None:
    rows = _load_rows(rows_path)
    summary = _summarize(rows)
    rag = summary.get(rag_baseline)
    full = summary.get(full_doc_baseline)

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
        f"- Classic RAG baseline: `{rag_baseline[0]}` top_k={rag_baseline[1]}",
        f"- Full-document baseline: `{full_doc_baseline[0]}` top_k={full_doc_baseline[1]}",
        "",
        "## Top Configurations",
        "",
        "| rank | context strategy | top_k | n | pass rate | avg score | avg ctx tokens | token savings vs RAG | token savings vs full-doc |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, ((strategy, top_k), stats) in enumerate(ranked[:10], 1):
        rag_savings = _savings(
            stats["avg_context_tokens"], rag["avg_context_tokens"] if rag else 0
        )
        full_savings = _savings(
            stats["avg_context_tokens"], full["avg_context_tokens"] if full else 0
        )
        lines.append(
            f"| {idx} | {strategy} | {top_k} | {stats['n']} | "
            f"{_pct(stats['pass_rate'])} | {stats['avg_score']:.3f} | "
            f"{stats['avg_context_tokens']:.0f} | {rag_savings} | {full_savings} |"
        )

    lines.extend(
        [
            "",
            "## Full Table",
            "",
            "| context strategy | top_k | n | pass | avg score | avg source tokens | avg ctx tokens | answer ms | judge ms | score vs RAG | token savings vs RAG | token savings vs full-doc | errors |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for (strategy, top_k), stats in sorted(summary.items()):
        score_delta = _delta_pct(stats["avg_score"], rag["avg_score"] if rag else 0)
        rag_savings = _savings(
            stats["avg_context_tokens"], rag["avg_context_tokens"] if rag else 0
        )
        full_savings = _savings(
            stats["avg_context_tokens"], full["avg_context_tokens"] if full else 0
        )
        lines.append(
            f"| {strategy} | {top_k} | {stats['n']} | {stats['passed']}/{stats['n']} | "
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
    parser.add_argument("--rag-baseline", default="classic_chunks:25")
    parser.add_argument("--full-baseline", default="full_selected_docs:25")
    args = parser.parse_args(argv)
    write_report(
        rows_path=args.results,
        out_path=args.out,
        rag_baseline=_parse_baseline(args.rag_baseline),
        full_doc_baseline=_parse_baseline(args.full_baseline),
    )
    print(f"wrote {args.out}")


def _parse_baseline(value: str) -> tuple[str, int]:
    strategy, top_k = value.rsplit(":", 1)
    return strategy, int(top_k)


if __name__ == "__main__":
    main()
