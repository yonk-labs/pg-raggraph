#!/usr/bin/env python3
"""Run the AGE arms (METHODOLOGY §3-4).

Task A: age_vector_baseline + age_pattern1 (Microsoft HorizonDB Pattern 1,
h2h-adapted SQL), 3 seeds x 50 questions, recall@{5,10,20} + recall_cited +
target_hit@5. Latency on seed 42 (1 warmup + 3 timed repeats/question) with
the question embedding computed INSIDE the timed loop (symmetric with the
pg-raggraph arm, whose query() embeds internally).

Task B: same two SQL arms (anchor removed before scoring) plus
age_cypher_traverse — anchor id via caption equality, then a 1-hop Cypher
REF walk.

Writes results/results_age.json.

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/run_age.py \
        [--db-url postgresql://postgres:postgres@localhost:5440/capgold_age]
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RESULTS = HERE / "results"

SEEDS = [41, 42, 43]
LATENCY_SEED = 42
KS = [5, 10, 20]
K_FETCH = 60  # candidate depth of their published SQL shapes
TIMED_REPEATS = 3

ARMS_SQL = {
    "age_vector_baseline": (HERE / "sql" / "vector_baseline.sql").read_text(),
    "age_pattern1": (HERE / "sql" / "pattern1_authority_boost.sql").read_text(),
}

CYPHER_TRAVERSE = """
SELECT trim(both '"' from g.ref_id::text) AS ref_id
FROM ag_catalog.cypher('case_graph', $$
    MATCH (s:case {case_id: "%s"})-[:REF]->(n)
    RETURN n.case_id
$$) AS g(ref_id agtype);
"""


def recall_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    return len(set(ranked[:k]) & gold) / len(gold) if gold else 0.0


def pctl(xs: list[float], p: float) -> float:
    return (
        statistics.quantiles(xs, n=100, method="inclusive")[int(p) - 1] if len(xs) > 1 else xs[0]
    )


def agg(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--db-url", default="postgresql://postgres:postgres@localhost:5440/capgold_age"
    )
    args = ap.parse_args()

    from fastembed import TextEmbedding

    model = TextEmbedding("BAAI/bge-small-en-v1.5")

    def embed_one(q: str) -> str:
        return json.dumps([float(x) for x in next(iter(model.embed([q])))])

    results: dict = {"taskA": {}, "latencyA": {}, "taskB": {}, "latencyB": {}}
    t_start = time.time()

    with psycopg.connect(args.db_url, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute('SET search_path = ag_catalog, "$user", public;')

        def ranked_for(sql: str, question: str) -> list[str]:
            cur.execute(sql, {"qvec": embed_one(question), "k": K_FETCH})
            return [str(r[0]) for r in cur.fetchall()]

        # ---- Task A ----
        for arm_name, sql in ARMS_SQL.items():
            per_seed: dict[str, dict] = {}
            for seed in SEEDS:
                gold_qs = json.load(open(DATA / f"gold_taskA_seed{seed}.json"))
                r_full = {k: [] for k in KS}
                r_cited = {k: [] for k in KS}
                target_hits = []
                for gq in gold_qs:
                    ranked = ranked_for(sql, gq["question"])
                    gold, cited = set(gq["gold"]), set(gq["gold_cited"])
                    for k in KS:
                        r_full[k].append(recall_at_k(ranked, gold, k))
                        r_cited[k].append(recall_at_k(ranked, cited, k))
                    target_hits.append(1.0 if gq["target_id"] in ranked[:5] else 0.0)
                per_seed[str(seed)] = {
                    "recall": {f"@{k}": agg(r_full[k]) for k in KS},
                    "recall_cited": {f"@{k}": agg(r_cited[k]) for k in KS},
                    "target_hit@5": agg(target_hits),
                }
                print(f"  {arm_name} seed {seed}: {per_seed[str(seed)]['recall']}", flush=True)
            results["taskA"][arm_name] = {"per_seed": per_seed}

        # ---- Task A latency (embed inside the timed loop) ----
        gold_qs = json.load(open(DATA / f"gold_taskA_seed{LATENCY_SEED}.json"))
        questions = [gq["question"] for gq in gold_qs]
        for arm_name, sql in ARMS_SQL.items():
            for q in questions:  # warmup pass
                ranked_for(sql, q)
            wall = []
            for q in questions:
                for _ in range(TIMED_REPEATS):
                    t0 = time.perf_counter()
                    ranked_for(sql, q)
                    wall.append((time.perf_counter() - t0) * 1000)
            results["latencyA"][arm_name] = {
                "wall_p50": round(statistics.median(wall), 1),
                "wall_p95": round(pctl(wall, 95), 1),
                "n": len(wall),
                "note": "embed inside timed loop (fastembed single-string) + SQL + fetch",
            }
            print(f"  latency {arm_name}: {results['latencyA'][arm_name]}", flush=True)

        # ---- Task B ----
        def traverse_ranked(caption: str) -> list[str] | None:
            cur.execute(
                "SELECT id FROM cases_updated WHERE data#>>'{name_abbreviation}' = %s LIMIT 1",
                (caption,),
            )
            row = cur.fetchone()
            if not row:
                return None
            assert str(row[0]).isdigit()
            cur.execute(CYPHER_TRAVERSE % row[0])
            seen: set[str] = set()
            out: list[str] = []
            for r in cur.fetchall():
                cid = str(r[0])
                if cid not in seen:
                    seen.add(cid)
                    out.append(cid)
            return out

        for seed in SEEDS:
            gold_qs = json.load(open(DATA / f"gold_taskB_seed{seed}.json"))
            for arm_name, sql in ARMS_SQL.items():
                r = {k: [] for k in KS}
                for gq in gold_qs:
                    ranked = [c for c in ranked_for(sql, gq["question"]) if c != gq["target_id"]]
                    for k in KS:
                        r[k].append(recall_at_k(ranked, set(gq["gold"]), k))
                results["taskB"].setdefault(arm_name, {"per_seed": {}})["per_seed"][str(seed)] = {
                    "recall": {f"@{k}": agg(r[k]) for k in KS}
                }
                print(
                    f"  taskB {arm_name} seed {seed}: "
                    f"{results['taskB'][arm_name]['per_seed'][str(seed)]}",
                    flush=True,
                )

            r = {k: [] for k in KS}
            anchor_misses = 0
            for gq in gold_qs:
                ranked = traverse_ranked(gq["target_caption"])
                if ranked is None:
                    anchor_misses += 1
                    ranked = []
                ranked = [c for c in ranked if c != gq["target_id"]]
                for k in KS:
                    r[k].append(recall_at_k(ranked, set(gq["gold"]), k))
            results["taskB"].setdefault("age_cypher_traverse", {"per_seed": {}})["per_seed"][
                str(seed)
            ] = {"recall": {f"@{k}": agg(r[k]) for k in KS}, "anchor_misses": anchor_misses}
            print(
                f"  taskB age_cypher_traverse seed {seed}: "
                f"{results['taskB']['age_cypher_traverse']['per_seed'][str(seed)]}",
                flush=True,
            )

        # ---- Task B latency ----
        gold_qs = json.load(open(DATA / f"gold_taskB_seed{LATENCY_SEED}.json"))
        for arm_name, sql in ARMS_SQL.items():
            for gq in gold_qs:
                ranked_for(sql, gq["question"])
            wall = []
            for gq in gold_qs:
                for _ in range(TIMED_REPEATS):
                    t0 = time.perf_counter()
                    ranked_for(sql, gq["question"])
                    wall.append((time.perf_counter() - t0) * 1000)
            results["latencyB"][arm_name] = {
                "wall_p50": round(statistics.median(wall), 1),
                "wall_p95": round(pctl(wall, 95), 1),
                "n": len(wall),
            }
        for gq in gold_qs:
            traverse_ranked(gq["target_caption"])
        wall = []
        for gq in gold_qs:
            for _ in range(TIMED_REPEATS):
                t0 = time.perf_counter()
                traverse_ranked(gq["target_caption"])
                wall.append((time.perf_counter() - t0) * 1000)
        results["latencyB"]["age_cypher_traverse"] = {
            "wall_p50": round(statistics.median(wall), 1),
            "wall_p95": round(pctl(wall, 95), 1),
            "n": len(wall),
        }
        print(f"  latencyB: {results['latencyB']}", flush=True)

    results["meta"] = {
        "seeds": SEEDS,
        "latency_seed": LATENCY_SEED,
        "k_values": KS,
        "k_fetch": K_FETCH,
        "timed_repeats": TIMED_REPEATS,
        "engine": "Apache AGE 1.5.0 + pgvector, PG16 (docker, port 5440)",
        "embedder": "fastembed BAAI/bge-small-en-v1.5 (384-dim), inside timed loop",
        "hnsw_ef_search": (
            "stock default 40 (not raised): the LIMIT-60 vector stage returns 40 "
            "rows through the HNSW plan. Symmetric with pg-raggraph, whose config "
            "default is also ef_search=40. Recall is only reported to @20, within "
            "candidate depth for every arm."
        ),
        "wall_s_total": round(time.time() - t_start, 1),
    }
    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / "results_age.json", "w") as f:
        json.dump(results, f, indent=2)
    print("wrote", RESULTS / "results_age.json")


if __name__ == "__main__":
    main()
