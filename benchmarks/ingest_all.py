"""Ingest all benchmark corpora with OpenAI gpt-4o-mini.

Runs sequentially to avoid LLM contention.
"""

import asyncio
import os
import time

from pg_raggraph import GraphRAG

# Load OpenAI key
with open("/home/yonk/yonk-tools/pg-agent/.openai") as f:
    key = f.read().strip().split("=", 1)[1]
os.environ["OPENAI_API_KEY"] = key

TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))

CORPORA = [
    ("bench_ntsb", os.path.join(BENCH_DIR, "kg-rag-eval", "extracted", "ntsb")),
    ("bench_sec", os.path.join(BENCH_DIR, "kg-rag-eval", "extracted", "sec-10q")),
    ("bench_pg", os.path.join(BENCH_DIR, "postgres-docs")),
    ("bench_scotus", os.path.join(BENCH_DIR, "scotus")),
]


async def ingest_corpus(namespace: str, path: str):
    """Ingest one corpus and report stats."""
    print(f"\n{'=' * 70}")
    print(f"Ingesting: {namespace}")
    print(f"Path: {path}")
    print(f"{'=' * 70}")

    # Use the "aggressive" profile (not "max") to leave some CPU headroom.
    # Override with INGEST_PROFILE env var if needed.
    profile = os.environ.get("INGEST_PROFILE", "aggressive")
    nice = int(os.environ.get("INGEST_NICE", "5"))

    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace=namespace,
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
        llm_api_key=os.environ["OPENAI_API_KEY"],
        ingest_profile=profile,
        nice_level=nice,
    )
    await rag.connect()

    # Check if already ingested
    existing = await rag.status(namespace)
    if existing["documents"] > 0:
        print(
            f"  Already ingested: {existing['documents']} docs, "
            f"{existing['entities']} entities, {existing['relationships']} rels"
        )
        await rag.close()
        return existing

    t0 = time.perf_counter()
    try:
        await rag.ingest([path], namespace=namespace)
    except Exception as e:
        print(f"  ERROR: {e}")
        await rag.close()
        return None
    elapsed = time.perf_counter() - t0

    status = await rag.status(namespace)
    print(f"  Done in {elapsed:.1f}s ({elapsed / max(status['documents'], 1):.1f}s/doc)")
    print(
        f"  {status['documents']} docs, {status['chunks']} chunks, "
        f"{status['entities']} entities, {status['relationships']} rels"
    )

    await rag.close()
    status["ingest_seconds"] = elapsed
    return status


async def main():
    results = {}
    total_start = time.perf_counter()

    for namespace, path in CORPORA:
        if not os.path.exists(path):
            print(f"SKIP {namespace}: path not found {path}")
            continue
        stats = await ingest_corpus(namespace, path)
        if stats:
            results[namespace] = stats

    total_elapsed = time.perf_counter() - total_start

    print("\n" + "=" * 70)
    print("INGESTION SUMMARY")
    print("=" * 70)
    print(
        f"\n  {'Corpus':<20} {'Docs':>6} {'Chunks':>8} {'Entities':>10} {'Rels':>8} {'Time':>10}"
    )
    print("  " + "-" * 70)
    for ns, s in results.items():
        t = s.get("ingest_seconds", 0)
        print(
            f"  {ns:<20} {s['documents']:>6} {s['chunks']:>8} "
            f"{s['entities']:>10} {s['relationships']:>8} {t:>8.0f}s"
        )

    totals = {
        "docs": sum(s["documents"] for s in results.values()),
        "chunks": sum(s["chunks"] for s in results.values()),
        "entities": sum(s["entities"] for s in results.values()),
        "rels": sum(s["relationships"] for s in results.values()),
    }
    print("  " + "-" * 70)
    print(
        f"  {'TOTAL':<20} {totals['docs']:>6} {totals['chunks']:>8} "
        f"{totals['entities']:>10} {totals['rels']:>8} {total_elapsed:>8.0f}s"
    )


if __name__ == "__main__":
    asyncio.run(main())
