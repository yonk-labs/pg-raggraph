"""A/B-gate I/O dataclasses — runner output (SC-023) + verdict shape (SC-013).

These types are the contracts between #49 (A/B runner) and #50 (results writer).
The shapes are locked by the mission brief and must not drift without a brief
amendment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# ============================================================================
# A/B runner output — what #49 emits, what #50 consumes (SC-023).
# ============================================================================


@dataclass(frozen=True)
class ABRetrievedItem:
    """One retrieved chunk in a #49 result row.

    Attributes
    ----------
    rank:
        1-indexed position in the retrieved list. ``rank=1`` is the top hit.
    source:
        Stable identifier of the source. Convention: ``source_path`` for
        file-backed corpora, ``namespace:doc_id`` for namespace-tracked
        ingests. The verdict writer treats this as opaque — recall@K only
        cares about set membership.
    score:
        Retrieval score. Semantics depend on ``mode`` — vector cosine for
        naive_vector, weighted graph-proximity for graph_leg. Informational.
    content_snippet:
        The chunk text the LLM judge sees. Should be ≤ ~2 KB to keep the
        judge prompt cheap; #49 chooses the truncation policy.
    """

    rank: int
    source: str
    score: float
    content_snippet: str


@dataclass(frozen=True)
class ABCaseResult:
    """One gold-question result for a (corpus, mode) pair.

    Attributes
    ----------
    question_id:
        Stable id from the gold file.
    question:
        The user-facing question text.
    gold_answer:
        Reference answer when present; ``None`` when the gold file only
        provides retrieval gold (recall/MRR but not LLM judge).
    retrieved:
        Ordered top-K items (typically K=10). May be empty if the mode
        returned no candidates.
    latency_ms:
        Per-question retrieval latency. Informational (§3.6 — not gating).
    """

    question_id: str
    question: str
    gold_answer: str | None
    retrieved: list[ABRetrievedItem]
    latency_ms: float


@dataclass(frozen=True)
class ABRunnerOutput:
    """All results for a single (corpus_id, mode) pair.

    A/B runner emits one ``ABRunnerOutput`` per corpus × mode cell. The
    results writer takes a list of these as input.

    Attributes
    ----------
    corpus_id:
        Identity-equal to pg-raggraph namespace and chunkshop corpus id.
        Examples: ``'bakeoff-scotus-ab'``, ``'bakeoff-ntsb-ab'``.
    mode:
        Free string — caller decides. Recommended values: ``'naive_vector'``,
        ``'graph_leg'``, ``'hybrid'``. The verdict writer treats unknown
        modes as opaque and pairs naive_vector ↔ graph_leg by name.
    results:
        Per-question results. The writer asserts ``len(results) > 0`` before
        computing metrics.
    """

    corpus_id: str
    mode: str
    results: list[ABCaseResult]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON dumping."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ABRunnerOutput:
        """Deserialize from a dict (e.g., ``json.load``ed payload)."""
        return cls(
            corpus_id=data["corpus_id"],
            mode=data["mode"],
            results=[
                ABCaseResult(
                    question_id=r["question_id"],
                    question=r["question"],
                    gold_answer=r.get("gold_answer"),
                    retrieved=[
                        ABRetrievedItem(
                            rank=item["rank"],
                            source=item["source"],
                            score=item["score"],
                            content_snippet=item["content_snippet"],
                        )
                        for item in r.get("retrieved", [])
                    ],
                    latency_ms=r["latency_ms"],
                )
                for r in data.get("results", [])
            ],
        )


# ============================================================================
# Verdict output shape — what #50 emits (SC-013).
# ============================================================================


@dataclass(frozen=True)
class MetricVerdict:
    """Per-metric verdict label after applying §3.2 thresholds.

    label is one of: 'GRAPH_WINS', 'NAIVE_WINS', 'TIE'.
    """

    metric: str  # 'recall_at_10', 'mrr', 'judge_win_rate'
    graph: float
    naive: float
    delta: float
    label: str  # 'GRAPH_WINS' | 'NAIVE_WINS' | 'TIE'


@dataclass(frozen=True)
class MetricRollup:
    """Per-corpus or combined rollup of all three metrics."""

    scope: str  # corpus_id or 'combined'
    recall_at_10: MetricVerdict
    mrr: MetricVerdict
    judge_win_rate: MetricVerdict


@dataclass(frozen=True)
class ABVerdict:
    """Final A/B verdict — what compute_verdict returns and verdict.json mirrors.

    Attributes
    ----------
    per_corpus:
        One MetricRollup per corpus_id seen in the input.
    combined:
        The combined rollup across all corpora (questions concatenated for
        recall/MRR; concatenated judge tally for the LLM metric per §3.4).
    label:
        Final verdict — 'GRAPH_WINS', 'NAIVE_WINS', or 'INCONCLUSIVE' after
        applying the §3.3 combiner and the §3.4 per-corpus asymmetry guard.
    rationale:
        Human-readable explanation of how the label was reached. Mirrors
        §3.7's worked-example walkthrough.
    """

    per_corpus: list[MetricRollup] = field(default_factory=list)
    combined: MetricRollup | None = None
    label: str = "INCONCLUSIVE"
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
