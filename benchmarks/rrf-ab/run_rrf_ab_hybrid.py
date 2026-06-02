"""A/B: linear vs RRF fusion on MuSiQue **hybrid** retrieval (issue #57).

The naive A/B (``run_rrf_ab.py``) could run without an LLM because naive needs
only chunks + embeddings. Hybrid needs the entity/relationship graph, which
requires LLM extraction at ingest. This runner points extraction at a LAN
OpenAI-compatible endpoint (default the gemma server on :8000) and ingests a
SMALL corpus WITH extraction so a real graph exists, then compares
``fusion="linear"`` vs ``fusion="rrf"`` under ``mode="hybrid"``.

Deterministic retrieval metrics only (recall@k vs gold supporting docs +
linear-vs-rrf rank overlap). Bounded corpus — extraction via a 26B model is
slow, so this is intentionally tiny (a real number, not scale).

Run:
    PGRG_LLM_BASE_URL=http://192.168.1.133:8000/v1 \
    PGRG_LLM_MODEL=cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit \
    uv run python benchmarks/rrf-ab/run_rrf_ab_hybrid.py
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
NAMESPACE = "rrf_ab_hybrid"

LLM_BASE_URL = os.environ.get("PGRG_LLM_BASE_URL", "http://192.168.1.133:8000/v1")
LLM_MODEL = os.environ.get("PGRG_LLM_MODEL", "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit")

# Tiny — extraction via a 26B model is the bottleneck, not retrieval.
N_QUESTIONS = 6
DISTRACTOR_CAP = 15
TOP_K = 10
RECALL_KS = (3, 5, 10)
SEED = 42


def title_of(filename: str) -> str:
    return Path(filename).stem


def source_id(document_source: str | None) -> str | None:
    return Path(document_source).stem if document_source else None


def recall_hit(retrieved: list[str], gold: set[str], k: int) -> bool:
    return any(r in gold for r in retrieved[:k])


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    union = sa | sb
    return 1.0 if not union else len(sa & sb) / len(union)


def _select_corpus() -> tuple[list[dict], list[str]]:
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


async def _topk_doc_ids(rag: GraphRAG, question: str, fusion: str) -> list[str]:
    result = await rag.query(question, mode="hybrid", namespace=NAMESPACE, fusion=fusion)
    ids: list[str] = []
    for ch in result.chunks[:TOP_K]:
        sid = source_id(ch.document_source)
        if sid is not None:
            ids.append(sid)
    return ids


async def main() -> None:
    chosen, corpus_files = _select_corpus()
    n_gold = len({f for q in chosen for f in (s["filename"] for s in q["supporting"])})
    print("=" * 72)
    print("RRF A/B — linear vs rrf on MuSiQue HYBRID retrieval (real graph)")
    print("=" * 72)
    print(f"questions     : {len(chosen)}")
    print(f"corpus docs   : {len(corpus_files)} ({n_gold} gold + distractors)")
    print(f"extraction LLM: {LLM_MODEL} @ {LLM_BASE_URL}")
    print(f"top_k         : {TOP_K}   seed: {SEED}")
    print()

    rag = GraphRAG(
        dsn=DSN,
        namespace=NAMESPACE,
        llm_base_url=LLM_BASE_URL,
        llm_model=LLM_MODEL,
        llm_api_key=os.environ.get("PGRG_LLM_API_KEY", "local"),
    )
    await rag.connect()
    try:
        # Always wipe + re-ingest WITH extraction so the graph is real.
        await rag.delete(namespace=NAMESPACE)
        paths = [str(DOCS_DIR / f) for f in corpus_files]
        print(f"[ingest] {len(paths)} docs WITH extraction (slow — 26B model)...")
        t0 = time.perf_counter()
        await rag.ingest(paths, namespace=NAMESPACE)
        print(f"[ingest] done in {time.perf_counter() - t0:.1f}s")

        ents = await rag.db.fetch_all(
            "SELECT count(*) AS n FROM entities WHERE namespace = %(ns)s", {"ns": NAMESPACE}
        )
        rels = await rag.db.fetch_all(
            "SELECT count(*) AS n FROM relationships WHERE namespace = %(ns)s", {"ns": NAMESPACE}
        )
        n_ent, n_rel = ents[0]["n"], rels[0]["n"]
        print(f"[graph] entities={n_ent}  relationships={n_rel}")
        if n_ent == 0 or n_rel == 0:
            print("[graph] EMPTY — extraction failed; hybrid A/B is meaningless. Aborting.")
            return

        lin_hits = {k: 0 for k in RECALL_KS}
        rrf_hits = {k: 0 for k in RECALL_KS}
        overlaps: list[float] = []
        print()
        print(f"{'#':>3}  {'hop':>5}  {'lin@3':>5}  {'rrf@3':>5}  {'jaccard':>7}")
        print("-" * 40)
        for i, q in enumerate(chosen, 1):
            gold = {title_of(s["filename"]) for s in q["supporting"]}
            lin = await _topk_doc_ids(rag, q["question"], "linear")
            rrf = await _topk_doc_ids(rag, q["question"], "rrf")
            for k in RECALL_KS:
                lin_hits[k] += int(recall_hit(lin, gold, k))
                rrf_hits[k] += int(recall_hit(rrf, gold, k))
            jac = jaccard(lin, rrf)
            overlaps.append(jac)
            print(
                f"{i:>3}  {q['hop_class']:>5}  "
                f"{'HIT' if recall_hit(lin, gold, 3) else '-':>5}  "
                f"{'HIT' if recall_hit(rrf, gold, 3) else '-':>5}  {jac:>7.2f}"
            )

        n = len(chosen)
        print()
        print("=" * 72)
        print("RESULTS (hybrid)")
        print("=" * 72)
        for k in RECALL_KS:
            lh, rh = lin_hits[k], rrf_hits[k]
            print(
                f"recall@{k:<2}  linear {lh}/{n}={lh / n:.3f}   "
                f"rrf {rh}/{n}={rh / n:.3f}   delta {(rh - lh) / n:+.3f}"
            )
        print(f"\nmean rank-overlap (Jaccard@{TOP_K}): {sum(overlaps) / len(overlaps):.3f}")
        print(f"reordered (jaccard<1.0): {sum(1 for j in overlaps if j < 1.0)}/{n} questions")
    finally:
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
