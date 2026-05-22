"""Retrieval ladder runner — sweeps a single namespace through every rung.

One GraphRAG instance per (dataset, arm). Per query, run every ladder rung
and record latency + chunks. Returns per-query-per-rung Cells for scoring.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from benchmarks.e2e.config import (
    ARMS,
    LADDER,
    PINNED_EMBEDDING_DIM,
    PINNED_EMBEDDING_MODEL,
)
from benchmarks.e2e.datasets._common import DatasetBundle, Query
from pg_raggraph import GraphRAG
from pg_raggraph import __version__ as PGRG_VERSION


@dataclass
class Cell:
    """One (dataset, arm, rung, query) result before scoring."""

    dataset: str
    arm: str
    namespace: str
    rung: str
    qid: str
    question: str
    answers: list[str]
    strata: dict[str, str]
    chunks: list[dict] = field(default_factory=list)  # {content, score, document_source, chunk_id}
    entities: list[str] = field(default_factory=list)
    n_candidates: int = 0
    latency_ms: float = 0.0
    error: str | None = None
    git_sha: str = ""
    pgrg_version: str = PGRG_VERSION
    timestamp: str = ""


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


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
        kwargs["llm_base_url"] = ""
    return GraphRAG(**kwargs)


def _filter_ladder(modes: list[str] | None) -> list[tuple[str, dict]]:
    if not modes:
        return LADDER
    wanted = set(modes)
    return [(label, kw) for (label, kw) in LADDER if label in wanted]


async def sweep(
    bundle: DatasetBundle,
    arm: str,
    namespace: str,
    *,
    dsn: str | None = None,
    modes: list[str] | None = None,
) -> list[Cell]:
    """Run the (filtered) ladder against every query in the bundle.

    Returns one Cell per (query, rung). Errors during a single query
    are recorded on the cell (``error`` set) so the sweep doesn't abort
    on a single failure.
    """
    rag = _build_graphrag(arm, dsn)
    await rag.connect()
    cells: list[Cell] = []
    sha = _git_sha()
    ts = datetime.now(timezone.utc).isoformat()
    ladder = _filter_ladder(modes)
    try:
        for q in bundle.queries:
            for rung_label, mode_kwargs in ladder:
                cell = await _run_one(rag, bundle, arm, namespace, q, rung_label, mode_kwargs)
                cell.git_sha = sha
                cell.timestamp = ts
                cells.append(cell)
    finally:
        await rag.close()
    return cells


async def _run_one(
    rag: GraphRAG,
    bundle: DatasetBundle,
    arm: str,
    namespace: str,
    q: Query,
    rung: str,
    mode_kwargs: dict,
) -> Cell:
    t0 = time.perf_counter()
    try:
        result = await rag.query(q.question, namespace=namespace, **mode_kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return Cell(
            dataset=bundle.name,
            arm=arm,
            namespace=namespace,
            rung=rung,
            qid=q.qid,
            question=q.question,
            answers=list(q.answers),
            strata=dict(q.strata),
            chunks=[
                {
                    "content": c.content,
                    "score": c.score,
                    "document_source": c.document_source,
                    "chunk_id": c.chunk_id,
                }
                for c in result.chunks
            ],
            entities=[e.name for e in result.entities],
            n_candidates=len(result.chunks),
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return Cell(
            dataset=bundle.name,
            arm=arm,
            namespace=namespace,
            rung=rung,
            qid=q.qid,
            question=q.question,
            answers=list(q.answers),
            strata=dict(q.strata),
            error=f"{type(exc).__name__}: {exc}",
            latency_ms=latency_ms,
        )
