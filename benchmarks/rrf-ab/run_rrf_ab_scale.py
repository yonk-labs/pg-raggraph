"""A/B at scale: linear vs RRF fusion on the FULL MuSiQue corpus (issue #57).

This is the benchmark the RRF blog promised: bigger and noisier than
``run_rrf_ab.py`` (which saturated recall at 1.0 on ~188 docs), with
rank-sensitive metrics so the comparison can actually move.

- Corpus: the full 1700-paragraph MuSiQue pool (diverse Wikipedia prose) =
  genuine noise. Each question's ~2-4 gold docs sit among ~1696 distractors.
- Mode: naive (vector + BM25 legs only — the purest place to test RRF's
  scale-free fusion). Graph extraction is skipped for a fast ingest.
- Metrics: nDCG@10 and MRR (rank-sensitive, won't saturate) plus
  recall@{1,5,10} (recall@1 discriminates where recall@10 saturates).

Honest by construction: it reports whatever the numbers say.

Run:
    uv run python benchmarks/rrf-ab/run_rrf_ab_scale.py
Tune via env: RRF_SCALE_DOCS (default all), RRF_SCALE_QUESTIONS (default 100).
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from pathlib import Path

from pg_raggraph import GraphRAG

ROOT = Path(__file__).resolve().parents[2] / "benchmarks" / "musique"
DOCS_DIR = ROOT / "docs"
QUESTIONS = ROOT / "questions.json"

DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NAMESPACE = "rrf_ab_scale"

N_DOCS = int(os.environ.get("RRF_SCALE_DOCS", "0")) or None  # None = all
N_QUESTIONS = int(os.environ.get("RRF_SCALE_QUESTIONS", "100"))
TOP_K = 20  # fetch depth; metrics computed at k <= 10
RECALL_KS = (1, 5, 10)
NDCG_K = 10


def title_of(filename: str) -> str:
    return Path(filename).stem


def source_id(document_source: str | None) -> str | None:
    return Path(document_source).stem if document_source else None


def recall_hit(ranked_docs: list[str], gold: set[str], k: int) -> bool:
    return any(d in gold for d in ranked_docs[:k])


def reciprocal_rank(ranked_docs: list[str], gold: set[str]) -> float:
    for i, d in enumerate(ranked_docs, start=1):
        if d in gold:
            return 1.0 / i
    return 0.0


def _dcg(rels: list[float]) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


def ndcg(ranked_docs: list[str], gold: set[str], k: int) -> float:
    rels = [1.0 if d in gold else 0.0 for d in ranked_docs[:k]]
    ideal = [1.0] * min(len(gold), k) + [0.0] * max(0, k - len(gold))
    idcg = _dcg(ideal[:k])
    return (_dcg(rels) / idcg) if idcg > 0 else 0.0


def _select() -> tuple[list[dict], list[str]]:
    questions = json.loads(QUESTIONS.read_text())[:N_QUESTIONS]
    all_docs = sorted(p.name for p in DOCS_DIR.glob("*.md"))
    corpus = all_docs[:N_DOCS] if N_DOCS else all_docs
    corpus_set = set(corpus)
    # Keep only gold docs that are actually in the ingested corpus, so a missed
    # gold means "retrieval missed it", never "we never loaded it".
    for q in questions:
        q["_gold"] = {
            title_of(s["filename"]) for s in q["supporting"] if s["filename"] in corpus_set
        }
    questions = [q for q in questions if q["_gold"]]
    return questions, corpus


async def _ranked_docs(rag: GraphRAG, question: str, fusion: str) -> list[str]:
    """Top-k DISTINCT doc ids for a query, in rank order (best first)."""
    res = await rag.query(question, mode="naive", namespace=NAMESPACE, fusion=fusion)
    seen: list[str] = []
    for ch in res.chunks:
        d = source_id(ch.document_source)
        if d and d not in seen:
            seen.append(d)
    return seen[:TOP_K]


async def main() -> None:
    questions, corpus = _select()
    n_gold = sum(len(q["_gold"]) for q in questions)
    print("=" * 74)
    print("RRF A/B AT SCALE — linear vs rrf on full MuSiQue (naive, rank-sensitive)")
    print("=" * 74)
    print(f"corpus docs   : {len(corpus)}")
    print(f"questions     : {len(questions)} (with gold in corpus)")
    print(f"gold docs/q   : {n_gold / max(len(questions), 1):.1f} avg")
    print(f"fetch top_k   : {TOP_K}   metrics at recall@{RECALL_KS}, nDCG@{NDCG_K}, MRR")
    print()

    rag = GraphRAG(dsn=DSN, namespace=NAMESPACE, skip_extraction=True, top_k=TOP_K)
    await rag.connect()
    try:
        status = await rag.status(namespace=NAMESPACE)
        if status["documents"] < len(corpus):
            print(f"[ingest] {len(corpus)} docs (chunks + embeddings, no graph)...")
            await rag.delete(namespace=NAMESPACE)
            t0 = time.perf_counter()
            await rag.ingest([str(DOCS_DIR / f) for f in corpus], namespace=NAMESPACE)
            print(f"[ingest] done in {time.perf_counter() - t0:.1f}s")
        else:
            print(f"[ingest] namespace already has {status['documents']} docs — reusing")

        agg = {
            f: {"ndcg": 0.0, "mrr": 0.0, **{f"r{k}": 0 for k in RECALL_KS}}
            for f in ("linear", "rrf")
        }
        reordered = 0
        lat = {"linear": 0.0, "rrf": 0.0}

        for i, q in enumerate(questions, 1):
            gold = q["_gold"]
            ranked = {}
            for f in ("linear", "rrf"):
                t0 = time.perf_counter()
                ranked[f] = await _ranked_docs(rag, q["question"], f)
                lat[f] += (time.perf_counter() - t0) * 1000
                agg[f]["ndcg"] += ndcg(ranked[f], gold, NDCG_K)
                agg[f]["mrr"] += reciprocal_rank(ranked[f], gold)
                for k in RECALL_KS:
                    agg[f][f"r{k}"] += int(recall_hit(ranked[f], gold, k))
            if ranked["linear"][:NDCG_K] != ranked["rrf"][:NDCG_K]:
                reordered += 1
            if i % 20 == 0:
                print(f"  ...{i}/{len(questions)}")

        n = len(questions)
        print()
        print("=" * 74)
        print(f"RESULTS  (n={n} questions, {len(corpus)} docs)")
        print("=" * 74)
        print(f"{'metric':<12} {'linear':>10} {'rrf':>10} {'delta':>10}")
        print("-" * 44)

        def row(label, lin, rrf):
            print(f"{label:<12} {lin:>10.4f} {rrf:>10.4f} {rrf - lin:>+10.4f}")

        row(f"nDCG@{NDCG_K}", agg["linear"]["ndcg"] / n, agg["rrf"]["ndcg"] / n)
        row("MRR", agg["linear"]["mrr"] / n, agg["rrf"]["mrr"] / n)
        for k in RECALL_KS:
            row(f"recall@{k}", agg["linear"][f"r{k}"] / n, agg["rrf"][f"r{k}"] / n)
        print("-" * 44)
        print(f"top-{NDCG_K} reordered by RRF: {reordered}/{n} questions")
        print(f"latency/query: linear {lat['linear'] / n:.0f}ms  rrf {lat['rrf'] / n:.0f}ms")
        print()
        # Honest verdict line.
        d_ndcg = (agg["rrf"]["ndcg"] - agg["linear"]["ndcg"]) / n
        d_mrr = (agg["rrf"]["mrr"] - agg["linear"]["mrr"]) / n
        if d_ndcg > 0.005 or d_mrr > 0.005:
            verdict = "RRF AHEAD on rank-sensitive metrics"
        elif d_ndcg < -0.005 or d_mrr < -0.005:
            verdict = "LINEAR AHEAD on rank-sensitive metrics"
        else:
            verdict = "WASH (no meaningful rank-sensitive difference)"
        print(f"VERDICT: {verdict} (dNDCG={d_ndcg:+.4f}, dMRR={d_mrr:+.4f})")
    finally:
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
