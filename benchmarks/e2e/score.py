"""Scorers — span recall (floor), rank metrics, LLM-judge (primary).

Each scorer takes a Cell + ranked chunks and returns a dict of metric →
value. Combined into ``ScoredCell`` for downstream reporting.
"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import asdict, dataclass, field

from benchmarks.e2e.judge import Judge
from benchmarks.e2e.retrieve import Cell

# Default k for top-k cutoffs in span recall / nDCG.
TOP_K = 10

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _normalize(s: str) -> str:
    return " ".join(_WORD_RE.findall(s.lower()))


def _answer_matches(text: str, answers: list[str]) -> bool:
    norm = _normalize(text)
    for a in answers:
        if not a:
            continue
        if _normalize(a) in norm:
            return True
    return False


def _per_chunk_match(cell: Cell) -> list[bool]:
    """For each chunk in cell.chunks, whether ANY answer string is in it."""
    return [_answer_matches(c["content"], cell.answers) for c in cell.chunks[:TOP_K]]


def span_recall_at_k(cell: Cell) -> float:
    """1.0 if any of the top-k chunks contains any answer string, else 0.0.

    Set-membership, k-blind to position. The findings-doc floor metric.
    Per spec §6, never quoted alone.
    """
    if cell.error or not cell.chunks:
        return 0.0
    return 1.0 if any(_per_chunk_match(cell)) else 0.0


def hit_at_1(cell: Cell) -> float:
    if cell.error or not cell.chunks:
        return 0.0
    return 1.0 if _answer_matches(cell.chunks[0]["content"], cell.answers) else 0.0


def mrr(cell: Cell) -> float:
    """Mean reciprocal rank — first-hit rank in top-k."""
    if cell.error or not cell.chunks:
        return 0.0
    for i, c in enumerate(cell.chunks[:TOP_K]):
        if _answer_matches(c["content"], cell.answers):
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(cell: Cell, k: int = TOP_K) -> float:
    """Binary-gain nDCG@k against answer-containing chunks."""
    if cell.error or not cell.chunks:
        return 0.0
    gains = [1.0 if m else 0.0 for m in _per_chunk_match(cell)]
    if not any(gains):
        return 0.0
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains[:k]))
    # Ideal: all gains at top
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(int(sum(gains)), k)))
    return dcg / ideal if ideal > 0 else 0.0


@dataclass
class ScoredCell:
    """Cell + scorer outputs. The unit of the per-cell JSON output."""

    cell: dict  # asdict(Cell) — keep full provenance
    span_recall: float
    hit_at_1: float
    mrr: float
    ndcg: float
    judge_score: float | None  # 1.0 correct, 0.0 wrong, None when judge skipped
    judge_provider: str | None
    judge_answer: str | None
    judge_reason: str | None
    metrics_extra: dict = field(default_factory=dict)


async def score_cells(
    cells: list[Cell],
    *,
    judge: Judge | None = None,
    judge_concurrency: int = 4,
) -> list[ScoredCell]:
    """Apply all scorers. Judge is awaited last with bounded concurrency."""
    deterministic: list[ScoredCell] = [
        ScoredCell(
            cell=_cell_to_dict(c),
            span_recall=span_recall_at_k(c),
            hit_at_1=hit_at_1(c),
            mrr=mrr(c),
            ndcg=ndcg_at_k(c),
            judge_score=None,
            judge_provider=None,
            judge_answer=None,
            judge_reason=None,
        )
        for c in cells
    ]
    if judge is None:
        return deterministic

    sem = asyncio.Semaphore(judge_concurrency)

    async def _judge_one(idx: int, c: Cell) -> None:
        async with sem:
            if c.error or not c.chunks:
                deterministic[idx].judge_score = 0.0
                deterministic[idx].judge_provider = judge.provider_name
                deterministic[idx].judge_reason = "no_chunks_or_error"
                return
            result = await judge.judge(
                question=c.question,
                context_chunks=[ch["content"] for ch in c.chunks[:TOP_K]],
                reference_answers=c.answers,
            )
            deterministic[idx].judge_score = result.score
            deterministic[idx].judge_provider = result.provider
            deterministic[idx].judge_answer = result.answer
            deterministic[idx].judge_reason = result.reason

    await asyncio.gather(*(_judge_one(i, c) for i, c in enumerate(cells)))
    return deterministic


def _cell_to_dict(c: Cell) -> dict:
    # Trim chunk content for the per-cell JSON — keep the metadata, ditch the
    # full text (it can be megabytes per cell on news corpora).
    d = asdict(c)
    d["chunks"] = [
        {
            **{k: v for k, v in ch.items() if k != "content"},
            "content_preview": (ch.get("content") or "")[:400],
        }
        for ch in d["chunks"]
    ]
    return d
