"""Bridge: chunkshop SP-A `agent_memory.memory` → pg-raggraph (Pattern M).

SP-B "agent-memory read bridge" (pg-raggraph issue #4). chunkshop's
SP-A primitives shipped in 0.4.3 — they write a two-tier
`agent_memory.memory` table that holds both episode chunks
(`kind='episode'`) and atomic SPO fact rows (`kind='fact'`), tagged
`tier='provisional'` or `tier='consolidated'`. This script bridges
that table into pg-raggraph's graph layer via the existing
`ingest_records(pre_chunked=…, relationships=…, skip_llm=True)` seams.

No new pg-raggraph API is introduced. The bridge is a transform — the
`pg_raggraph.memory_bridge.rows_to_records()` helper handles the SP-A
→ pg-raggraph record-shape mapping.

Pre-requisite: chunkshop SP-A has populated `agent_memory.memory`.
See chunkshop's `docs/incremental.md#agent-memory-sp-a` and
`configs/memory/{realtime,consolidate}.yaml`.

What this script does:
  1. Reads agent_memory.memory in the SP-A canonical column set.
  2. Groups rows by session_id (each session = one pg-raggraph document).
  3. Maps episode rows → pre_chunked (chunks + embeddings pass through
     unchanged; no re-embedding).
  4. Maps fact rows → caller-known relationships (SPO triple → src/dst/
     rel_type) AND chunks (the support_span proposition is also
     vector-retrievable — the Dense-X lever).
  5. Stamps `tier` onto every chunk's metadata so the read-side
     `memory_tier` filter (config + per-call kwarg) enforces SP-A's O2
     consolidated-wins rule.
  6. Calls rag.ingest_records() with skip_llm=True (SP-A already
     extracted the facts; LLM re-extraction would be wasted work).

At read time:

    # Default config — sees both tiers, ranks naturally
    await rag.ask("what did the agent learn about postgres?")

    # SP-A O2: prefer consolidated when both exist
    await rag.ask("what did the agent learn?", memory_tier="consolidated")

Honest gap: pg-raggraph's `relationships` table does not currently
have per-fact temporal columns (effective_from / effective_to /
retracted). The bridge stashes those values in the *chunk*
metadata (the fact chunk's `support_span` carries them), so they're
queryable via JSONB and visible on `ChunkResult.metadata`, but they
don't drive ranking. Adding first-class temporal columns to the
relationships table is a separate evolution-tier ask.
"""

from __future__ import annotations

import asyncio
import os

import psycopg
from psycopg.rows import dict_row

from pg_raggraph import GraphRAG
from pg_raggraph.memory_bridge import SP_A_MEMORY_COLUMNS, rows_to_records

PGRG_DSN = os.environ.get(
    "PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
)
SP_A_DSN = os.environ.get("SP_A_DSN", PGRG_DSN)  # often the same database
NAMESPACE = os.environ.get("PGRG_NAMESPACE", "agent_memory")
SP_A_TABLE = os.environ.get("SP_A_TABLE", "agent_memory.memory")

# Subset of SP-A columns we actually project. Keeping the SELECT
# explicit (vs SELECT *) makes the column contract obvious and lets the
# contract test in tests/unit/test_sp_a_memory_contract.py guard drift.
_SELECT_COLS = sorted(SP_A_MEMORY_COLUMNS)
SQL_FETCH_MEMORY = (
    f"SELECT {', '.join(_SELECT_COLS)} FROM {SP_A_TABLE} "
    "WHERE namespace = %(namespace)s ORDER BY session_id, seq_num"
)


async def main() -> None:
    rag = GraphRAG(
        dsn=PGRG_DSN,
        namespace=NAMESPACE,
        # SP-A's default embedder is int8 bge-small (384d). Match here
        # so `pre_chunked` dim validation passes without re-embedding.
        embedding_dim=384,
        # No LLM needed — fact extraction already happened in SP-A's
        # consolidation cell. The bridge passes skip_llm=True per record.
        skip_extraction=True,
    )
    await rag.connect()

    # Fetch SP-A rows. Synchronous psycopg is fine for the demo — chunkshop
    # writes to this table from offline cells, so the read path is bulk and
    # latency-insensitive.
    with psycopg.connect(SP_A_DSN, row_factory=dict_row) as conn:
        rows = list(conn.execute(SQL_FETCH_MEMORY, {"namespace": NAMESPACE}).fetchall())

    if not rows:
        print(f"No rows found in {SP_A_TABLE} for namespace={NAMESPACE!r}. "
              f"Run chunkshop's `memory/consolidate.yaml` cell first.")
        return

    records = rows_to_records(rows)
    print(
        f"Bridging {len(rows)} SP-A rows → {len(records)} pg-raggraph "
        f"records (one per session) into namespace {NAMESPACE!r}."
    )

    await rag.ingest_records(records, namespace=NAMESPACE)

    # Smoke-check the tier filter works. With `memory_tier='consolidated'`,
    # any provisional-tier chunks bridged above are filtered out at read
    # time without re-ingesting.
    result = await rag.ask(
        "summarize what was learned in this session",
        memory_tier="consolidated",
    )
    print(f"\nask(memory_tier='consolidated') → {len(result.chunks)} chunks")
    if result.chunks:
        print(f"  top chunk tier: "
              f"{(result.chunks[0].metadata or {}).get('tier', '(no tier metadata)')}")

    await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
