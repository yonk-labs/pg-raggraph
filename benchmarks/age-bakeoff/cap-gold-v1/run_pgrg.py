#!/usr/bin/env python3
"""Run the pg-raggraph arms (METHODOLOGY §3-4).

Task A (issue-description retrieval): 6 arms x 3 seeds x 50 questions,
recall@{5,10,20} + recall_cited + target_hit@5, profile="raw", top_k=200
chunks deduped to parent cases. Latency on seed 42 (1 warmup + 3 timed
repeats per question), separately for profile="raw" and profile="balanced";
raw-vs-balanced ranking equality asserted on 5 questions.

Task B (citation lookup): naive, naive_boost, typed_traverse (#95
find_entities + traverse). The anchor case is removed from every ranked
list before scoring.

Writes results/results_pgrg.json.

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/run_pgrg.py \
        [--db-url postgresql://postgres:postgres@localhost:5434/pg_raggraph_capgold]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path

os.environ["PGRG_LLM_BASE_URL"] = ""  # no LLM may join the run

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RESULTS = HERE / "results"

SEEDS = [41, 42, 43]
LATENCY_SEED = 42
KS = [5, 10, 20]
TOP_K_CHUNKS = 200
TIMED_REPEATS = 3

ARMS_A = {
    "pgrg_naive": {"mode": "naive", "fusion": "linear"},
    "pgrg_naive_rrf": {"mode": "naive", "fusion": "rrf"},
    "pgrg_naive_boost": {"mode": "naive_boost"},
    "pgrg_local": {"mode": "local"},
    "pgrg_hybrid": {"mode": "hybrid", "fusion": "linear"},
    "pgrg_hybrid_rrf": {"mode": "hybrid", "fusion": "rrf"},
}
ARMS_B_QUERY = {
    "pgrg_naive": {"mode": "naive", "fusion": "linear"},
    "pgrg_naive_boost": {"mode": "naive_boost"},
}


def recall_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    return len(set(ranked[:k]) & gold) / len(gold) if gold else 0.0


def pctl(xs: list[float], p: float) -> float:
    return (
        statistics.quantiles(xs, n=100, method="inclusive")[int(p) - 1] if len(xs) > 1 else xs[0]
    )


def dedupe_to_cases(chunks) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for ch in chunks:
        src = ch.document_source or ""
        cid = src.removeprefix("case:")
        if cid and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def agg(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


async def query_ranked(rag, question: str, arm: dict, profile: str = "raw") -> list[str]:
    res = await rag.query(question, top_k=TOP_K_CHUNKS, profile=profile, **arm)
    return dedupe_to_cases(res.chunks)


async def task_a(rag, results: dict) -> None:
    for arm_name, arm in ARMS_A.items():
        per_seed: dict[str, dict] = {}
        for seed in SEEDS:
            gold_qs = json.load(open(DATA / f"gold_taskA_seed{seed}.json"))
            r_full = {k: [] for k in KS}
            r_cited = {k: [] for k in KS}
            target_hits = []
            min_cases = None
            for gq in gold_qs:
                ranked = await query_ranked(rag, gq["question"], arm)
                gold, cited = set(gq["gold"]), set(gq["gold_cited"])
                for k in KS:
                    r_full[k].append(recall_at_k(ranked, gold, k))
                    r_cited[k].append(recall_at_k(ranked, cited, k))
                target_hits.append(1.0 if gq["target_id"] in ranked[:5] else 0.0)
                n = len(ranked)
                min_cases = n if min_cases is None else min(min_cases, n)
            per_seed[str(seed)] = {
                "recall": {f"@{k}": agg(r_full[k]) for k in KS},
                "recall_cited": {f"@{k}": agg(r_cited[k]) for k in KS},
                "target_hit@5": agg(target_hits),
                "min_distinct_cases_returned": min_cases,
            }
            print(f"  {arm_name} seed {seed}: {per_seed[str(seed)]['recall']}", flush=True)
        results["taskA"][arm_name] = {"per_seed": per_seed}


async def latency_a(rag, results: dict) -> None:
    gold_qs = json.load(open(DATA / f"gold_taskA_seed{LATENCY_SEED}.json"))
    questions = [gq["question"] for gq in gold_qs]
    for profile in ("raw", "balanced"):
        for arm_name, arm in ARMS_A.items():
            for q in questions:  # warmup pass
                await rag.query(q, top_k=TOP_K_CHUNKS, profile=profile, **arm)
            wall, internal = [], []
            for q in questions:
                for _ in range(TIMED_REPEATS):
                    t0 = time.perf_counter()
                    res = await rag.query(q, top_k=TOP_K_CHUNKS, profile=profile, **arm)
                    wall.append((time.perf_counter() - t0) * 1000)
                    internal.append(res.latency_ms)
            results["latencyA"].setdefault(arm_name, {})[profile] = {
                "wall_p50": round(statistics.median(wall), 1),
                "wall_p95": round(pctl(wall, 95), 1),
                "internal_p50": round(statistics.median(internal), 1),
                "internal_p95": round(pctl(internal, 95), 1),
                "n": len(wall),
            }
            print(f"  latency {arm_name} [{profile}]: "
                  f"{results['latencyA'][arm_name][profile]}", flush=True)

    # ranking equality raw vs balanced on 5 questions, naive arm (§4)
    mismatches = 0
    for q in questions[:5]:
        r_raw = await query_ranked(rag, q, ARMS_A["pgrg_naive"], profile="raw")
        r_bal = await query_ranked(rag, q, ARMS_A["pgrg_naive"], profile="balanced")
        if r_raw[:20] != r_bal[:20]:
            mismatches += 1
    results["latencyA"]["raw_vs_balanced_ranking_mismatches_of_5"] = mismatches


async def task_b(rag, results: dict, ent_name_to_id: dict[str, str]) -> None:
    for seed in SEEDS:
        gold_qs = json.load(open(DATA / f"gold_taskB_seed{seed}.json"))

        # query-path arms
        for arm_name, arm in ARMS_B_QUERY.items():
            r = {k: [] for k in KS}
            for gq in gold_qs:
                ranked = await query_ranked(rag, gq["question"], arm)
                ranked = [c for c in ranked if c != gq["target_id"]]  # anchor removed
                for k in KS:
                    r[k].append(recall_at_k(ranked, set(gq["gold"]), k))
            results["taskB"].setdefault(arm_name, {"per_seed": {}})["per_seed"][str(seed)] = {
                "recall": {f"@{k}": agg(r[k]) for k in KS}
            }
            print(f"  taskB {arm_name} seed {seed}: "
                  f"{results['taskB'][arm_name]['per_seed'][str(seed)]}", flush=True)

        # typed_traverse (#95 primitives)
        r = {k: [] for k in KS}
        anchor_misses = 0
        for gq in gold_qs:
            ranked = await traverse_ranked(rag, gq["target_caption"], ent_name_to_id)
            if ranked is None:
                anchor_misses += 1
                ranked = []
            ranked = [c for c in ranked if c != gq["target_id"]]
            for k in KS:
                r[k].append(recall_at_k(ranked, set(gq["gold"]), k))
        results["taskB"].setdefault("pgrg_typed_traverse", {"per_seed": {}})["per_seed"][
            str(seed)
        ] = {
            "recall": {f"@{k}": agg(r[k]) for k in KS},
            "anchor_misses": anchor_misses,
        }
        print(f"  taskB pgrg_typed_traverse seed {seed}: "
              f"{results['taskB']['pgrg_typed_traverse']['per_seed'][str(seed)]}", flush=True)


async def traverse_ranked(rag, caption: str, ent_name_to_id: dict[str, str]) -> list[str] | None:
    matches = await rag.find_entities(caption, entity_type="case", limit=1)
    if not matches:
        return None
    hops = await rag.traverse(
        [matches[0].id], rel_types=["CITES"], direction="out", max_hops=1, limit=200
    )
    out: list[str] = []
    seen: set[str] = set()
    for h in hops:
        cid = ent_name_to_id.get(h.name)
        if cid and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


async def latency_b(rag, results: dict, ent_name_to_id: dict[str, str]) -> None:
    gold_qs = json.load(open(DATA / f"gold_taskB_seed{LATENCY_SEED}.json"))
    for arm_name, arm in ARMS_B_QUERY.items():
        for gq in gold_qs:
            await rag.query(gq["question"], top_k=TOP_K_CHUNKS, profile="raw", **arm)
        wall = []
        for gq in gold_qs:
            for _ in range(TIMED_REPEATS):
                t0 = time.perf_counter()
                await rag.query(gq["question"], top_k=TOP_K_CHUNKS, profile="raw", **arm)
                wall.append((time.perf_counter() - t0) * 1000)
        results["latencyB"][arm_name] = {
            "wall_p50": round(statistics.median(wall), 1),
            "wall_p95": round(pctl(wall, 95), 1),
            "n": len(wall),
        }
    for gq in gold_qs:  # warmup
        await traverse_ranked(rag, gq["target_caption"], ent_name_to_id)
    wall = []
    for gq in gold_qs:
        for _ in range(TIMED_REPEATS):
            t0 = time.perf_counter()
            await traverse_ranked(rag, gq["target_caption"], ent_name_to_id)
            wall.append((time.perf_counter() - t0) * 1000)
    results["latencyB"]["pgrg_typed_traverse"] = {
        "wall_p50": round(statistics.median(wall), 1),
        "wall_p95": round(pctl(wall, 95), 1),
        "n": len(wall),
    }
    print(f"  latencyB: {results['latencyB']}", flush=True)


async def run(args) -> None:
    from pg_raggraph import GraphRAG

    corpus = [json.loads(line) for line in open(DATA / "corpus.jsonl")]
    ent_name_to_id = {c["entity_name"]: c["id"] for c in corpus}

    rag = GraphRAG(dsn=args.db_url, skip_extraction=True)
    await rag.connect()
    results: dict = {"taskA": {}, "latencyA": {}, "taskB": {}, "latencyB": {}}
    t0 = time.time()
    try:
        await task_a(rag, results)
        await latency_a(rag, results)
        await task_b(rag, results, ent_name_to_id)
        await latency_b(rag, results, ent_name_to_id)
    finally:
        await rag.close()

    results["meta"] = {
        "seeds": SEEDS,
        "latency_seed": LATENCY_SEED,
        "k_values": KS,
        "top_k_chunks": TOP_K_CHUNKS,
        "timed_repeats": TIMED_REPEATS,
        "profile_recall": "raw",
        "embedder": "fastembed BAAI/bge-small-en-v1.5 (384-dim), inside timed loop",
        "wall_s_total": round(time.time() - t0, 1),
    }
    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / "results_pgrg.json", "w") as f:
        json.dump(results, f, indent=2)
    print("wrote", RESULTS / "results_pgrg.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--db-url", default="postgresql://postgres:postgres@localhost:5434/pg_raggraph_capgold"
    )
    args = ap.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
