#!/usr/bin/env python3
"""Load the h2h corpus into the pg-raggraph arm.

Same raw text as the AGE arm (name + first 8000 chars of the lead opinion),
same citation graph, same embedder (bge-small-en-v1.5 via pg-raggraph's
default FastEmbedProvider). No LLM anywhere:

  * each case -> one document via ingest_records (skip_llm=True)
  * each case -> one known_entity (entity_type "case"; duplicate case names
    disambiguated with "(id)" suffix — 19 duplicates in the corpus)
  * each in-corpus citation -> one known_relationship (rel_type CITES),
    deterministically mirroring the AGE arm's REF edges

pg-raggraph chunks the text itself (its native design); the AGE arm keeps
Microsoft's one-embedding-per-case shape. Both arms therefore run their own
system's intended retrieval granularity over identical raw text.

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/horizondb-h2h/load_pgrg.py \
        [--db-url postgresql://postgres:postgres@localhost:5434/pg_raggraph_h2h]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"


def ensure_database(db_url: str) -> None:
    """CREATE DATABASE if missing (connect to the maintenance db)."""
    base, _, dbname = db_url.rpartition("/")
    with psycopg.connect(base + "/postgres", autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{dbname}"')
            print(f"created database {dbname}")
    # pg-raggraph's pool registers the vector type before schema bootstrap,
    # so the extensions must pre-exist in a fresh database.
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


async def run(db_url: str) -> None:
    from pg_raggraph import GraphRAG

    corpus = [json.loads(line) for line in open(DATA / "corpus.jsonl")]
    ent_name = {c["id"]: c["entity_name"] for c in corpus}

    records = []
    for c in corpus:
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
            {
                "src": ent_name[c["id"]],
                "dst": ent_name[dst],
                "rel_type": "CITES",
                "weight": 1.0,
            }
            for dst in c["cites_in_corpus"]
        ]
        records.append(
            {
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
        )

    rag = GraphRAG(dsn=db_url, skip_extraction=True)
    await rag.connect()
    try:
        t0 = time.time()
        stats = await rag.ingest_records(records)
        print(f"ingested in {time.time() - t0:.1f}s: {stats}")
    finally:
        await rag.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--db-url", default="postgresql://postgres:postgres@localhost:5434/pg_raggraph_h2h"
    )
    args = ap.parse_args()
    ensure_database(args.db_url)
    asyncio.run(run(args.db_url))


if __name__ == "__main__":
    main()
