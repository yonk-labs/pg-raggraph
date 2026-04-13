"""Demo script: show smart mode routing in action.

Runs 5 questions against the bench_ntsb corpus (already ingested)
and shows which smart-mode path each question took.

Usage:
    uv run python benchmarks/demo_smart_mode.py
"""

import asyncio
import os
import time

with open("/home/yonk/yonk-tools/pg-agent/.openai") as f:
    os.environ["OPENAI_API_KEY"] = f.read().strip().split("=", 1)[1]

from pg_raggraph import GraphRAG  # noqa: E402

DEMO_QUERIES = [
    # Direct factual — should be smart[naive]
    ("What aircraft was involved in the first incident?", "naive path (direct)"),
    # Keyword-heavy — should be smart[naive]
    ("pilot error weather conditions", "naive path (BM25 friendly)"),
    # Multi-hop reasoning — likely smart[boosted] or smart[expanded]
    ("How does pilot experience relate to aviation incidents?", "graph-boosted"),
    # Vague — likely smart[expanded]
    ("common patterns across crashes", "expanded (vague query)"),
    # Specific entity lookup — should find confidence
    ("Beech A23 incident details", "high confidence naive"),
]


async def main():
    print("=" * 75)
    print("SMART MODE DEMO — pg-raggraph")
    print("=" * 75)
    print("\nRunning 5 questions through smart mode on the NTSB corpus.")
    print("Each question shows the path smart mode chose and why.\n")

    rag = GraphRAG(
        dsn="postgresql://postgres:postgres@localhost:5434/pg_raggraph",
        namespace="bench_ntsb",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
        llm_api_key=os.environ["OPENAI_API_KEY"],
    )
    await rag.connect()

    # Check corpus is ingested
    status = await rag.status("bench_ntsb")
    if status["documents"] == 0:
        print("ERROR: bench_ntsb is empty. Run `uv run python benchmarks/ingest_all.py` first.")
        await rag.close()
        return

    print(
        f"Corpus: {status['documents']} docs, "
        f"{status['entities']} entities, "
        f"{status['relationships']} relationships\n"
    )

    for i, (question, expected) in enumerate(DEMO_QUERIES, 1):
        print("-" * 75)
        print(f"[{i}/{len(DEMO_QUERIES)}] Q: {question}")
        print(f"     Expected path: {expected}")

        t0 = time.perf_counter()
        result = await rag.query(question, mode="smart", namespace="bench_ntsb")
        elapsed = (time.perf_counter() - t0) * 1000

        print(
            f"     Chose: {result.query_mode:<20} "
            f"confidence={result.confidence:<6} "
            f"top_score={result.top_score:.2f} "
            f"time={elapsed:.0f}ms"
        )
        print(f"     Found: {len(result.chunks)} chunks, {len(result.entities)} entities")

        if result.chunks:
            top = result.chunks[0]
            src = top.document_source or "unknown"
            src_name = os.path.basename(src)
            preview = top.content[:140].replace("\n", " ")
            print(f"     Top chunk [{top.score:.2f}] from {src_name}:")
            print(f'       "{preview}..."')
        print()

    # Compare smart vs other modes on one query
    print("=" * 75)
    print("MODE COMPARISON on 'common patterns across crashes'")
    print("=" * 75)
    q = "common patterns across crashes"
    modes = ["naive", "naive_boost", "smart", "hybrid"]
    for mode in modes:
        r = await rag.query(q, mode=mode, namespace="bench_ntsb")
        print(
            f"  {mode:<14} {r.latency_ms:>5.0f}ms  "
            f"chunks={len(r.chunks):>2}  "
            f"entities={len(r.entities):>3}  "
            f"reported_mode={r.query_mode}"
        )

    await rag.close()

    print("\n" + "=" * 75)
    print("KEY TAKEAWAYS")
    print("=" * 75)
    print("""
  - Smart mode picks the cheapest path that gets the answer right.
  - High-confidence queries (known keywords, clear match) stay in naive.
  - Medium-confidence queries get a 1-hop graph boost (cheap).
  - Low-confidence queries escalate to full graph expansion.
  - You get hybrid-quality results at naive-like speed on most questions.
""")


if __name__ == "__main__":
    asyncio.run(main())
