#!/usr/bin/env python3
"""Run the AGE arm: composability probe, recall@k on the gold question,
latency over the latency question set.

Arms:
  vector_baseline        their Stage-1 vector query (the "40%" reference)
  pattern1               HorizonDB doc Pattern 1 (authority-boost RRF), adapted
  accelerator_norerank   their production function minus the azure_ml rerank

Also executes the AAT-002 composability probe: Microsoft's exact
cypher()-in-CTE + pgvector single-statement composition, in its verbatim
`AS (case_id TEXT, ref_id TEXT)` form, and records whether it runs as
published on stock Apache AGE 1.5.0.

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/horizondb-h2h/run_age.py \
        [--db-url ...] [--repeats 15] [--warmups 3]
Writes data/results_age.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import psycopg
import yaml

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
KS = [5, 10, 20, 30, 60]
K_MAX = 60

ARMS = {
    "vector_baseline": (HERE / "sql" / "vector_baseline.sql").read_text(),
    "pattern1": (HERE / "sql" / "pattern1_authority_boost.sql").read_text(),
    "accelerator_norerank": (HERE / "sql" / "accelerator_graphrag_norerank.sql").read_text(),
}

# AAT-002 probe: Microsoft's composition VERBATIM — ag_catalog.cypher() CTE
# with their `AS (case_id TEXT, ref_id TEXT)` column list, joined against a
# pgvector-ordered CTE, one statement. Structure lifted from
# get_vector_semantic_graphrag_optimized (graph_query + vector CTEs).
PROBE_VERBATIM = """
WITH vector_stage AS (
    SELECT id, RANK() OVER (ORDER BY description_vector <=> %(qvec)s::vector) AS vector_rank
    FROM cases_updated
    ORDER BY description_vector <=> %(qvec)s::vector
    LIMIT 10
),
graph_query AS (
    SELECT * FROM ag_catalog.cypher('case_graph',
        $$ MATCH (s)-[r:REF]->(n) RETURN n.case_id AS case_id, s.case_id AS ref_id $$
    ) AS (case_id TEXT, ref_id TEXT)
)
SELECT v.id, v.vector_rank, count(g.ref_id) AS refs
FROM vector_stage v
LEFT JOIN graph_query g ON v.id = g.case_id
GROUP BY v.id, v.vector_rank
ORDER BY v.vector_rank;
"""


def recall_at_k(ranked_ids: list[str], gold: set[str], k: int) -> float:
    return len(set(ranked_ids[:k]) & gold) / len(gold) if gold else 0.0


def pctl(xs: list[float], p: float) -> float:
    return (
        statistics.quantiles(xs, n=100, method="inclusive")[int(p) - 1] if len(xs) > 1 else xs[0]
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-url", default="postgresql://postgres:postgres@localhost:5440/h2h_age")
    ap.add_argument("--repeats", type=int, default=15)
    ap.add_argument("--warmups", type=int, default=3)
    args = ap.parse_args()

    gold = json.load(open(DATA / "gold.json"))
    questions = yaml.safe_load(open(HERE / "questions.yaml"))
    gold_q = questions["gold_question"]
    latency_qs = questions["latency_questions"]

    print("embedding questions with fastembed bge-small-en-v1.5 ...")
    from fastembed import TextEmbedding

    model = TextEmbedding("BAAI/bge-small-en-v1.5")
    all_qs = [gold_q] + [q for q in latency_qs if q != gold_q]
    qvecs = {q: json.dumps([float(x) for x in e]) for q, e in zip(all_qs, model.embed(all_qs))}

    results: dict = {"arms": {}, "composability_probe": {}}

    with psycopg.connect(args.db_url, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute('SET search_path = ag_catalog, "$user", public;')

        # ---- AAT-002 composability probe ----
        probe: dict = {
            "sql_form": "cypher() AS (case_id TEXT, ref_id TEXT) + pgvector CTE, single statement"
        }
        try:
            cur.execute(PROBE_VERBATIM, {"qvec": qvecs[gold_q]})
            rows = cur.fetchall()
            n_with_refs = sum(1 for r in rows if r[2] > 0)
            probe["executed"] = True
            probe["rows"] = len(rows)
            probe["rows_with_refs"] = n_with_refs
            probe["note"] = (
                "single-statement cypher()+pgvector composition executed; "
                f"{n_with_refs}/{len(rows)} vector hits joined to graph refs "
                "(0 would indicate the TEXT-cast join silently mismatching quoted agtype strings)"
            )
        except Exception as e:  # noqa: BLE001 — record the failure verbatim
            probe["executed"] = False
            probe["error"] = f"{type(e).__name__}: {e}"
        results["composability_probe"] = probe
        print("composability probe:", json.dumps(probe, indent=2))

        # ---- recall + latency per arm ----
        for arm, sql in ARMS.items():
            params_gold = {"qvec": qvecs[gold_q], "k": K_MAX}
            for _ in range(args.warmups):
                cur.execute(sql, params_gold)
                cur.fetchall()

            lat_gold, ranked = [], []
            for _ in range(args.repeats):
                t0 = time.perf_counter()
                cur.execute(sql, params_gold)
                rows = cur.fetchall()
                lat_gold.append((time.perf_counter() - t0) * 1000)
            # ranked ids from the last run; column 0 is id in vector_baseline/
            # pattern1, column 5 in accelerator_norerank (matches its SELECT)
            id_col = 5 if arm == "accelerator_norerank" else 0
            ranked = [str(r[id_col]) for r in rows]

            lat_all = []
            for q in latency_qs:
                p = {"qvec": qvecs[q], "k": K_MAX}
                cur.execute(sql, p)  # warmup
                cur.fetchall()
                for _ in range(5):
                    t0 = time.perf_counter()
                    cur.execute(sql, p)
                    cur.fetchall()
                    lat_all.append((time.perf_counter() - t0) * 1000)

            arm_res = {
                "ranked_ids_top60": ranked,
                "recall": {
                    gs: {f"@{k}": round(recall_at_k(ranked, set(gold[gs]), k), 4) for k in KS}
                    for gs in ("gold_strict", "gold_plus")
                },
                "latency_ms": {
                    "gold_question_p50": round(statistics.median(lat_gold), 2),
                    "gold_question_p95": round(pctl(lat_gold, 95), 2),
                    "all_questions_p50": round(statistics.median(lat_all), 2),
                    "all_questions_p95": round(pctl(lat_all, 95), 2),
                    "n_gold": len(lat_gold),
                    "n_all": len(lat_all),
                },
            }
            results["arms"][arm] = arm_res
            print(f"\n=== {arm} ===")
            print(
                json.dumps({k: v for k, v in arm_res.items() if k != "ranked_ids_top60"}, indent=2)
            )

    results["meta"] = {
        "repeats": args.repeats,
        "warmups": args.warmups,
        "k_values": KS,
        "engine": "Apache AGE 1.5.0 + pgvector 0.8.0, PG16 (docker)",
        "embedder": "fastembed BAAI/bge-small-en-v1.5 (384-dim), same as pgrg arm",
        "caveat": "single question with gold labels (N=1), single seed, single machine — preliminary",
    }
    with open(DATA / "results_age.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nwrote", DATA / "results_age.json")


if __name__ == "__main__":
    main()
