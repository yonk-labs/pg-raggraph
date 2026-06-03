"""3-way A/B: linear vs CAPTIVE rrf vs PROPER rrf on full MuSiQue (issue #57).

Motivated by the prior-art research (research/rrf-fusion-vs-prior-art.md): every
production system fuses two INDEPENDENT retriever lists, where a doc absent from
a leg gets zero from that leg. pg-raggraph's shipped naive RRF instead ranks one
vector-seeded candidate pool two ways, which (a) keeps BM25 captive to the vector
pool and (b) hands ~40-65% zero-BM25 docs a tied, noisy rank.

This script measures all three on the SAME 1700-doc corpus:
  - linear        : the shipped default (w_sem*cos + w_bm25*ts_rank)
  - rrf (captive) : the shipped RRF (vector top-200 ranked two ways)
  - rrf (proper)  : independent vector top-N + BM25 top-N, FULL OUTER JOIN,
                    COALESCE-to-zero — the way Elasticsearch/OpenSearch/pgvector do it

Reuses the rrf_ab_scale namespace if already populated. Rank-sensitive metrics.

Run:  uv run python benchmarks/rrf-ab/run_rrf_ab_proper.py
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from pathlib import Path

from pg_raggraph import GraphRAG
from pg_raggraph.embedding import get_embedding_provider
from pg_raggraph.retrieval import _to_or_tsquery

ROOT = Path(__file__).resolve().parents[2] / "benchmarks" / "musique"
DOCS_DIR = ROOT / "docs"
QUESTIONS = ROOT / "questions.json"

DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NAMESPACE = "rrf_ab_scale"  # reuse the scale corpus

N_QUESTIONS = int(os.environ.get("RRF_SCALE_QUESTIONS", "100"))
LEG_N = 100  # per-leg retrieval depth for proper RRF (each retriever's own top-N)
TOP_K = 20
RECALL_KS = (1, 5, 10)
NDCG_K = 10
RRF_K = 60
W_SEM, W_BM25 = 0.5, 0.2  # same weights all three modes use, for a fair fight

PROPER_RRF_SQL = """
WITH vec AS (
    SELECT c.id,
           row_number() OVER (ORDER BY c.embedding <=> %(embedding)s::vector) AS vec_rank
    FROM chunks c JOIN documents d ON d.id = c.document_id
    WHERE d.namespace = %(ns)s
    ORDER BY c.embedding <=> %(embedding)s::vector
    LIMIT %(leg_n)s
),
bm AS (
    SELECT c.id,
           row_number() OVER (
               ORDER BY ts_rank(c.search_vector, to_tsquery('english', %(tsquery)s)) DESC
           ) AS bm25_rank
    FROM chunks c JOIN documents d ON d.id = c.document_id
    WHERE d.namespace = %(ns)s
      AND c.search_vector @@ to_tsquery('english', %(tsquery)s)
    ORDER BY ts_rank(c.search_vector, to_tsquery('english', %(tsquery)s)) DESC
    LIMIT %(leg_n)s
)
SELECT d.source_path AS source_path,
       COALESCE(%(w_sem)s / (%(rrf_k)s + v.vec_rank), 0)
     + COALESCE(%(w_bm25)s / (%(rrf_k)s + bm.bm25_rank), 0) AS score
FROM vec v
FULL OUTER JOIN bm ON v.id = bm.id
JOIN chunks c ON c.id = COALESCE(v.id, bm.id)
JOIN documents d ON d.id = c.document_id
ORDER BY score DESC
LIMIT %(top_k)s
"""

MODES = ("linear", "rrf", "proper")


def title_of(fn: str) -> str:
    return Path(fn).stem


def source_id(src: str | None) -> str | None:
    return Path(src).stem if src else None


def recall_hit(docs: list[str], gold: set[str], k: int) -> bool:
    return any(d in gold for d in docs[:k])


def rr(docs: list[str], gold: set[str]) -> float:
    for i, d in enumerate(docs, 1):
        if d in gold:
            return 1.0 / i
    return 0.0


def _dcg(rels: list[float]) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


def ndcg(docs: list[str], gold: set[str], k: int) -> float:
    rels = [1.0 if d in gold else 0.0 for d in docs[:k]]
    ideal = [1.0] * min(len(gold), k) + [0.0] * max(0, k - len(gold))
    idcg = _dcg(ideal[:k])
    return (_dcg(rels) / idcg) if idcg > 0 else 0.0


def _dedupe(rows_or_chunks) -> list[str]:
    seen: list[str] = []
    for r in rows_or_chunks:
        d = source_id(r["source_path"] if isinstance(r, dict) else r.document_source)
        if d and d not in seen:
            seen.append(d)
    return seen[:TOP_K]


async def main() -> None:
    questions = json.loads(QUESTIONS.read_text())[:N_QUESTIONS]
    rag = GraphRAG(dsn=DSN, namespace=NAMESPACE, skip_extraction=True, top_k=TOP_K)
    await rag.connect()
    try:
        status = await rag.status(namespace=NAMESPACE)
        n_docs = status["documents"]
        print("=" * 78)
        print("RRF 3-way — linear vs captive-rrf vs PROPER-rrf (full MuSiQue, naive)")
        print("=" * 78)
        print(f"corpus docs : {n_docs}   (reusing rrf_ab_scale namespace)")
        if n_docs < 1000:
            print("WARNING: corpus looks small/empty — run run_rrf_ab_scale.py first to ingest.")
        emb = get_embedding_provider(rag.config)

        # keep only questions whose gold is in the corpus
        qset = []
        for q in questions:
            gold = {title_of(s["filename"]) for s in q["supporting"]}
            q["_gold"] = gold
            qset.append(q)

        agg = {m: {"ndcg": 0.0, "mrr": 0.0, **{f"r{k}": 0 for k in RECALL_KS}} for m in MODES}
        lat = {m: 0.0 for m in MODES}
        n = 0
        print(f"questions   : {len(qset)}   leg_n(proper)={LEG_N}  rrf_k={RRF_K}")
        print()
        for i, q in enumerate(qset, 1):
            gold = q["_gold"]
            if not gold:
                continue
            n += 1
            q_emb = (await emb.embed([q["question"]]))[0]
            tsq = _to_or_tsquery(q["question"])
            ranked = {}
            # library modes
            for m in ("linear", "rrf"):
                t0 = time.perf_counter()
                res = await rag.query(q["question"], mode="naive", namespace=NAMESPACE, fusion=m)
                lat[m] += (time.perf_counter() - t0) * 1000
                ranked[m] = _dedupe(res.chunks)
            # proper RRF via direct SQL
            t0 = time.perf_counter()
            rows = await rag.db.fetch_all(
                PROPER_RRF_SQL,
                {
                    "embedding": q_emb,
                    "tsquery": tsq,
                    "ns": NAMESPACE,
                    "leg_n": LEG_N,
                    "w_sem": W_SEM,
                    "w_bm25": W_BM25,
                    "rrf_k": RRF_K,
                    "top_k": TOP_K,
                },
            )
            lat["proper"] += (time.perf_counter() - t0) * 1000
            ranked["proper"] = _dedupe(rows)

            for m in MODES:
                agg[m]["ndcg"] += ndcg(ranked[m], gold, NDCG_K)
                agg[m]["mrr"] += rr(ranked[m], gold)
                for k in RECALL_KS:
                    agg[m][f"r{k}"] += int(recall_hit(ranked[m], gold, k))
            if i % 25 == 0:
                print(f"  ...{i}/{len(qset)}")

        print()
        print("=" * 78)
        print(f"RESULTS  (n={n} questions, {n_docs} docs)")
        print("=" * 78)
        print(f"{'metric':<12} {'linear':>11} {'rrf(captive)':>13} {'rrf(proper)':>13}")
        print("-" * 54)

        def line(label, key):
            print(
                f"{label:<12} {agg['linear'][key] / n:>11.4f} "
                f"{agg['rrf'][key] / n:>13.4f} {agg['proper'][key] / n:>13.4f}"
            )

        line(f"nDCG@{NDCG_K}", "ndcg")
        line("MRR", "mrr")
        for k in RECALL_KS:
            line(f"recall@{k}", f"r{k}")
        print("-" * 54)
        print(
            f"latency/q ms: linear {lat['linear'] / n:.0f}  "
            f"captive {lat['rrf'] / n:.0f}  proper {lat['proper'] / n:.0f}"
        )
        print()
        base = agg["linear"]["ndcg"] / n
        for m in ("rrf", "proper"):
            d = agg[m]["ndcg"] / n - base
            print(f"  {m:<8} nDCG vs linear: {d:+.4f}")
    finally:
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
