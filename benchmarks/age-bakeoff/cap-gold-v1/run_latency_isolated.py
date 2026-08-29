#!/usr/bin/env python3
"""Engine-isolated Task B latency addendum (instrumentation of the existing
preregistered task — nothing new preregistered; see RESULTS.md addendum).

Removes the two disclosed asymmetries from the Task B latency table:
raw-SQL-vs-Python-API and exact-key-vs-trgm-bind. Every arm here is BARE SQL
via psycopg with the anchor's EXACT id resolved outside the timed loop:

  age_cypher_1hop / _2hop   MATCH (s:case {case_id})-[:REF]->(n) (/ *1..2)
  pgrg_cte_1hop / _2hop     the EXACT SQL GraphRAG.traverse() generates
                            (pg_raggraph.graph_join.build_traverse_sql), incl.
                            its per-edge provenance chunk_ids subquery + ORDER BY
  pgrg_cte_min_1hop / _2hop the engine floor: same recursive walk, identifiers
                            only (no provenance arrays, no entity join, no sort)
  pgrg_trgm_bind            the fuzzy caption->entity bind alone (the exact
                            find_entities SQL), quantifying what Task B's
                            anchor binding cost on top of traversal

Anchors: all 150 Task B targets (seeds 41/42/43). 1 warmup pass + 3 timed
repeats per anchor per arm -> 450 samples; p50/p95 ms. Writes
results/results_latency_isolated.json.

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/run_latency_isolated.py
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import psycopg

from pg_raggraph.graph_join import build_find_entities_sql, build_traverse_sql

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RESULTS = HERE / "results"

PGRG_DB = "postgresql://postgres:postgres@localhost:5434/pg_raggraph_capgold"
AGE_DB = "postgresql://postgres:postgres@localhost:5440/capgold_age"
NAMESPACE = "default"
REPEATS = 3

AGE_1HOP = """SELECT trim(both '"' from g.ref_id::text)
FROM ag_catalog.cypher('case_graph', $$
    MATCH (s:case {case_id: "%s"})-[:REF]->(n)
    RETURN n.case_id
$$) AS g(ref_id agtype);"""

AGE_2HOP = """SELECT trim(both '"' from g.ref_id::text)
FROM ag_catalog.cypher('case_graph', $$
    MATCH (s:case {case_id: "%s"})-[:REF*1..2]->(n)
    RETURN n.case_id
$$) AS g(ref_id agtype);"""

# Engine floor: the same recursive walk build_traverse_sql generates, minus
# the API SQL's provenance chunk_ids subquery, entity join, and ORDER BY —
# output parity with the AGE arm (identifiers per path only).
PGRG_MIN = """
WITH RECURSIVE walk AS (
    SELECT e.id AS entity_id, 0 AS depth, ARRAY[e.id] AS path
    FROM entities e
    WHERE e.id = ANY(%(entity_ids)s) AND e.namespace = %(namespace)s
    UNION ALL
    SELECT r.dst_id, w.depth + 1, w.path || r.dst_id
    FROM walk w
    JOIN relationships r ON r.src_id = w.entity_id
    WHERE w.depth < %(max_hops)s
      AND r.namespace = %(namespace)s
      AND NOT r.retracted
      AND upper(r.rel_type) = ANY(%(rel_types)s)
      AND NOT (r.dst_id = ANY(w.path))
)
SELECT entity_id, depth FROM walk WHERE depth > 0
"""


def pctl(xs: list[float], p: float) -> float:
    return statistics.quantiles(xs, n=100, method="inclusive")[int(p) - 1]


def timed(cur, run_one, anchors) -> dict:
    for a in anchors:  # warmup pass
        run_one(cur, a)
    wall: list[float] = []
    rows_total = 0
    for a in anchors:
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            rows_total += run_one(cur, a)
            wall.append((time.perf_counter() - t0) * 1000)
    return {
        "wall_p50": round(statistics.median(wall), 2),
        "wall_p95": round(pctl(wall, 95), 2),
        "n": len(wall),
        "mean_rows": round(rows_total / len(wall), 1),
    }


def main() -> None:
    anchors = []
    for seed in (41, 42, 43):
        for gq in json.load(open(DATA / f"gold_taskB_seed{seed}.json")):
            anchors.append({"case_id": gq["target_id"], "caption": gq["target_caption"]})
    corpus_name = {}
    for line in open(DATA / "corpus.jsonl"):
        c = json.loads(line)
        corpus_name[c["id"]] = c["entity_name"]

    results: dict = {"arms": {}}

    with psycopg.connect(PGRG_DB, autocommit=True) as pconn:
        pcur = pconn.cursor()
        # exact-id anchor resolution, OUTSIDE all timed loops
        for a in anchors:
            row = pcur.execute(
                "SELECT id FROM entities WHERE namespace = %s AND name = %s",
                (NAMESPACE, corpus_name[a["case_id"]]),
            ).fetchone()
            a["entity_id"] = row[0] if row else None
        missing = sum(1 for a in anchors if a["entity_id"] is None)
        # merged-away entities have no exact row; they are excluded from ALL
        # arms so every arm times the identical anchor set
        anchors = [a for a in anchors if a["entity_id"] is not None]
        results["anchors"] = {"n": len(anchors), "excluded_merged": missing}
        print(f"anchors: {len(anchors)} (excluded {missing} merged-away)")

        shipped = build_traverse_sql("out", typed=True)
        bind_sql = build_find_entities_sql(fuzzy=True, typed=True)

        def cte(hops):
            def run_one(cur, a):
                cur.execute(
                    shipped,
                    {
                        "entity_ids": [a["entity_id"]],
                        "namespace": NAMESPACE,
                        "rel_types": ["CITES"],
                        "max_hops": hops,
                        "limit": 10000,
                    },
                )
                return len(cur.fetchall())

            return run_one

        def cte_min(hops):
            def run_one(cur, a):
                cur.execute(
                    PGRG_MIN,
                    {
                        "entity_ids": [a["entity_id"]],
                        "namespace": NAMESPACE,
                        "rel_types": ["CITES"],
                        "max_hops": hops,
                    },
                )
                return len(cur.fetchall())

            return run_one

        def trgm_bind(cur, a):
            cur.execute(
                bind_sql,
                {
                    "namespace": NAMESPACE,
                    "name": a["caption"],  # unsuffixed caption -> fuzzy leg, as in Task B
                    "entity_type": "case",
                    "min_score": 0.3,
                    "limit": 5,
                },
            )
            return len(cur.fetchall())

        for name, fn in [
            ("pgrg_cte_1hop", cte(1)),
            ("pgrg_cte_2hop", cte(2)),
            ("pgrg_cte_min_1hop", cte_min(1)),
            ("pgrg_cte_min_2hop", cte_min(2)),
            ("pgrg_trgm_bind", trgm_bind),
        ]:
            results["arms"][name] = timed(pcur, fn, anchors)
            print(f"  {name}: {results['arms'][name]}", flush=True)

    with psycopg.connect(AGE_DB, autocommit=True) as aconn:
        acur = aconn.cursor()
        acur.execute('SET search_path = ag_catalog, "$user", public;')

        def age(sql):
            def run_one(cur, a):
                assert a["case_id"].isdigit()
                cur.execute(sql % a["case_id"])
                return len(cur.fetchall())

            return run_one

        for name, fn in [("age_cypher_1hop", age(AGE_1HOP)), ("age_cypher_2hop", age(AGE_2HOP))]:
            results["arms"][name] = timed(acur, fn, anchors)
            print(f"  {name}: {results['arms'][name]}", flush=True)

    # correctness cross-check (not timed): 1-hop id sets vs corpus citations
    corpus_cites = {}
    for line in open(DATA / "corpus.jsonl"):
        c = json.loads(line)
        corpus_cites[c["id"]] = set(c["cites_in_corpus"])
    with psycopg.connect(PGRG_DB) as pconn:
        pcur = pconn.cursor()
        name_to_case = {v: k for k, v in corpus_name.items()}
        pgrg_exact = age_exact = 0
        for a in anchors[:25]:
            pcur.execute(
                PGRG_MIN,
                {
                    "entity_ids": [a["entity_id"]],
                    "namespace": NAMESPACE,
                    "rel_types": ["CITES"],
                    "max_hops": 1,
                },
            )
            ids = [r[0] for r in pcur.fetchall()]
            pcur.execute("SELECT id, name FROM entities WHERE id = ANY(%s)", (ids,))
            got = {name_to_case.get(n) for _, n in pcur.fetchall()} - {None}
            pgrg_exact += got == corpus_cites[a["case_id"]]
    with psycopg.connect(AGE_DB) as aconn:
        acur = aconn.cursor()
        acur.execute('SET search_path = ag_catalog, "$user", public;')
        for a in anchors[:25]:
            acur.execute(AGE_1HOP % a["case_id"])
            got = {r[0] for r in acur.fetchall()}
            age_exact += got == corpus_cites[a["case_id"]]
    results["correctness_1hop_exact_of_25"] = {"pgrg": pgrg_exact, "age": age_exact}
    print("correctness:", results["correctness_1hop_exact_of_25"])

    results["meta"] = {
        "protocol": "150 Task B anchors (3 seeds), 1 warmup pass + 3 timed repeats/anchor",
        "isolation": "bare psycopg SQL both engines; exact anchor ids resolved outside timed loops",
        "pgrg_cte_source": "pg_raggraph.graph_join.build_traverse_sql('out', typed=True) verbatim",
        "limit_note": "shipped CTE run with limit=10000 (never binds at this fan-out; shipped default is 200)",
    }
    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / "results_latency_isolated.json", "w") as f:
        json.dump(results, f, indent=2)
    print("wrote", RESULTS / "results_latency_isolated.json")


if __name__ == "__main__":
    main()
