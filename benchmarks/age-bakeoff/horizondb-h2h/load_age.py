#!/usr/bin/env python3
"""Load the h2h corpus into the AGE arm (mirrors Microsoft's seed pipeline).

Mirrors setup_postgres_legal_seeddata.py from the accelerator:
  * cases_updated(id TEXT PK, data JSONB, description_vector vector(384))
  * gold_dataset(gold_id, label) — their table, verbatim rows
  * AGE graph 'case_graph': one (:case {case_id}) node per case,
    REF edges bulk-inserted into case_graph."REF" exactly like their
    create_edges_from_citations (direct INSERT of graphids, not per-edge
    Cypher — that is THEIR bulk-load approach, copied faithfully).

Differences from their seed script: 384-dim fastembed vectors (precomputed by
prepare_corpus.py) instead of 1536-dim OpenAI; no Azure role grants.

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/horizondb-h2h/load_age.py \
        [--db-url postgresql://postgres:postgres@localhost:5440/h2h_age]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-url", default="postgresql://postgres:postgres@localhost:5440/h2h_age")
    args = ap.parse_args()

    corpus = [json.loads(line) for line in open(DATA / "corpus.jsonl")]
    embs = {
        r["id"]: r["embedding"]
        for r in (json.loads(line) for line in open(DATA / "age_embeddings.jsonl"))
    }
    gold = json.load(open(DATA / "gold.json"))
    # Raw case JSON comes from the accelerator CSV; reload it for the data
    # column so the arm's table shape matches theirs (JSONB with casebody etc.).
    # corpus.jsonl already carries everything the queries touch; rebuild a
    # minimal JSONB with the same paths their SQL reads.
    t0 = time.time()

    with psycopg.connect(args.db_url, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute("CREATE EXTENSION IF NOT EXISTS age;")
        cur.execute('SET search_path = ag_catalog, "$user", public;')

        cur.execute("DROP TABLE IF EXISTS cases_updated;")
        cur.execute(
            "CREATE TABLE cases_updated (id TEXT PRIMARY KEY, data JSONB, "
            "description_vector vector(384));"
        )
        cur.execute("DROP TABLE IF EXISTS gold_dataset;")
        cur.execute("CREATE TABLE gold_dataset (gold_id TEXT, label TEXT);")
        cur.executemany(
            "INSERT INTO gold_dataset (gold_id, label) VALUES (%s, %s)",
            list(gold["labels"].items()),
        )

        rows = []
        for c in corpus:
            data = {
                "name": c["name"],
                "name_abbreviation": c["name_abbreviation"],
                "decision_date": c["decision_date"],
                "court": {"id": c["court_id"]},
                "casebody": {"opinions": [{"text": c["text"]}]},
                "cites_in_corpus": c["cites_in_corpus"],
            }
            rows.append((c["id"], json.dumps(data), json.dumps(embs[c["id"]])))
        cur.executemany(
            "INSERT INTO cases_updated (id, data, description_vector) VALUES (%s, %s, %s::vector)",
            rows,
        )
        print(f"loaded {len(rows)} cases into cases_updated")

        cur.execute(
            "CREATE INDEX ON cases_updated USING hnsw (description_vector vector_cosine_ops);"
        )

        # --- AGE graph ---
        cur.execute("SELECT count(*) FROM ag_catalog.ag_graph WHERE name = 'case_graph';")
        if cur.fetchone()[0]:
            cur.execute("SELECT drop_graph('case_graph', true);")
        cur.execute("SELECT create_graph('case_graph');")
        cur.execute("SELECT create_vlabel('case_graph', 'case');")
        cur.execute("SELECT create_elabel('case_graph', 'REF');")

        for c in corpus:
            assert c["id"].isdigit(), c["id"]
            # their create_case_in_case_graph stores case_id as a string prop
            cur.execute(
                f"SELECT * FROM cypher('case_graph', "
                f'$$ CREATE (:case {{case_id: "{c["id"]}"}}) $$) AS (a agtype);'
            )
        print(f"created {len(corpus)} case nodes")

        # Bulk edge insert — their create_edges_from_citations approach:
        # resolve graphids from the vertex table, INSERT INTO case_graph."REF".
        cur.execute("DROP TABLE IF EXISTS _h2h_edges;")
        cur.execute("CREATE TABLE _h2h_edges (id_from TEXT, id_to TEXT);")
        pairs = sorted({(c["id"], dst) for c in corpus for dst in c["cites_in_corpus"]})
        cur.executemany("INSERT INTO _h2h_edges VALUES (%s, %s)", pairs)
        # NOTE: Microsoft's seed script writes `properties ->> 'case_id'` —
        # that form errors on stock Apache AGE 1.5.0 ("Expected agtype value")
        # and only works on Azure's AGE build. Stock AGE requires the RHS to
        # be an agtype string: `->> '"case_id"'::agtype`. Recorded in README.
        cur.execute(
            """
            INSERT INTO case_graph."REF" (start_id, end_id)
            SELECT n1.id, n2.id
            FROM _h2h_edges e
            JOIN case_graph."case" n1 ON n1.properties ->> '"case_id"'::agtype = e.id_from
            JOIN case_graph."case" n2 ON n2.properties ->> '"case_id"'::agtype = e.id_to;
            """
        )
        cur.execute("DROP TABLE _h2h_edges;")
        cur.execute(
            "SELECT count(*) FROM cypher('case_graph', "
            "$$ MATCH ()-[r:REF]->() RETURN r $$) AS (r agtype);"
        )
        n_edges = cur.fetchone()[0]
        print(f"created {n_edges} REF edges (expected {len(pairs)})")

        cur.execute("ANALYZE cases_updated;")
        cur.execute('ANALYZE case_graph."case";')
        cur.execute('ANALYZE case_graph."REF";')

    print(f"AGE arm loaded in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
