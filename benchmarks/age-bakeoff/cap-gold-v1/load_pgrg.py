#!/usr/bin/env python3
"""Load the CAP gold v1 corpus into the pg-raggraph arm (METHODOLOGY §5).

No LLM anywhere: each case -> one document via ingest_records (skip_llm=True),
one `case` known_entity (duplicate captions carry an " (id)" suffix), each
in-corpus citation -> one CITES known_relationship. pg-raggraph chunks the
text itself (its native granularity); the AGE arm keeps one embedding per
case (Microsoft's shape). Identical raw text both arms.

Writes data/ingest_pgrg.json (wall time, doc/chunk/entity/edge/merge counts).

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/load_pgrg.py \
        [--db-url postgresql://postgres:postgres@localhost:5434/pg_raggraph_capgold]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

os.environ["PGRG_LLM_BASE_URL"] = ""  # no LLM may join the run

import psycopg  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
BATCH = 500


def ensure_database(db_url: str) -> None:
    base, _, dbname = db_url.rpartition("/")
    with psycopg.connect(base + "/postgres", autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{dbname}"')
            print(f"created database {dbname}")
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def make_record(c: dict, ent_name: dict[str, str]) -> dict:
    entities = [
        {
            "name": ent_name[c["id"]],
            "entity_type": "case",
            "description": c["name"][:500],
            "properties": {"case_id": c["id"], "court_id": c["court_id"]},
        }
    ] + [
        {"name": ent_name[dst], "entity_type": "case", "properties": {"case_id": dst}}
        for dst in c["cites_in_corpus"]
    ]
    relationships = [
        {"src": ent_name[c["id"]], "dst": ent_name[dst], "rel_type": "CITES", "weight": 1.0}
        for dst in c["cites_in_corpus"]
    ]
    return {
        "text": c["text"],
        "source_id": f"case:{c['id']}",
        "metadata": {
            "case_id": c["id"],
            "court_id": c["court_id"],
            "decision_date": c["decision_date"],
        },
        "entities": entities,
        "relationships": relationships,
        "skip_llm": True,
    }


async def run(db_url: str) -> None:
    from pg_raggraph import GraphRAG

    corpus = [json.loads(line) for line in open(DATA / "corpus.jsonl")]
    ent_name = {c["id"]: c["entity_name"] for c in corpus}
    records = [make_record(c, ent_name) for c in corpus]

    rag = GraphRAG(dsn=db_url, skip_extraction=True)
    await rag.connect()
    t0 = time.time()
    try:
        # Bulk-load pattern (METHODOLOGY Deviations D1): drop the two HNSW
        # indexes during load, rebuild after. Concurrent HNSW inserts inside
        # long per-doc transactions serialize on transactionid waits (observed:
        # 7/8 writers blocked, 2-6 s per chunk INSERT). Ingest-time entity
        # resolution never uses ANN (its fuzzy query computes exact distances
        # on trgm-filtered rows), so correctness is unaffected. Rebuild time
        # is included in the reported ingest wall.
        await rag.db.execute("DROP INDEX IF EXISTS idx_chunk_embed")
        await rag.db.execute("DROP INDEX IF EXISTS idx_entity_embed")

        done = 0
        for i in range(0, len(records), BATCH):
            batch = records[i : i + BATCH]
            # doc_concurrency 8 = the shipped "max" ingest profile; the default
            # "balanced" (2) paced this corpus at ~0.35 docs/s (~9 h) on this
            # machine. Shipped knob, recorded in RESULTS.
            await rag.ingest_records(batch, max_concurrent_docs=8)
            done += len(batch)
            print(f"  ingested {done}/{len(records)} ({time.time() - t0:.0f}s)", flush=True)

        t_idx = time.time()
        await rag.db.execute("SET maintenance_work_mem = '512MB'")
        await rag.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunk_embed ON chunks "
            "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )
        await rag.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_entity_embed ON entities "
            "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )
        await rag.db.execute("ANALYZE")
        print(f"  HNSW rebuild + analyze: {time.time() - t_idx:.0f}s", flush=True)
        wall = time.time() - t0

        counts = {}
        for label, q in [
            ("documents", "SELECT count(*) FROM documents"),
            ("chunks", "SELECT count(*) FROM chunks"),
            ("entities", "SELECT count(*) FROM entities"),
            ("relationships", "SELECT count(*) FROM relationships WHERE rel_type = 'CITES'"),
            ("fuzzy_merges", "SELECT count(*) FROM entity_merge_log"),
        ]:
            row = await rag.db.fetch_one(q)
            counts[label] = row["count"]
    finally:
        await rag.close()

    out = {"ingest_wall_s": round(wall, 1), "counts": counts, "n_records": len(records)}
    with open(DATA / "ingest_pgrg.json", "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--db-url", default="postgresql://postgres:postgres@localhost:5434/pg_raggraph_capgold"
    )
    args = ap.parse_args()
    ensure_database(args.db_url)
    asyncio.run(run(args.db_url))


if __name__ == "__main__":
    main()
