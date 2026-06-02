"""A/B benchmark: linear vs RRF fusion on MuSiQue naive retrieval.

Self-contained runner for issue #57 / SC-008. Measures whether RRF
(reciprocal-rank fusion) changes naive-mode retrieval quality versus the
default linear (weighted-sum) fusion. naive mode runs both a vector leg
(pgvector cosine) and a BM25 leg (PostgreSQL full-text) — exactly where a
scale-free rank fusion like RRF could matter.

Deterministic retrieval metrics only (no LLM judge):
  * recall@k  — fraction of questions where >=1 gold supporting doc appears
    in the top-k retrieved chunks.
  * rank-overlap — mean Jaccard similarity of the top-k *doc* sets returned
    by linear vs rrf for the same question (1.0 = identical ranking sets).

Bounded corpus: a subset of questions plus their gold supporting docs and a
capped pool of distractor docs, ingested into a throwaway ``rrf_ab``
namespace. Re-runnable: if the namespace already has the expected doc count
the ingest is skipped; otherwise it is wiped and rebuilt.

Run:
    uv run python benchmarks/rrf-ab/run_rrf_ab.py
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from pathlib import Path

from pg_raggraph import GraphRAG

ROOT = Path(__file__).resolve().parents[2] / "benchmarks" / "musique"
DOCS_DIR = ROOT / "docs"
QUESTIONS = ROOT / "questions.json"

DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NAMESPACE = "rrf_ab"

# Scope bounds — keep CPU embedding (bge-small) work small.
N_QUESTIONS = 25  # subset of MuSiQue questions to evaluate
DISTRACTOR_CAP = 120  # extra non-gold docs sprinkled in as noise
TOP_K = 10  # config default; rank-overlap uses this (full retrieved set)
RECALL_KS = (3, 5, 10)  # report recall at several cutoffs (recall@10 saturates)
SEED = 42


def _title_of(filename: str) -> str:
    """Map a docs/ filename to the gold doc identity used for matching.

    We match on filename stem (e.g. ``Partition-of-India--2``) since gold
    ``supporting`` entries carry the disambiguated filename, and ingested
    ``document_source`` is the file path.
    """
    return Path(filename).stem


def _source_id(document_source: str | None) -> str | None:
    if not document_source:
        return None
    return Path(document_source).stem


def _select_corpus() -> tuple[list[dict], list[str]]:
    """Pick N questions, gather their gold docs + a capped distractor pool."""
    questions = json.loads(QUESTIONS.read_text())
    rng = random.Random(SEED)
    rng.shuffle(questions)
    chosen = questions[:N_QUESTIONS]

    gold_files: set[str] = set()
    for q in chosen:
        for s in q["supporting"]:
            gold_files.add(s["filename"])

    all_docs = sorted(p.name for p in DOCS_DIR.glob("*.md"))
    non_gold = [d for d in all_docs if d not in gold_files]
    rng.shuffle(non_gold)
    distractors = non_gold[:DISTRACTOR_CAP]

    corpus_files = sorted(gold_files | set(distractors))
    return chosen, corpus_files


async def _ensure_ingested(rag: GraphRAG, corpus_files: list[str]) -> int:
    paths = [str(DOCS_DIR / f) for f in corpus_files]
    status = await rag.status(NAMESPACE)
    have = status.get("documents", 0)
    want = len(paths)
    if have == want:
        print(f"[ingest] namespace={NAMESPACE} already has {have} docs — skipping ingest")
        return have
    if have:
        print(f"[ingest] namespace has {have} docs, expected {want} — wiping and re-ingesting")
        await rag.delete(namespace=NAMESPACE)
    t0 = time.perf_counter()
    print(f"[ingest] ingesting {want} docs into namespace={NAMESPACE} (bge-small CPU embeddings)...")
    # defer_extraction: naive mode needs only chunks + embeddings, no graph.
    await rag.ingest(paths, namespace=NAMESPACE)
    status = await rag.status(NAMESPACE)
    print(
        f"[ingest] done in {time.perf_counter() - t0:.1f}s: "
        f"{status['documents']} docs, {status['chunks']} chunks"
    )
    return status["documents"]


async def _topk_doc_ids(rag: GraphRAG, question: str, fusion: str) -> list[str]:
    result = await rag.query(question, mode="naive", namespace=NAMESPACE, fusion=fusion)
    ids: list[str] = []
    for ch in result.chunks[:TOP_K]:
        sid = _source_id(ch.document_source)
        if sid is not None:
            ids.append(sid)
    return ids


def _recall_hit(retrieved: list[str], gold: set[str], k: int) -> bool:
    return any(r in gold for r in retrieved[:k])


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    if not union:
        return 1.0
    return len(sa & sb) / len(union)


async def main() -> None:
    chosen, corpus_files = _select_corpus()
    n_gold = len({f for q in chosen for f in (s["filename"] for s in q["supporting"])})
    print("=" * 72)
    print("RRF A/B benchmark — linear vs rrf fusion on MuSiQue naive retrieval")
    print("=" * 72)
    print(f"questions       : {len(chosen)}")
    print(f"corpus docs     : {len(corpus_files)} ({n_gold} gold + distractors)")
    print(f"top_k           : {TOP_K}")
    print(f"seed            : {SEED}")
    print()

    rag = GraphRAG(dsn=DSN, namespace=NAMESPACE)
    await rag.connect()
    try:
        await _ensure_ingested(rag, corpus_files)

        lin_hits = {k: 0 for k in RECALL_KS}
        rrf_hits = {k: 0 for k in RECALL_KS}
        overlaps: list[float] = []
        lin_ms = 0.0
        rrf_ms = 0.0

        print()
        print(f"{'#':>3}  {'hop':>5}  {'lin@3':>5}  {'rrf@3':>5}  {'jaccard':>7}")
        print("-" * 40)
        for i, q in enumerate(chosen, 1):
            gold = {_title_of(s["filename"]) for s in q["supporting"]}

            t0 = time.perf_counter()
            lin = await _topk_doc_ids(rag, q["question"], "linear")
            lin_ms += (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            rrf = await _topk_doc_ids(rag, q["question"], "rrf")
            rrf_ms += (time.perf_counter() - t0) * 1000

            for k in RECALL_KS:
                lin_hits[k] += int(_recall_hit(lin, gold, k))
                rrf_hits[k] += int(_recall_hit(rrf, gold, k))
            jac = _jaccard(lin, rrf)
            overlaps.append(jac)

            print(
                f"{i:>3}  {q['hop_class']:>5}  "
                f"{'HIT' if _recall_hit(lin, gold, 3) else '-':>5}  "
                f"{'HIT' if _recall_hit(rrf, gold, 3) else '-':>5}  {jac:>7.2f}"
            )

        n = len(chosen)
        print()
        print("=" * 72)
        print("RESULTS")
        print("=" * 72)
        for k in RECALL_KS:
            lh, rh = lin_hits[k], rrf_hits[k]
            print(
                f"recall@{k:<2}  linear {lh}/{n}={lh / n:.3f}   "
                f"rrf {rh}/{n}={rh / n:.3f}   delta {(rh - lh) / n:+.3f}"
            )
        print()
        print(f"mean rank-overlap (Jaccard@{TOP_K}): {sum(overlaps) / n:.3f}")
        print(f"identical-ranking questions: {sum(1 for j in overlaps if j == 1.0)}/{n}")
        print()
        print(f"avg latency  linear: {lin_ms / n:.1f} ms   rrf: {rrf_ms / n:.1f} ms")
        print("=" * 72)
    finally:
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
