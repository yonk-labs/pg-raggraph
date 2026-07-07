#!/usr/bin/env python3
"""Load the CAP gold v1 corpus into the AGE arm (mirrors the h2h load_age.py,
which mirrors Microsoft's seed pipeline).

  * cases_updated(id TEXT PK, data JSONB, description_vector vector(384))
    + HNSW cosine index — one embedding per case (their shape), computed
    here with fastembed bge-small-en-v1.5 over the identical raw text.
  * AGE graph 'case_graph': one (:case {case_id}) node per case, REF edges
    bulk-inserted (their create_edges_from_citations approach, incl. the
    stock-AGE `->> '"case_id"'::agtype` fix the h2h documented).

Writes data/ingest_age.json (wall time + counts).

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/load_age.py \
        [--db-url postgresql://postgres:postgres@localhost:5440/capgold_age]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"


def ensure_database(db_url: str) -> None:
    base, _, dbname = db_url.rpartition("/")
    with psycopg.connect(base + "/postgres", autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{dbname}"')
            print(f"created database {dbname}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--db-url", default="postgresql://postgres:postgres@localhost:5440/capgold_age"
    )
    args = ap.parse_args()
    ensure_database(args.db_url)

    corpus = [json.loads(line) for line in open(DATA / "corpus.jsonl")]

    print(f"embedding {len(corpus)} cases with fastembed BAAI/bge-small-en-v1.5 ...")
    from fastembed import TextEmbedding

    t0 = time.time()
    model = TextEmbedding("BAAI/bge-small-en-v1.5")
    embs = list(model.embed([c["text"] for c in corpus], batch_size=64))
    t_embed = time.time() - t0
    print(f"embedded in {t_embed:.0f}s")

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
        rows = []
        for c, e in zip(corpus, embs):
            data = {
                "name": c["name"],
                "name_abbreviation": c["name_abbreviation"],
                "decision_date": c["decision_date"],
                "court": {"id": c["court_id"]},
                "cites_in_corpus": c["cites_in_corpus"],
            }
            rows.append((c["id"], json.dumps(data), json.dumps([float(x) for x in e])))
        with cur.copy("COPY cases_updated (id, data, description_vector) FROM STDIN") as copy:
            for r in rows:
                copy.write_row(r)
        print(f"loaded {len(rows)} cases into cases_updated")
        cur.execute(
            "CREATE INDEX ON cases_updated USING hnsw (description_vector vector_cosine_ops);"
        )

        cur.execute("SELECT count(*) FROM ag_catalog.ag_graph WHERE name = 'case_graph';")
        if cur.fetchone()[0]:
            cur.execute("SELECT drop_graph('case_graph', true);")
        cur.execute("SELECT create_graph('case_graph');")
        cur.execute("SELECT create_vlabel('case_graph', 'case');")
        cur.execute("SELECT create_elabel('case_graph', 'REF');")

        for i, c in enumerate(corpus):
            assert c["id"].isdigit(), c["id"]
            cur.execute(
                f"SELECT * FROM cypher('case_graph', "
                f'$$ CREATE (:case {{case_id: "{c["id"]}"}}) $$) AS (a agtype);'
            )
            if (i + 1) % 2000 == 0:
                print(f"  {i + 1} case nodes ({time.time() - t0:.0f}s)", flush=True)
        print(f"created {len(corpus)} case nodes")

        cur.execute("DROP TABLE IF EXISTS _capgold_edges;")
        cur.execute("CREATE TABLE _capgold_edges (id_from TEXT, id_to TEXT);")
        pairs = sorted({(c["id"], dst) for c in corpus for dst in c["cites_in_corpus"]})
        cur.executemany("INSERT INTO _capgold_edges VALUES (%s, %s)", pairs)
        # stock AGE 1.5.0 requires the agtype-string RHS (h2h finding)
        cur.execute(
            """
            INSERT INTO case_graph."REF" (start_id, end_id)
            SELECT n1.id, n2.id
            FROM _capgold_edges e
            JOIN case_graph."case" n1 ON n1.properties ->> '"case_id"'::agtype = e.id_from
            JOIN case_graph."case" n2 ON n2.properties ->> '"case_id"'::agtype = e.id_to;
            """
        )
        cur.execute("DROP TABLE _capgold_edges;")
        cur.execute(
            "SELECT count(*) FROM cypher('case_graph', "
            "$$ MATCH ()-[r:REF]->() RETURN r $$) AS (r agtype);"
        )
        n_edges = cur.fetchone()[0]
        print(f"created {n_edges} REF edges (expected {len(pairs)})")

        cur.execute("ANALYZE cases_updated;")
        cur.execute('ANALYZE case_graph."case";')
        cur.execute('ANALYZE case_graph."REF";')

    wall = time.time() - t0
    out = {
        "embed_wall_s": round(t_embed, 1),
        "load_wall_s": round(wall, 1),
        "n_cases": len(corpus),
        "n_edges": n_edges,
        "n_edges_expected": len(pairs),
    }
    with open(DATA / "ingest_age.json", "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
