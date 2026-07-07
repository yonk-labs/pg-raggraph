#!/usr/bin/env python3
"""Run the pg-raggraph arm: recall@k on the gold question + latency.

Modes: naive (vector-only control), naive_boost, local, global, hybrid.
Chunk hits are deduplicated to their parent case (document_source
"case:<id>") in rank order, so recall@k is measured over CASES — the same
unit as the AGE arm (whose rows are cases).

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/horizondb-h2h/run_pgrg.py \
        [--db-url ...] [--repeats 15] [--warmups 3]
Writes data/results_pgrg.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
KS = [5, 10, 20, 30, 60]
MODES = ["naive", "naive_boost", "local", "global", "hybrid"]
# fetch enough chunks that >=60 distinct cases survive dedup (multiple
# chunks per case; 8000-char cases yield ~4-6 chunks each)
TOP_K_CHUNKS = 400


def recall_at_k(ranked_ids: list[str], gold: set[str], k: int) -> float:
    return len(set(ranked_ids[:k]) & gold) / len(gold) if gold else 0.0


def pctl(xs: list[float], p: float) -> float:
    return (
        statistics.quantiles(xs, n=100, method="inclusive")[int(p) - 1] if len(xs) > 1 else xs[0]
    )


def dedupe_to_cases(chunks) -> list[str]:
    seen, out = set(), []
    for ch in chunks:
        src = ch.document_source or ""
        cid = src.removeprefix("case:")
        if cid and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


async def run(args) -> None:
    from pg_raggraph import GraphRAG

    gold = json.load(open(DATA / "gold.json"))
    questions = yaml.safe_load(open(HERE / "questions.yaml"))
    gold_q = questions["gold_question"]
    latency_qs = questions["latency_questions"]

    rag = GraphRAG(dsn=args.db_url, skip_extraction=True)
    await rag.connect()
    results: dict = {"arms": {}}
    try:
        for mode in MODES:
            for _ in range(args.warmups):
                await rag.query(gold_q, mode=mode, top_k=TOP_K_CHUNKS)

            lat_gold, lat_gold_int = [], []
            res = None
            for _ in range(args.repeats):
                t0 = time.perf_counter()
                res = await rag.query(gold_q, mode=mode, top_k=TOP_K_CHUNKS)
                lat_gold.append((time.perf_counter() - t0) * 1000)
                lat_gold_int.append(res.latency_ms)
            ranked = dedupe_to_cases(res.chunks)

            lat_all, lat_all_int = [], []
            for q in latency_qs:
                await rag.query(q, mode=mode, top_k=TOP_K_CHUNKS)  # warmup
                for _ in range(5):
                    t0 = time.perf_counter()
                    r = await rag.query(q, mode=mode, top_k=TOP_K_CHUNKS)
                    lat_all.append((time.perf_counter() - t0) * 1000)
                    lat_all_int.append(r.latency_ms)

            arm_res = {
                "ranked_ids_top60": ranked[:60],
                "n_chunks_returned": len(res.chunks),
                "n_distinct_cases": len(ranked),
                "recall": {
                    gs: {f"@{k}": round(recall_at_k(ranked, set(gold[gs]), k), 4) for k in KS}
                    for gs in ("gold_strict", "gold_plus")
                },
                "latency_ms": {
                    "gold_question_p50": round(statistics.median(lat_gold), 2),
                    "gold_question_p95": round(pctl(lat_gold, 95), 2),
                    "all_questions_p50": round(statistics.median(lat_all), 2),
                    "all_questions_p95": round(pctl(lat_all, 95), 2),
                    # retrieval-internal timing (QueryResult.latency_ms) — the
                    # number comparable to timing raw SQL on the AGE arm
                    "internal_all_questions_p50": round(statistics.median(lat_all_int), 2),
                    "internal_all_questions_p95": round(pctl(lat_all_int, 95), 2),
                    "n_gold": len(lat_gold),
                    "n_all": len(lat_all),
                },
            }
            results["arms"][f"pgrg_{mode}"] = arm_res
            print(f"\n=== pgrg_{mode} ===")
            print(
                json.dumps({k: v for k, v in arm_res.items() if k != "ranked_ids_top60"}, indent=2)
            )
    finally:
        await rag.close()

    results["meta"] = {
        "repeats": args.repeats,
        "warmups": args.warmups,
        "k_values": KS,
        "top_k_chunks": TOP_K_CHUNKS,
        "engine": "pg-raggraph on pgvector/pgvector:pg16 (docker, port 5434)",
        "embedder": "fastembed BAAI/bge-small-en-v1.5 (384-dim), same as AGE arm",
        "latency_note": (
            "wall time around GraphRAG.query() — includes Python/library overhead, "
            "vs the AGE arm which times raw SQL execution client-side. This favors "
            "the AGE arm; both include one client-server round trip."
        ),
        "caveat": "single question with gold labels (N=1), single seed, single machine — preliminary",
    }
    with open(DATA / "results_pgrg.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nwrote", DATA / "results_pgrg.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--db-url", default="postgresql://postgres:postgres@localhost:5434/pg_raggraph_h2h"
    )
    ap.add_argument("--repeats", type=int, default=15)
    ap.add_argument("--warmups", type=int, default=3)
    args = ap.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
