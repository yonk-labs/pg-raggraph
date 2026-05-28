"""Bench A — MCP staleness chokepoint overhead.

Measures the per-tool latency added by `_apply_freshness` / `list_pending_documents`
as the count of pending docs in a namespace grows. Compares:

  - baseline (no pending docs — chokepoint computes empty banner/footer)
  - 10 / 100 / 1000 / 10000 pending docs in the namespace

Reports p50 and p95 over N=200 calls per cell.

Run:
  uv run python -m benchmarks.mcp_freshness_perf
"""

from __future__ import annotations

import asyncio
import statistics
import time

from pg_raggraph import GraphRAG
from pg_raggraph.mcp_helpers import _apply_freshness


DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
NS = "bench_mcp_freshness"
SAMPLES = 200
PENDING_COUNTS = [0, 10, 100, 1000, 10000]


async def _seed(rag: GraphRAG, n: int) -> None:
    """Seed N pending docs in the namespace."""
    if n == 0:
        return
    # Use small chunks; the chokepoint reads documents.*, not chunks.
    records = [
        {
            "text": f"doc {i} body — short content to make ingest cheap",
            "source_id": f"/repo/bench/doc-{i:06d}.md",
        }
        for i in range(n)
    ]
    # defer_extraction=True → graph_status='pending' immediately
    await rag.ingest_records(records, namespace=NS, defer_extraction=True)


async def _bench_one(rag: GraphRAG, samples: int) -> tuple[float, float, float]:
    """Run `samples` chokepoint calls; return (p50, p95, mean) in ms."""
    # Synthetic baseline response — exercises both citation paths.
    response_with_cite = {
        "chunks": [{"source": "/repo/bench/doc-000000.md", "score": 0.9, "content": "..."}],
        "entities": ["X"],
    }

    durs_ms: list[float] = []
    for _ in range(samples):
        t0 = time.perf_counter()
        await _apply_freshness(dict(response_with_cite), rag=rag, namespace=NS)
        durs_ms.append((time.perf_counter() - t0) * 1000)

    p50 = statistics.median(durs_ms)
    p95 = sorted(durs_ms)[int(0.95 * len(durs_ms)) - 1]
    mean = statistics.mean(durs_ms)
    return p50, p95, mean


async def main() -> None:
    rag = GraphRAG(
        dsn=DSN,
        namespace=NS,
        llm_base_url="http://localhost:99999/v1",  # no LLM; lede off
    )
    await rag.connect()

    print(f"namespace: {NS}")
    print(f"samples per cell: {SAMPLES}")
    print()
    print(f"{'pending docs':>12s}  {'p50 ms':>8s}  {'p95 ms':>8s}  {'mean ms':>8s}  {'banner?':>8s}")
    print("-" * 56)

    try:
        cumulative_n = 0
        for n in PENDING_COUNTS:
            # Each cell adds (n - cumulative_n) more pending docs so we can grow
            # incrementally without resetting.
            delta = n - cumulative_n
            if delta > 0:
                await _seed(rag, delta)
                cumulative_n = n

            # Warmup (DB pool, hot caches)
            for _ in range(10):
                await _apply_freshness(
                    {"chunks": [{"source": "/repo/bench/doc-000000.md"}]}, rag=rag, namespace=NS
                )

            p50, p95, mean = await _bench_one(rag, SAMPLES)

            # Banner presence check
            resp = {"chunks": [{"source": "/repo/bench/doc-000000.md"}]}
            await _apply_freshness(resp, rag=rag, namespace=NS)
            has_banner = "yes" if "banner" in resp or "footer" in resp else "no"

            print(f"{n:>12d}  {p50:>8.3f}  {p95:>8.3f}  {mean:>8.3f}  {has_banner:>8s}")
    finally:
        await rag.delete(NS)
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
