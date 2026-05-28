"""Bench B — resolve_entity_lookup throughput.

Measures lookups/sec for `resolve_entity_lookup` across:

  * match type: exact (name equals), trgm (fuzzy by surface variant), miss (None)
  * corpus size: 100 / 1000 / 10000 entities pre-seeded in the namespace

Reports calls/sec + p50/p95 ms over N=500 calls per cell.

Run:
  uv run python -m benchmarks.resolve_lookup_perf
"""

from __future__ import annotations

import asyncio
import random
import statistics
import time

from pg_raggraph import GraphRAG
from pg_raggraph.resolution import resolve_entity_lookup


DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
NS = "bench_resolve_lookup"
SAMPLES = 500
ENTITY_COUNTS = [100, 1000, 10000]

# Synthetic names — fixed seed for reproducibility
random.seed(42)
NAMES = [f"Entity{i:06d} Corp" for i in range(max(ENTITY_COUNTS))]


async def _seed(rag: GraphRAG, start: int, end: int) -> None:
    """Insert entities NAMES[start:end] (idempotent across cumulative calls)."""
    if end <= start:
        return
    dim = rag.config.embedding_dim
    rows = [(NS, NAMES[i], "Corp", "", [0.1] * dim) for i in range(start, end)]
    await rag.db.bulk_insert(
        "entities",
        ["namespace", "name", "entity_type", "description", "embedding"],
        rows,
    )


async def _bench_one(rag: GraphRAG, surfaces: list[str], samples: int) -> tuple[float, float, float, int]:
    """Run `samples` lookups picking surfaces round-robin; return (calls/s, p50, p95, hit_count)."""
    durs_ms: list[float] = []
    hits = 0
    t_start = time.perf_counter()
    for i in range(samples):
        s = surfaces[i % len(surfaces)]
        t0 = time.perf_counter()
        result = await resolve_entity_lookup(s, corpus_id=NS, db=rag.db, config=rag.config)
        durs_ms.append((time.perf_counter() - t0) * 1000)
        if result is not None:
            hits += 1
    total_s = time.perf_counter() - t_start
    p50 = statistics.median(durs_ms)
    p95 = sorted(durs_ms)[int(0.95 * len(durs_ms)) - 1]
    return samples / total_s, p50, p95, hits


async def main() -> None:
    rag = GraphRAG(
        dsn=DSN,
        namespace=NS,
        llm_base_url="http://localhost:99999/v1",
    )
    await rag.connect()
    await rag.delete(NS)

    print(f"namespace: {NS}")
    print(f"samples per cell: {SAMPLES}")
    print()
    print(
        f"{'entities':>10s}  {'match':>10s}  {'calls/s':>10s}  {'p50 ms':>8s}  {'p95 ms':>8s}  {'hits':>6s}"
    )
    print("-" * 64)

    try:
        cumulative_n = 0
        for n in ENTITY_COUNTS:
            if n > cumulative_n:
                await _seed(rag, cumulative_n, n)
                cumulative_n = n

            # Pick 10 random known + 10 fuzzy + 10 misses each cell — surface
            # rotation gives realistic mix without dominating cache by repeat
            picks = random.sample(range(n), min(10, n))
            exact_surfaces = [NAMES[i] for i in picks]
            trgm_surfaces = [NAMES[i].upper().replace("Corp", "INC") for i in picks]  # variant
            miss_surfaces = [f"NopeEntity{i:06d} Ltd" for i in range(10)]

            # Warmup the pool
            for _ in range(20):
                await resolve_entity_lookup(
                    NAMES[picks[0]], corpus_id=NS, db=rag.db, config=rag.config
                )

            for label, surfaces in (
                ("exact", exact_surfaces),
                ("trgm", trgm_surfaces),
                ("miss", miss_surfaces),
            ):
                rate, p50, p95, hits = await _bench_one(rag, surfaces, SAMPLES)
                print(
                    f"{n:>10d}  {label:>10s}  {rate:>10.1f}  {p50:>8.3f}  {p95:>8.3f}  {hits:>6d}"
                )
    finally:
        await rag.delete(NS)
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
