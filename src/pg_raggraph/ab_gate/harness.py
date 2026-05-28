"""A/B Gate retrieval harness — #48.

One entry point: ``run_harness_mode(rag, corpus_id, mode, gold_questions, top_k)``
returning an :class:`ABRunnerOutput`. Three modes:

- ``naive_vector`` — pure ANN over chunks, fact rows excluded per chunkshop §4.2.
- ``graph_leg`` — entity-resolve question terms via #47, walk fact triples and
  cooccur edges, return the episode chunks carrying those facts.
- ``hybrid`` — optional 50/50 blend. SC-007 explicitly allows shipping with
  ``NotImplementedError`` if scope grows.

The harness reads the chunkshop-emitted row set verbatim — no shape
transformation, no re-indexing. Per the brief's P1 constraint.

Question-term encoding (used by ``graph_leg``) goes through ``lede_spacy``'s
NER backend so ingest and query share the same entity definition. A
whitespace+stoplist fallback covers environments where lede_spacy isn't
installed (operator sees a warning, not a crash).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Literal

from pg_raggraph.ab_gate.io import (
    ABCaseResult,
    ABRetrievedItem,
    ABRunnerOutput,
    GoldQuestion,
)

if TYPE_CHECKING:
    from pg_raggraph import GraphRAG

logger = logging.getLogger("pg_raggraph.ab_gate.harness")

Mode = Literal["naive_vector", "graph_leg", "hybrid"]


# SQL for naive_vector mode.
#
# Mirrors the shape of _build_naive_vector_first in retrieval.py:366, stripped
# of the evolution / weighted-rerank logic the production retriever needs.
# The single new clause is chunkshop §4.2:
#
#     AND c.metadata->>'kind' IS DISTINCT FROM 'fact'
#
# DC-002 enforces ``IS DISTINCT FROM``, not ``!=`` — those differ on NULL.
# A chunk with no 'kind' metadata key (legacy / non-chunkshop ingest) MUST
# still be returned; ``!= 'fact'`` would drop it.
_NAIVE_VECTOR_SQL = """
SELECT
    c.id,
    COALESCE(c.embedded_content, c.content) AS content,
    d.source_path,
    1 - (c.embedding <=> %(embedding)s::vector) AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.namespace = %(namespace)s
  AND c.metadata->>'kind' IS DISTINCT FROM 'fact'
ORDER BY c.embedding <=> %(embedding)s::vector
LIMIT %(top_k)s
"""


async def _run_naive_vector(
    rag: "GraphRAG",
    *,
    corpus_id: str,
    question: str,
    top_k: int,
) -> list[ABRetrievedItem]:
    """Pure ANN over chunks, excluding fact rows.

    Reuses the rag's configured embedder so dims line up with the
    ingested chunks. Returns 1-indexed ABRetrievedItems ordered by
    score DESC.
    """
    embedder = rag._get_embedder()
    [embedding] = await embedder.embed([question])
    rows = await rag.db.fetch_all(
        _NAIVE_VECTOR_SQL,
        {"embedding": embedding, "namespace": corpus_id, "top_k": top_k},
    )
    items: list[ABRetrievedItem] = []
    for rank, row in enumerate(rows, start=1):
        source = row["source_path"] or f"{corpus_id}:chunk:{row['id']}"
        items.append(
            ABRetrievedItem(
                rank=rank,
                source=source,
                score=float(row["score"]),
                content_snippet=row["content"] or "",
            )
        )
    return items


async def run_harness_mode(
    rag: "GraphRAG",
    *,
    corpus_id: str,
    mode: Mode,
    gold_questions: list[GoldQuestion],
    top_k: int = 10,
) -> ABRunnerOutput:
    """Run one (corpus, mode) cell of the A/B matrix.

    See module docstring for mode semantics. Returns one ABCaseResult
    per input GoldQuestion in the same order. Latency is measured per
    case — only the retrieval call, not setup like entity resolution
    (see SC-014 / DC-FINAL).
    """
    results: list[ABCaseResult] = []
    for gold in gold_questions:
        t0 = time.monotonic()
        if mode == "naive_vector":
            retrieved = await _run_naive_vector(
                rag, corpus_id=corpus_id, question=gold.question, top_k=top_k
            )
        elif mode == "graph_leg":
            raise NotImplementedError("graph_leg mode lands in Task 4")
        elif mode == "hybrid":
            raise NotImplementedError("hybrid mode lands in Task 6 (or stays NotImplementedError)")
        else:
            raise ValueError(f"unknown harness mode: {mode!r}")
        latency_ms = (time.monotonic() - t0) * 1000.0
        results.append(
            ABCaseResult(
                question_id=gold.id,
                question=gold.question,
                gold_answer=gold.gold_answer,
                retrieved=retrieved,
                latency_ms=latency_ms,
            )
        )
    return ABRunnerOutput(corpus_id=corpus_id, mode=mode, results=results)
