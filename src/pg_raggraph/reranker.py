"""Cross-encoder reranking for retrieval results.

Adds a CPU-only reranking pass after the vector + BM25 retrieval. The
reranker scores each (question, chunk) pair with a cross-encoder model
and re-orders the top-k. Standard recipe in modern RAG systems.

Cost profile:
  - Zero added per-query LLM cost (model is local, CPU)
  - +30-80 ms p50 latency on top of retrieval (model + candidate count
    dependent)
  - Lift on retrieval-dependent metrics: +3-7 pp on the published
    benchmarks; per-corpus variance applies.

Usage pattern: caller fetches `top_k * rerank_factor` candidates from
SQL, then passes them through `Reranker.apply()` which returns a
QueryResult trimmed to `top_k` reordered chunks.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from pg_raggraph.models import QueryResult

logger = logging.getLogger("pg_raggraph.reranker")


class Reranker(Protocol):
    """Cross-encoder reranker contract.

    Implementations score each (question, chunk_content) pair and
    return scores aligned with the input chunk order.
    """

    async def score(self, question: str, chunk_texts: list[str]) -> list[float]: ...


class FastEmbedReranker:
    """fastembed-backed cross-encoder reranker.

    Default model is `BAAI/bge-reranker-base` (~1 GB, MIT-licensed,
    CPU-friendly via onnxruntime). Smaller alternatives that fastembed
    supports include `Xenova/ms-marco-MiniLM-L-6-v2` (80 MB, faster but
    slightly less accurate).

    The model is loaded lazily on first use to avoid paying the
    download / load cost when reranking is not enabled.
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        self.model_name = model_name
        self._model = None  # lazy

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as e:
            raise ImportError(
                "Reranking requires fastembed's cross-encoder support. "
                "fastembed is already a base dependency, but the cross-encoder "
                "submodule may be missing in older versions. "
                "Try: pip install --upgrade 'fastembed>=0.4'. "
                f"Original error: {e}"
            ) from e

        logger.info(f"Loading reranker model: {self.model_name}")
        self._model = TextCrossEncoder(model_name=self.model_name)

    def _score_sync(self, question: str, chunk_texts: list[str]) -> list[float]:
        self._load()
        # rerank() returns a generator of float scores aligned with input order
        return list(self._model.rerank(question, chunk_texts))

    async def score(self, question: str, chunk_texts: list[str]) -> list[float]:
        """Score each (question, chunk) pair. Returns scores aligned with input."""
        if not chunk_texts:
            return []
        # Run the CPU-bound model in a worker thread so it doesn't starve
        # the event loop.
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._score_sync, question, chunk_texts)


async def apply_reranker(
    reranker: Reranker,
    question: str,
    result: QueryResult,
    top_k: int,
) -> QueryResult:
    """Re-rank a QueryResult's chunks and trim to top_k.

    Mutates ``result`` in place: chunks are reordered, each chunk's
    ``score`` is replaced with the reranker score, and the list is
    truncated to top_k. Entities and relationships are left untouched
    (the same entity/rel set is still associated with the surviving
    chunks at the document level).
    """
    if not result.chunks:
        return result

    chunk_texts = [c.content for c in result.chunks]
    scores = await reranker.score(question, chunk_texts)

    # Pair each chunk with its new score, sort descending, trim
    reranked = sorted(zip(result.chunks, scores), key=lambda pair: pair[1], reverse=True)[:top_k]

    new_chunks = []
    for chunk, score in reranked:
        chunk.score = float(score)
        new_chunks.append(chunk)

    result.chunks = new_chunks
    return result
