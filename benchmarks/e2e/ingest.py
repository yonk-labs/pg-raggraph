"""Ingest layer — one namespace per (dataset, arm).

Stage once, sweep many. Re-running without --reingest short-circuits on
existing documents (content_hash dedup at the GraphRAG layer).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from benchmarks.e2e.config import (
    ARMS,
    PINNED_EMBEDDING_DIM,
    PINNED_EMBEDDING_MODEL,
)
from benchmarks.e2e.datasets._common import DatasetBundle
from pg_raggraph import GraphRAG


def namespace_for(dataset: str, arm: str) -> str:
    return f"bench_{dataset}_{arm}"


@dataclass
class IngestStats:
    dataset: str
    arm: str
    namespace: str
    wall_seconds: float
    documents: int
    chunks: int
    entities: int
    relationships: int
    skipped: bool  # True when --skip-ingest hit a populated namespace


def _build_graphrag(arm: str, dsn: str | None) -> GraphRAG:
    spec = ARMS[arm]
    kwargs: dict[str, Any] = {
        "embedding_model": PINNED_EMBEDDING_MODEL,
        "embedding_dim": PINNED_EMBEDDING_DIM,
        "fact_extractor": spec.fact_extractor,
    }
    if dsn:
        kwargs["dsn"] = dsn
    if not spec.requires_llm:
        # lede_spacy needs no LLM; force-empty the base URL so any default
        # localhost:11434 can't accidentally get hit during extraction.
        kwargs["llm_base_url"] = ""
    return GraphRAG(**kwargs)


async def stage(
    bundle: DatasetBundle,
    arm: str,
    *,
    dsn: str | None = None,
    reingest: bool = False,
    skip_ingest: bool = False,
) -> IngestStats:
    """Stage one (dataset, arm) into its namespace.

    If ``reingest`` is True, delete the namespace first. If ``skip_ingest``
    is True, never ingest — caller is asserting the namespace is already
    populated and just wants retrieval to run. If the namespace is empty
    AND ``skip_ingest`` is True, we still ingest (fail-loud would force the
    operator to drop --skip-ingest manually; that's worse than auto-staging).
    """
    ns = namespace_for(bundle.name, arm)
    rag = _build_graphrag(arm, dsn)
    await rag.connect()
    try:
        if reingest:
            await rag.delete(ns)

        existing = await rag.status(ns)
        if skip_ingest and existing["documents"] > 0:
            return IngestStats(
                dataset=bundle.name,
                arm=arm,
                namespace=ns,
                wall_seconds=0.0,
                documents=existing["documents"],
                chunks=existing["chunks"],
                entities=existing["entities"],
                relationships=existing.get("relationships", 0),
                skipped=True,
            )

        records = [
            {
                "text": d.text,
                "source_id": d.source_id,
                "metadata": d.metadata,
            }
            for d in bundle.corpus_docs
        ]

        t0 = time.perf_counter()
        await rag.ingest_records(records, namespace=ns)
        wall = time.perf_counter() - t0

        status = await rag.status(ns)
        return IngestStats(
            dataset=bundle.name,
            arm=arm,
            namespace=ns,
            wall_seconds=wall,
            documents=status["documents"],
            chunks=status["chunks"],
            entities=status["entities"],
            relationships=status.get("relationships", 0),
            skipped=False,
        )
    finally:
        await rag.close()
