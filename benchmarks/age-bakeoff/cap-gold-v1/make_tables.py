#!/usr/bin/env python3
"""Render RESULTS.md tables from results/results_pgrg.json + results_age.json.

Mean ± half-range across seeds (3 seeds = range, not a CI — labeled as such
in RESULTS.md). Prints markdown to stdout; RESULTS.md quotes it verbatim.

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/make_tables.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
KS = [5, 10, 20]


def mr(vals: list[float]) -> str:
    m = sum(vals) / len(vals)
    half = (max(vals) - min(vals)) / 2
    return f"{m:.3f} ±{half:.3f}"


def recall_row(arm: str, per_seed: dict, key: str) -> str:
    cells = []
    for k in KS:
        vals = [per_seed[s][key][f"@{k}"] for s in sorted(per_seed)]
        cells.append(mr(vals))
    return f"| {arm} | " + " | ".join(cells) + " |"


def main() -> None:
    pgrg = json.load(open(RES / "results_pgrg.json"))
    age = json.load(open(RES / "results_age.json"))

    arms_a = {
        **{a: d["per_seed"] for a, d in age["taskA"].items()},
        **{a: d["per_seed"] for a, d in pgrg["taskA"].items()},
    }

    print("### Task A — recall (gold = target + in-corpus citations)\n")
    print("| arm | R@5 | R@10 | R@20 |")
    print("|---|---|---|---|")
    for arm, ps in arms_a.items():
        print(recall_row(arm, ps, "recall"))

    print("\n### Task A — recall_cited (gold = citations only)\n")
    print("| arm | Rc@5 | Rc@10 | Rc@20 |")
    print("|---|---|---|---|")
    for arm, ps in arms_a.items():
        print(recall_row(arm, ps, "recall_cited"))

    print("\n### Task A — target_hit@5 diagnostic\n")
    print("| arm | target_hit@5 |")
    print("|---|---|")
    for arm, ps in arms_a.items():
        vals = [ps[s]["target_hit@5"] for s in sorted(ps)]
        print(f"| {arm} | {mr(vals)} |")

    print("\n### Task A — latency (seed 42, 150 timed samples/arm, embed inside loop)\n")
    print("| arm | wall p50 | wall p95 | internal p50 | internal p95 |")
    print("|---|---|---|---|---|")
    for arm, d in age["latencyA"].items():
        print(f"| {arm} (SQL) | {d['wall_p50']} | {d['wall_p95']} | — | — |")
    for arm, d in pgrg["latencyA"].items():
        if not isinstance(d, dict) or "raw" not in d:
            continue
        r, b = d["raw"], d["balanced"]
        print(
            f"| {arm} (raw) | {r['wall_p50']} | {r['wall_p95']} | "
            f"{r['internal_p50']} | {r['internal_p95']} |"
        )
        print(
            f"| {arm} (balanced) | {b['wall_p50']} | {b['wall_p95']} | "
            f"{b['internal_p50']} | {b['internal_p95']} |"
        )
    print(
        f"\nraw-vs-balanced ranking mismatches (5 checked): "
        f"{pgrg['latencyA'].get('raw_vs_balanced_ranking_mismatches_of_5')}"
    )

    arms_b = {
        **{a: d["per_seed"] for a, d in age["taskB"].items()},
        **{a: d["per_seed"] for a, d in pgrg["taskB"].items()},
    }
    print("\n### Task B — citation lookup (gold = citations only, anchor removed)\n")
    print("| arm | R@5 | R@10 | R@20 | anchor misses (per seed) |")
    print("|---|---|---|---|---|")
    for arm, ps in arms_b.items():
        cells = []
        for k in KS:
            vals = [ps[s]["recall"][f"@{k}"] for s in sorted(ps)]
            cells.append(mr(vals))
        misses = "/".join(str(ps[s].get("anchor_misses", "—")) for s in sorted(ps))
        print(f"| {arm} | " + " | ".join(cells) + f" | {misses} |")

    print("\n### Task B — latency (seed 42)\n")
    print("| arm | wall p50 | wall p95 |")
    print("|---|---|---|")
    for src in (age["latencyB"], pgrg["latencyB"]):
        for arm, d in src.items():
            print(f"| {arm} | {d['wall_p50']} | {d['wall_p95']} |")


if __name__ == "__main__":
    main()
