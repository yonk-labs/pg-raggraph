#!/usr/bin/env python
"""Compare fp32 vs int8 factorial runs — speed + accuracy + retrieval rank.

Reads:
  results/diagnostics/factorial-probe-fp32.json
  results/diagnostics/factorial-probe-int8.json
  results/diagnostics/factorial-accuracy-fp32.json
  results/diagnostics/factorial-accuracy-int8.json

Writes:
  results/diagnostics/factorial-probe-COMPARE.md   (fp32 vs int8 per-cell)

For each of 12 (chunking, embedding) cells:
  - fully_correct delta (int8 − fp32) / 30
  - per-probe rank-of-first-gold delta
  - ingest wall time delta (if available from orchestrator logs)
  - aggregate "is int8 safe to ship as the default?" decision line
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"missing: {path}")
    return json.loads(path.read_text())


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    diag = root / "results" / "diagnostics"

    probe_fp32 = _load(diag / "factorial-probe-fp32.json")
    probe_int8 = _load(diag / "factorial-probe-int8.json")
    acc_fp32 = _load(diag / "factorial-accuracy-fp32.json")
    acc_int8 = _load(diag / "factorial-accuracy-int8.json")

    def _by_cell(data: dict) -> dict:
        return {(v["chunking"], v["embedding"]): v for v in data["variants"]}

    p32, p8 = _by_cell(probe_fp32), _by_cell(probe_int8)
    a32, a8 = _by_cell(acc_fp32), _by_cell(acc_int8)

    cells = sorted(set(a32) | set(a8))

    lines: list[str] = []
    lines.append("# fp32 vs int8 Factorial Comparison\n")
    lines.append(f"Accuracy wall time: fp32 {acc_fp32.get('wall_sec', '?')}s  |  int8 {acc_int8.get('wall_sec', '?')}s")
    lines.append(
        f"LLM cost: fp32 ${acc_fp32.get('cost_usd_total', 0):.4f}  |  "
        f"int8 ${acc_int8.get('cost_usd_total', 0):.4f}\n"
    )

    # TL;DR
    total_fc_32 = sum(a32[c]["fully_correct"] for c in cells if c in a32)
    total_fc_8 = sum(a8[c]["fully_correct"] for c in cells if c in a8)
    delta_total = total_fc_8 - total_fc_32
    lines.append("## TL;DR\n")
    lines.append(
        f"Total fully_correct across all 12 cells: fp32 = **{total_fc_32}**, "
        f"int8 = **{total_fc_8}**, delta = **{delta_total:+d}** out of 360.\n"
    )

    # Per-cell table
    lines.append("## Per-cell comparison (sorted by int8 fully_correct desc)\n")
    lines.append("| chunking | embedding | fp32 fc | int8 fc | Δfc | fp32 partial | int8 partial | fp32 avg_rank | int8 avg_rank |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    failing = ["scotus-q-004", "scotus-q-008", "scotus-q-025"]

    def _avg_rank(variant: dict) -> float:
        ranks = [variant["per_probe"][p]["rank_of_first_gold_chunk"] for p in failing]
        ranks_num = [r if r is not None else 10_000 for r in ranks]
        return sum(ranks_num) / len(ranks_num)

    def _fmt_rank(v: dict | None) -> str:
        return f"{_avg_rank(v):.1f}" if v else "?"

    rows = []
    for c in cells:
        if c not in a32 or c not in a8:
            continue
        v32, v8 = a32[c], a8[c]
        pv32, pv8 = p32.get(c), p8.get(c)
        fc32, fc8 = v32["fully_correct"], v8["fully_correct"]
        row = (
            fc8, c,
            f"| {c[0]} | {c[1]} | {fc32} | {fc8} | {fc8-fc32:+d} | "
            f"{v32['partially_correct']} | {v8['partially_correct']} | "
            f"{_fmt_rank(pv32)} | {_fmt_rank(pv8)} |"
        )
        rows.append(row)
    rows.sort(key=lambda r: -r[0])
    for _, _, line in rows:
        lines.append(line)

    # Decision line
    lines.append("\n## Decision\n")
    winner_fp32 = max(a32.values(), key=lambda v: v["fully_correct"])
    winner_int8 = max(a8.values(), key=lambda v: v["fully_correct"])
    lines.append(
        f"- fp32 best: **{winner_fp32['chunking']}/{winner_fp32['embedding']}** "
        f"({winner_fp32['fully_correct']}/30 fully_correct)"
    )
    lines.append(
        f"- int8 best: **{winner_int8['chunking']}/{winner_int8['embedding']}** "
        f"({winner_int8['fully_correct']}/30 fully_correct)"
    )
    delta_winner = winner_int8["fully_correct"] - winner_fp32["fully_correct"]
    if delta_winner >= 0:
        decision = f"INT8_SAFE_TO_SHIP  (int8 best >= fp32 best, Δ={delta_winner:+d})"
    elif delta_winner >= -2:
        decision = f"INT8_MARGINAL  (int8 best within 2 questions of fp32, Δ={delta_winner:+d}; ship-if-speed-matters)"
    else:
        decision = f"INT8_BLOCKED  (int8 best trails fp32 by {-delta_winner}+ questions; stay on fp32)"
    lines.append(f"\n**DECISION: {decision}**\n")

    out_path = root / "results" / "diagnostics" / "factorial-probe-COMPARE.md"
    out_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {out_path}", flush=True)
    print(f"Total delta: int8 {delta_total:+d} fully_correct vs fp32 across 12 cells", flush=True)
    print(f"Decision: {decision}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
