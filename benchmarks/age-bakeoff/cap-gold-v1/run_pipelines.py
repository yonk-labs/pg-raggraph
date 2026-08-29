#!/usr/bin/env python3
"""Addendum 2 — pipeline latency (instrumentation of the preregistered
corpus; NO new accuracy claims). Tables + framing: PIPELINES.md.

Tier 1  traversal depth sweep 1/2/3 hops, engine-isolated (bare SQL, exact
        anchor ids outside timed loops), 149 Task B anchors.
Tier 2  realistic RAG pipeline (vector seed -> entity collect -> typed
        expansion -> re-scored chunks/cases): single-statement bare SQL in
        both engines + the pg-raggraph API wall (mode local / naive_boost).
Tier 3  composed analytical slice (semantic seed -> 2-hop expansion ->
        citation authority -> year filter -> RRF -> top 10 w/ provenance):
        single-statement both engines, plus a 2-statement targeted-VLE AGE
        variant. statements-per-query is reported as a column.

Timeouts (30 s statement_timeout, both engines) are RESULTS, not hidden:
a timed-out warmup marks the anchor/question skipped-for-repeats and is
counted. Writes results/results_pipelines.json.

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/run_pipelines.py
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from pathlib import Path

os.environ["PGRG_LLM_BASE_URL"] = ""

import psycopg

from pg_raggraph.graph_join import build_traverse_sql

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RESULTS = HERE / "results"

PGRG_DB = "postgresql://postgres:postgres@localhost:5434/pg_raggraph_capgold"
AGE_DB = "postgresql://postgres:postgres@localhost:5440/capgold_age"
NS = "default"
REPEATS = 3
TIMEOUT_MS = 30_000
YEAR_MIN = "1960"  # tier-3 structured predicate: decisions from 1960 on
RRF_K = 60  # same constant Microsoft Pattern 1 uses


def pctl(xs, p):
    return statistics.quantiles(xs, n=100, method="inclusive")[int(p) - 1]


def timed(cur, run_one, items) -> dict:
    """1 warmup pass + REPEATS timed. Warmup timeout => item skipped, counted."""
    skip, timeouts = set(), 0
    for i, it in enumerate(items):
        try:
            run_one(cur, it)
        except psycopg.errors.QueryCanceled:
            skip.add(i)
            timeouts += 1
    wall, rows_total, n_rows = [], 0, 0
    for i, it in enumerate(items):
        if i in skip:
            continue
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            try:
                rows = run_one(cur, it)
            except psycopg.errors.QueryCanceled:
                timeouts += 1
                continue
            wall.append((time.perf_counter() - t0) * 1000)
            rows_total += rows
            n_rows += 1
    out = {"n": len(wall), "timeouts": timeouts, "skipped_items": len(skip)}
    if wall:
        out |= {
            "wall_p50": round(statistics.median(wall), 2),
            "wall_p95": round(pctl(wall, 95), 2) if len(wall) > 1 else round(wall[0], 2),
            "mean_rows": round(rows_total / n_rows, 1),
        }
    return out


# ---------------------------------------------------------------- tier 1

AGE_VLE = """SELECT trim(both '"' from g.ref_id::text)
FROM ag_catalog.cypher('case_graph', $$
    MATCH (s:case {case_id: "%s"})-[:REF*1..%d]->(n)
    RETURN n.case_id
$$) AS g(ref_id agtype);"""

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


def tier1(results, anchors):
    shipped = build_traverse_sql("out", typed=True)
    with psycopg.connect(PGRG_DB, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        for hops in (1, 2, 3):
            for label, sql in (("pgrg_cte", shipped), ("pgrg_cte_min", PGRG_MIN)):
                params = {
                    "namespace": NS,
                    "rel_types": ["CITES"],
                    "max_hops": hops,
                    "limit": 100_000,
                }

                def run_one(cur, a, sql=sql, params=params):
                    cur.execute(sql, params | {"entity_ids": [a["entity_id"]]})
                    return len(cur.fetchall())

                results["tier1"][f"{label}_{hops}hop"] = timed(cur, run_one, anchors)
                print(
                    f"  tier1 {label}_{hops}hop:",
                    results["tier1"][f"{label}_{hops}hop"],
                    flush=True,
                )
    with psycopg.connect(AGE_DB, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute('SET search_path = ag_catalog, "$user", public;')
        cur.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        for hops in (1, 2, 3):

            def run_one(cur, a, hops=hops):
                cur.execute(AGE_VLE % (a["case_id"], hops))
                return len(cur.fetchall())

            results["tier1"][f"age_cypher_{hops}hop"] = timed(cur, run_one, anchors)
            print(
                f"  tier1 age_cypher_{hops}hop:",
                results["tier1"][f"age_cypher_{hops}hop"],
                flush=True,
            )


# ---------------------------------------------------------------- tier 2


# ponytail: fixed-depth SET expansion (UNION joins), not per-path recursion —
# the pipeline wants the neighborhood as a set; per-path costs are Tier 1.
def pgrg_pipeline_sql(hops: int) -> str:
    hop1 = """SELECT DISTINCT r.dst_id AS entity_id
        FROM relationships r JOIN seed_entities se ON r.src_id = se.entity_id
        WHERE r.namespace = %(ns)s AND NOT r.retracted AND upper(r.rel_type) = 'CITES'"""
    hop2 = """SELECT DISTINCT r2.dst_id
        FROM relationships r2 JOIN hop1 h ON r2.src_id = h.entity_id
        WHERE r2.namespace = %(ns)s AND NOT r2.retracted AND upper(r2.rel_type) = 'CITES'"""
    hood = "SELECT entity_id FROM seed_entities UNION SELECT entity_id FROM hop1"
    if hops == 2:
        hood += " UNION SELECT dst_id FROM hop2"
    return f"""
WITH seeds AS (
    SELECT c.id AS chunk_id
    FROM chunks c
    ORDER BY c.embedding <=> %(qvec)s::vector
    LIMIT 60
),
seed_entities AS (
    SELECT DISTINCT ec.entity_id
    FROM seeds s
    JOIN entity_chunks ec ON ec.chunk_id = s.chunk_id
    JOIN entities e ON e.id = ec.entity_id AND e.entity_type = 'case'
),
hop1 AS ({hop1}),
{"hop2 AS (" + hop2 + ")," if hops == 2 else ""}
hood AS ({hood}),
hood_chunks AS (
    SELECT DISTINCT ec.chunk_id
    FROM hood h JOIN entity_chunks ec ON ec.entity_id = h.entity_id
)
SELECT c.id, c.document_id, c.embedding <=> %(qvec)s::vector AS dist
FROM hood_chunks hc JOIN chunks c ON c.id = hc.chunk_id
ORDER BY dist
LIMIT 20
"""


def age_pipeline_sql(hops: int) -> str:
    hood = "SELECT id FROM seeds UNION SELECT dst FROM hop1"
    if hops == 2:
        hood += " UNION SELECT e2.dst FROM edges e2 JOIN hop1 h ON e2.src = h.dst"
    return f"""
WITH seeds AS (
    SELECT id
    FROM cases_updated
    ORDER BY description_vector <=> %(qvec)s::vector
    LIMIT 60
),
edges AS (
    SELECT trim(both '"' from a.src::text) AS src, trim(both '"' from a.dst::text) AS dst
    FROM ag_catalog.cypher('case_graph',
        $$ MATCH (s:case)-[:REF]->(n) RETURN s.case_id, n.case_id $$
    ) AS a(src agtype, dst agtype)
),
hop1 AS (
    SELECT DISTINCT e.dst FROM edges e JOIN seeds s ON e.src = s.id
),
hood AS ({hood})
SELECT cu.id, cu.description_vector <=> %(qvec)s::vector AS dist
FROM hood h JOIN cases_updated cu ON cu.id = h.id
ORDER BY dist
LIMIT 20
"""


def tier2_sql(results, qvecs):
    with psycopg.connect(PGRG_DB, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        for hops in (1, 2):
            sql = pgrg_pipeline_sql(hops)

            def run_one(cur, qv, sql=sql):
                cur.execute(sql, {"qvec": qv, "ns": NS})
                return len(cur.fetchall())

            results["tier2"][f"pgrg_sql_{hops}hop"] = timed(cur, run_one, qvecs)
            print(
                f"  tier2 pgrg_sql_{hops}hop:", results["tier2"][f"pgrg_sql_{hops}hop"], flush=True
            )
    with psycopg.connect(AGE_DB, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute('SET search_path = ag_catalog, "$user", public;')
        cur.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        for hops in (1, 2):
            sql = age_pipeline_sql(hops)

            def run_one(cur, qv, sql=sql):
                cur.execute(sql, {"qvec": qv})
                return len(cur.fetchall())

            results["tier2"][f"age_sql_{hops}hop"] = timed(cur, run_one, qvecs)
            print(
                f"  tier2 age_sql_{hops}hop:", results["tier2"][f"age_sql_{hops}hop"], flush=True
            )


async def tier2_api(results, questions):
    from pg_raggraph import GraphRAG

    rag = GraphRAG(dsn=PGRG_DB, skip_extraction=True)
    await rag.connect()
    try:
        for mode in ("naive_boost", "local"):
            for q in questions:  # warmup
                await rag.query(q, mode=mode, top_k=200, profile="raw")
            wall = []
            for q in questions:
                for _ in range(REPEATS):
                    t0 = time.perf_counter()
                    await rag.query(q, mode=mode, top_k=200, profile="raw")
                    wall.append((time.perf_counter() - t0) * 1000)
            results["tier2"][f"pgrg_api_{mode}"] = {
                "wall_p50": round(statistics.median(wall), 2),
                "wall_p95": round(pctl(wall, 95), 2),
                "n": len(wall),
                "note": "full Python API, profile=raw, top_k=200, embedding INSIDE loop",
            }
            print(f"  tier2 pgrg_api_{mode}:", results["tier2"][f"pgrg_api_{mode}"], flush=True)
    finally:
        await rag.close()


# ---------------------------------------------------------------- tier 3

PGRG_TIER3 = """
WITH seeds AS (
    SELECT c.id AS chunk_id, c.embedding <=> %(qvec)s::vector AS dist
    FROM chunks c
    ORDER BY c.embedding <=> %(qvec)s::vector
    LIMIT 60
),
seed_entities AS (
    SELECT DISTINCT ec.entity_id
    FROM seeds s
    JOIN entity_chunks ec ON ec.chunk_id = s.chunk_id
    JOIN entities e ON e.id = ec.entity_id AND e.entity_type = 'case'
),
hop1 AS (
    SELECT DISTINCT r.dst_id AS entity_id
    FROM relationships r JOIN seed_entities se ON r.src_id = se.entity_id
    WHERE r.namespace = %(ns)s AND NOT r.retracted AND upper(r.rel_type) = 'CITES'
),
hop2 AS (
    SELECT DISTINCT r.dst_id AS entity_id
    FROM relationships r JOIN hop1 h ON r.src_id = h.entity_id
    WHERE r.namespace = %(ns)s AND NOT r.retracted AND upper(r.rel_type) = 'CITES'
),
hood AS (
    SELECT entity_id FROM seed_entities
    UNION SELECT entity_id FROM hop1
    UNION SELECT entity_id FROM hop2
),
authority AS (  -- targeted in-degree: indexed on relationships(dst_id, rel_type)
    SELECT h.entity_id, count(r.id) AS cite_count
    FROM hood h
    LEFT JOIN relationships r
      ON r.dst_id = h.entity_id AND upper(r.rel_type) = 'CITES'
     AND r.namespace = %(ns)s AND NOT r.retracted
    GROUP BY h.entity_id
),
cand AS (
    SELECT DISTINCT ON (c.id) c.id AS chunk_id, c.document_id,
           d.metadata->>'case_id' AS case_id,
           c.embedding <=> %(qvec)s::vector AS dist,
           a.cite_count
    FROM hood h
    JOIN entity_chunks ec ON ec.entity_id = h.entity_id
    JOIN authority a ON a.entity_id = h.entity_id
    JOIN chunks c ON c.id = ec.chunk_id
    JOIN documents d ON d.id = c.document_id
    WHERE left(d.metadata->>'decision_date', 4) >= %(year_min)s
    ORDER BY c.id, a.cite_count DESC
)
SELECT chunk_id, document_id, case_id, dist, cite_count,
       1.0 / (%(rrf_k)s + RANK() OVER (ORDER BY dist)) +
       1.0 / (%(rrf_k)s + RANK() OVER (ORDER BY cite_count DESC)) AS rrf
FROM cand
ORDER BY rrf DESC
LIMIT 10
"""

AGE_TIER3_1STMT = """
WITH seeds AS (
    SELECT id, description_vector <=> %(qvec)s::vector AS dist
    FROM cases_updated
    ORDER BY description_vector <=> %(qvec)s::vector
    LIMIT 60
),
edges AS (
    SELECT trim(both '"' from a.src::text) AS src, trim(both '"' from a.dst::text) AS dst
    FROM ag_catalog.cypher('case_graph',
        $$ MATCH (s:case)-[:REF]->(n) RETURN s.case_id, n.case_id $$
    ) AS a(src agtype, dst agtype)
),
hop1 AS (SELECT DISTINCT e.dst FROM edges e JOIN seeds s ON e.src = s.id),
hop2 AS (SELECT DISTINCT e.dst FROM edges e JOIN hop1 h ON e.src = h.dst),
hood AS (
    SELECT id FROM seeds UNION SELECT dst FROM hop1 UNION SELECT dst FROM hop2
),
authority AS (  -- in-degree from the same edge dump
    SELECT h.id, count(e.src) AS cite_count
    FROM hood h LEFT JOIN edges e ON e.dst = h.id
    GROUP BY h.id
),
cand AS (
    SELECT cu.id, cu.description_vector <=> %(qvec)s::vector AS dist, a.cite_count
    FROM hood h
    JOIN cases_updated cu ON cu.id = h.id
    JOIN authority a ON a.id = h.id
    WHERE left(cu.data->>'decision_date', 4) >= %(year_min)s
)
SELECT id, dist, cite_count,
       1.0 / (%(rrf_k)s + RANK() OVER (ORDER BY dist)) +
       1.0 / (%(rrf_k)s + RANK() OVER (ORDER BY cite_count DESC)) AS rrf
FROM cand
ORDER BY rrf DESC
LIMIT 10
"""

# 2-statement targeted variant: stmt 1 fetches seed ids; stmt 2 string-builds
# a targeted VLE from those literal ids (cypher() cannot consume dynamic seeds
# from a CTE — the composability limit this column measures) and finishes
# relationally; authority still needs the edge dump (no targeted in-degree in
# one cypher call over a dynamic set).
AGE_TIER3_STMT2 = """
WITH expanded AS (
    SELECT DISTINCT trim(both '"' from g.dst::text) AS id
    FROM ag_catalog.cypher('case_graph', $$
        MATCH (s:case)-[:REF*1..2]->(n)
        WHERE s.case_id IN [%(seed_list)s]
        RETURN n.case_id
    $$) AS g(dst agtype)
),
hood AS (
    SELECT id FROM expanded UNION SELECT unnest(%(seed_ids)s::text[])
),
edges AS (
    SELECT trim(both '"' from a.dst::text) AS dst
    FROM ag_catalog.cypher('case_graph',
        $$ MATCH (s:case)-[:REF]->(n) RETURN s.case_id, n.case_id $$
    ) AS a(src agtype, dst agtype)
),
authority AS (
    SELECT h.id, count(e.dst) AS cite_count
    FROM hood h LEFT JOIN edges e ON e.dst = h.id
    GROUP BY h.id
),
cand AS (
    SELECT cu.id, cu.description_vector <=> %(qvec)s::vector AS dist, a.cite_count
    FROM hood h
    JOIN cases_updated cu ON cu.id = h.id
    JOIN authority a ON a.id = h.id
    WHERE left(cu.data->>'decision_date', 4) >= %(year_min)s
)
SELECT id, dist, cite_count,
       1.0 / (%(rrf_k)s + RANK() OVER (ORDER BY dist)) +
       1.0 / (%(rrf_k)s + RANK() OVER (ORDER BY cite_count DESC)) AS rrf
FROM cand
ORDER BY rrf DESC
LIMIT 10
"""


def tier3(results, qvecs):
    with psycopg.connect(PGRG_DB, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute(f"SET statement_timeout = {TIMEOUT_MS}")

        def run_one(cur, qv):
            cur.execute(PGRG_TIER3, {"qvec": qv, "ns": NS, "year_min": YEAR_MIN, "rrf_k": RRF_K})
            return len(cur.fetchall())

        results["tier3"]["pgrg_sql"] = timed(cur, run_one, qvecs) | {"statements": 1}
        print("  tier3 pgrg_sql:", results["tier3"]["pgrg_sql"], flush=True)

    with psycopg.connect(AGE_DB, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute('SET search_path = ag_catalog, "$user", public;')
        cur.execute(f"SET statement_timeout = {TIMEOUT_MS}")

        def run_1stmt(cur, qv):
            cur.execute(AGE_TIER3_1STMT, {"qvec": qv, "year_min": YEAR_MIN, "rrf_k": RRF_K})
            return len(cur.fetchall())

        results["tier3"]["age_sql_1stmt"] = timed(cur, run_1stmt, qvecs) | {"statements": 1}
        print("  tier3 age_sql_1stmt:", results["tier3"]["age_sql_1stmt"], flush=True)

        def run_2stmt(cur, qv):
            cur.execute(
                "SELECT id FROM cases_updated "
                "ORDER BY description_vector <=> %(qvec)s::vector LIMIT 60",
                {"qvec": qv},
            )
            seed_ids = [r[0] for r in cur.fetchall()]
            assert all(s.isdigit() for s in seed_ids)
            sql = AGE_TIER3_STMT2.replace("%(seed_list)s", ", ".join(f'"{s}"' for s in seed_ids))
            cur.execute(
                sql, {"qvec": qv, "seed_ids": seed_ids, "year_min": YEAR_MIN, "rrf_k": RRF_K}
            )
            return len(cur.fetchall())

        results["tier3"]["age_sql_2stmt_targeted_vle"] = timed(cur, run_2stmt, qvecs) | {
            "statements": 2
        }
        print("  tier3 age_sql_2stmt:", results["tier3"]["age_sql_2stmt_targeted_vle"], flush=True)


# ---------------------------------------------------------------- main


def main() -> None:
    anchors = []
    for seed in (41, 42, 43):
        for gq in json.load(open(DATA / f"gold_taskB_seed{seed}.json")):
            anchors.append({"case_id": gq["target_id"], "caption": gq["target_caption"]})
    corpus_name = {}
    for line in open(DATA / "corpus.jsonl"):
        c = json.loads(line)
        corpus_name[c["id"]] = c["entity_name"]
    with psycopg.connect(PGRG_DB) as conn:
        cur = conn.cursor()
        for a in anchors:
            row = cur.execute(
                "SELECT id FROM entities WHERE namespace = %s AND name = %s",
                (NS, corpus_name[a["case_id"]]),
            ).fetchone()
            a["entity_id"] = row[0] if row else None
    anchors = [a for a in anchors if a["entity_id"] is not None]
    print(f"tier1 anchors: {len(anchors)}")

    questions = [gq["question"] for gq in json.load(open(DATA / "gold_taskA_seed42.json"))]
    print("embedding 50 questions (outside timed loops for SQL arms) ...")
    from fastembed import TextEmbedding

    model = TextEmbedding("BAAI/bge-small-en-v1.5")
    qvecs = [json.dumps([float(x) for x in e]) for e in model.embed(questions)]

    results: dict = {"tier1": {}, "tier2": {}, "tier3": {}}
    tier1(results, anchors)
    tier2_sql(results, qvecs)
    asyncio.run(tier2_api(results, questions))
    tier3(results, qvecs)

    results["meta"] = {
        "label": "addendum 2 — pipeline latency; instrumentation of the preregistered corpus; no new accuracy claims",
        "protocol": (
            "tier1: 149 exact-id anchors; tiers 2-3: seed-42's 50 Task A questions, "
            "embeddings precomputed OUTSIDE timed loops for bare-SQL arms, INSIDE for API arms. "
            f"1 warmup pass + {REPEATS} timed repeats; statement_timeout {TIMEOUT_MS} ms; "
            "warmup timeout => item skipped for repeats and counted."
        ),
        "seed_stage_note": (
            "both engines request LIMIT 60 vector seeds through HNSW plans at the shipped "
            "ef_search=40 default => 40 effective seeds, symmetric"
        ),
        "unit_note": "pgrg returns chunks, AGE returns cases (native shapes, as in the main benchmark)",
    }
    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / "results_pipelines.json", "w") as f:
        json.dump(results, f, indent=2)
    print("wrote", RESULTS / "results_pipelines.json")


if __name__ == "__main__":
    main()
