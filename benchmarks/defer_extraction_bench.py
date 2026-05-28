"""Before/after benchmark for defer_extraction.

Measures the user-visible speedup of moving LLM/lede extraction out of
ingest() and into a background worker. Uses lede_spacy as the extractor
because it's deterministic, requires no network, and exercises the real
graph-write path end-to-end.

Three arms, each on the same MHR slice:

  A. SYNC      — defer_extraction=False (today's default with extraction).
                  Wall time = chunk + embed + extract + graph-write (one tx).
  B. DEFER     — defer_extraction=True. Wall time = chunk + embed + status
                  flip only. The graph is empty; naive retrieval still works.
  C. DRAIN     — pgrg-extract equivalent on the docs from B. Wall time of
                  claim_pending + extract_documents until queue empty.

Headline numbers:
  * Time-to-queryable        = B
  * Time-to-full-graph (sync)= A
  * Time-to-full-graph (defer)= B + C
  * Async win                = A - B   (what the caller doesn't wait for)
  * Total overhead           = (B + C) - A   (signed; expected near 0)

Run: uv run python -m benchmarks.defer_extraction_bench --docs 20
"""

from __future__ import annotations

import argparse
import asyncio
import time

from benchmarks.e2e.datasets.mhr import load as load_mhr
from pg_raggraph import GraphRAG
from pg_raggraph.backfill import claim_pending, extract_documents

TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


def _make_rag(namespace: str) -> GraphRAG:
    return GraphRAG(
        dsn=TEST_DSN,
        namespace=namespace,
        fact_extractor="lede_spacy",
        # No LLM endpoint — lede_spacy is the active extractor, deterministic.
        llm_base_url="",
    )


async def _ensure_warm_embed_cache(rag: GraphRAG, docs) -> None:
    """Embedding cache is shared across runs; pre-warm it to remove cold-cache
    noise. We want to measure the EXTRACTION delta, not the embedder.
    """
    embedder = rag._get_embedder()
    from pg_raggraph.chunking import chunk_document

    all_chunks: list[str] = []
    for d in docs:
        all_chunks.extend(c["content"] for c in chunk_document(d.text, config=rag.config))
    # First touch populates the cache.
    await embedder.embed(all_chunks)


async def _ingest(rag, docs, *, defer: bool) -> float:
    records = [
        {
            "text": d.text,
            "source_id": f"defer_bench:{d.source_id}",
            "metadata": dict(d.metadata),
        }
        for d in docs
    ]
    t0 = time.perf_counter()
    await rag.ingest_records(records, defer_extraction=defer)
    return time.perf_counter() - t0


async def _drain(rag, batch_size: int = 16) -> tuple[float, dict]:
    """Drain the pending queue; return (wall_time, totals)."""
    totals = {"claimed": 0, "ready": 0, "failed": 0, "ents": 0, "rels": 0, "iters": 0}
    t0 = time.perf_counter()
    while True:
        ids = await claim_pending(rag.db, rag.config.namespace, batch_size)
        if not ids:
            break
        totals["iters"] += 1
        stats = await extract_documents(rag, ids)
        totals["claimed"] += stats.claimed
        totals["ready"] += stats.ready
        totals["failed"] += stats.failed
        totals["ents"] += stats.entities
        totals["rels"] += stats.relationships
    return time.perf_counter() - t0, totals


async def _graph_counts(rag) -> dict:
    ns = rag.config.namespace
    docs = await rag.db.fetch_one(
        "SELECT count(*) AS n FROM documents WHERE namespace = %s", (ns,)
    )
    chunks = await rag.db.fetch_one(
        "SELECT count(*) AS n FROM chunks c "
        "JOIN documents d ON d.id = c.document_id WHERE d.namespace = %s",
        (ns,),
    )
    ents = await rag.db.fetch_one(
        "SELECT count(*) AS n FROM entities WHERE namespace = %s", (ns,)
    )
    rels = await rag.db.fetch_one(
        "SELECT count(*) AS n FROM relationships WHERE namespace = %s", (ns,)
    )
    return {
        "docs": docs["n"],
        "chunks": chunks["n"],
        "ents": ents["n"],
        "rels": rels["n"],
    }


async def main(n_docs: int) -> None:
    bundle = load_mhr()
    docs = bundle.corpus_docs[:n_docs]
    n_chars = sum(len(d.text) for d in docs)
    print(f"corpus: {n_docs} docs, {n_chars:,} chars")
    print(f"extractor: lede_spacy (deterministic, no LLM)")
    print()

    # Pre-warm the embedding cache so cold-cache noise doesn't masquerade as
    # extraction cost. Both arms then pay the same warm-cache embedding price.
    warm_rag = _make_rag("defer_bench_warm")
    await warm_rag.connect()
    try:
        await warm_rag.delete("defer_bench_warm")
        await _ensure_warm_embed_cache(warm_rag, docs)
    finally:
        await warm_rag.close()

    # ===== ARM A: sync extract =====
    rag_a = _make_rag("defer_bench_a")
    await rag_a.connect()
    try:
        await rag_a.delete("defer_bench_a")
        t_a = await _ingest(rag_a, docs, defer=False)
        graph_a = await _graph_counts(rag_a)
    finally:
        await rag_a.delete("defer_bench_a")
        await rag_a.close()

    # ===== ARM B: deferred ingest =====
    rag_b = _make_rag("defer_bench_b")
    await rag_b.connect()
    try:
        await rag_b.delete("defer_bench_b")
        t_b = await _ingest(rag_b, docs, defer=True)
        graph_b_pre = await _graph_counts(rag_b)

        # ===== ARM C: drain via backfill primitive (== `pgrg extract`) =====
        t_c, drain_stats = await _drain(rag_b)
        graph_b_post = await _graph_counts(rag_b)
    finally:
        await rag_b.delete("defer_bench_b")
        await rag_b.close()

    print("=== ARM A — SYNC ingest (defer_extraction=False) ===")
    print(f"  wall:        {t_a:7.2f}s  ({1000 * t_a / n_docs:6.1f} ms/doc)")
    print(f"  graph:       {graph_a}")
    print()
    print("=== ARM B — DEFER ingest (defer_extraction=True) ===")
    print(f"  wall:        {t_b:7.2f}s  ({1000 * t_b / n_docs:6.1f} ms/doc)")
    print(f"  graph (pre): {graph_b_pre}   ← naive-queryable, no entities yet")
    print()
    print("=== ARM C — DRAIN (pgrg extract equivalent) ===")
    print(f"  wall:        {t_c:7.2f}s  ({1000 * t_c / n_docs:6.1f} ms/doc)")
    print(f"  iterations:  {drain_stats['iters']}")
    print(f"  claimed/ready/failed: {drain_stats['claimed']}/{drain_stats['ready']}/{drain_stats['failed']}")
    print(f"  graph (post): {graph_b_post}")
    print()
    print("=== HEADLINE ===")
    print(f"  Time-to-queryable (B):       {t_b:7.2f}s   {1000 * t_b / n_docs:6.1f} ms/doc")
    print(f"  Time-to-full-graph SYNC (A): {t_a:7.2f}s   {1000 * t_a / n_docs:6.1f} ms/doc")
    print(f"  Time-to-full-graph DEFER (B+C): {t_b + t_c:7.2f}s   {1000 * (t_b + t_c) / n_docs:6.1f} ms/doc")
    speedup_b_vs_a = t_a / t_b if t_b > 0 else float("inf")
    overhead = (t_b + t_c) - t_a
    print(
        f"  Async win (A - B):           {t_a - t_b:+7.2f}s  ← what the caller no longer waits for"
    )
    print(
        f"  Caller speedup (A / B):      {speedup_b_vs_a:6.2f}×  ← perceived 'non-event' factor"
    )
    print(
        f"  Total overhead ((B+C) - A):  {overhead:+7.2f}s  ← signed; near 0 means async is free"
    )
    print()
    # Sanity: deferred path should end up with comparable graph counts.
    print(
        f"  Graph parity: A entities={graph_a['ents']} rels={graph_a['rels']} | "
        f"B+C entities={graph_b_post['ents']} rels={graph_b_post['rels']}"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=int, default=20)
    a = ap.parse_args()
    asyncio.run(main(a.docs))
