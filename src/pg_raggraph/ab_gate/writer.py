"""A/B verdict writer — applies chunkshop emission contract §3 to runner output.

This module owns the verdict computation (``compute_verdict``) and the
report emission (``write_verdict_report``). The LLM-judge integration is
intentionally siloed in ``judge_seam.py`` so the verdict logic can be
unit-tested with hand-crafted score fixtures, no llm-judge dependency.
"""

from __future__ import annotations

from typing import Any

from pg_raggraph.ab_gate.io import ABVerdict, MetricRollup, MetricVerdict

# ============================================================================
# Threshold constants — chunkshop emission contract §3.2.
# These are the verdict knobs. Changing them MUST be a deliberate edit
# coordinated with chunkshop (see contract §5 Change-Management).
# ============================================================================

#: Graph wins the recall metric if its recall@10 is at least +5pp above naive.
RECALL_AT_10_LIFT_PP: float = 5.0

#: Graph wins the MRR metric if its MRR is at least +0.05 above naive.
MRR_DELTA: float = 0.05

#: Graph wins the LLM-judge metric if its win-rate is at least +0.10 above naive.
JUDGE_WIN_RATE_DELTA: float = 0.10


# ============================================================================
# Per-metric label helpers — apply §3.2 thresholds to deltas.
# ============================================================================


def _label_recall(graph: float, naive: float) -> MetricVerdict:
    """Recall@10 lift threshold is in percentage points, so multiply by 100."""
    delta_pp = (graph - naive) * 100.0
    if delta_pp >= RECALL_AT_10_LIFT_PP:
        label = "GRAPH_WINS"
    elif delta_pp <= -RECALL_AT_10_LIFT_PP:
        label = "NAIVE_WINS"
    else:
        label = "TIE"
    return MetricVerdict(
        metric="recall_at_10", graph=graph, naive=naive, delta=delta_pp, label=label
    )


def _label_mrr(graph: float, naive: float) -> MetricVerdict:
    delta = graph - naive
    if delta >= MRR_DELTA:
        label = "GRAPH_WINS"
    elif delta <= -MRR_DELTA:
        label = "NAIVE_WINS"
    else:
        label = "TIE"
    return MetricVerdict(metric="mrr", graph=graph, naive=naive, delta=delta, label=label)


def _label_judge(
    graph_wins: int, graph_total: int, naive_wins: int, naive_total: int
) -> MetricVerdict:
    """Win rates are fractions; missing tally (total == 0) means TIE."""
    graph_rate = graph_wins / graph_total if graph_total > 0 else 0.0
    naive_rate = naive_wins / naive_total if naive_total > 0 else 0.0
    delta = graph_rate - naive_rate
    if graph_total == 0 and naive_total == 0:
        label = "TIE"
    elif delta >= JUDGE_WIN_RATE_DELTA:
        label = "GRAPH_WINS"
    elif delta <= -JUDGE_WIN_RATE_DELTA:
        label = "NAIVE_WINS"
    else:
        label = "TIE"
    return MetricVerdict(
        metric="judge_win_rate",
        graph=graph_rate,
        naive=naive_rate,
        delta=delta,
        label=label,
    )


# ============================================================================
# Rollup builders.
# ============================================================================


def _build_rollup(scope: str, naive: dict, graph: dict) -> MetricRollup:
    return MetricRollup(
        scope=scope,
        recall_at_10=_label_recall(graph["recall_at_10"], naive["recall_at_10"]),
        mrr=_label_mrr(graph["mrr"], naive["mrr"]),
        judge_win_rate=_label_judge(
            graph["judge_wins"],
            graph["judge_total"],
            naive["judge_wins"],
            naive["judge_total"],
        ),
    )


def _combine(rollup: MetricRollup) -> str:
    """Apply the §3.3 2-of-3 combiner to a single rollup."""
    labels = (rollup.recall_at_10.label, rollup.mrr.label, rollup.judge_win_rate.label)
    graph_wins = sum(1 for label in labels if label == "GRAPH_WINS")
    naive_wins = sum(1 for label in labels if label == "NAIVE_WINS")
    if graph_wins >= 2 and naive_wins == 0:
        return "GRAPH_WINS"
    if naive_wins >= 2 and graph_wins == 0:
        return "NAIVE_WINS"
    return "INCONCLUSIVE"


def _apply_asymmetry_guard(combined_label: str, per_corpus: list[MetricRollup]) -> tuple[str, str]:
    """§3.4 asymmetry guard: GRAPH_WINS downgrades to INCONCLUSIVE if graph
    loses all 3 metrics on any single corpus. Symmetric guard for NAIVE_WINS
    (graph wins all 3 on any single corpus → INCONCLUSIVE).

    Returns (final_label, rationale_addition).
    """
    if combined_label == "GRAPH_WINS":
        for rollup in per_corpus:
            if (
                rollup.recall_at_10.label == "NAIVE_WINS"
                and rollup.mrr.label == "NAIVE_WINS"
                and rollup.judge_win_rate.label == "NAIVE_WINS"
            ):
                return (
                    "INCONCLUSIVE",
                    f"§3.4 asymmetry guard: combined GRAPH_WINS, but graph "
                    f"loses 3-0 on {rollup.scope}; downgraded to INCONCLUSIVE.",
                )
    if combined_label == "NAIVE_WINS":
        for rollup in per_corpus:
            if (
                rollup.recall_at_10.label == "GRAPH_WINS"
                and rollup.mrr.label == "GRAPH_WINS"
                and rollup.judge_win_rate.label == "GRAPH_WINS"
            ):
                return (
                    "INCONCLUSIVE",
                    f"§3.4 asymmetry guard: combined NAIVE_WINS, but graph "
                    f"wins 3-0 on {rollup.scope}; downgraded to INCONCLUSIVE.",
                )
    return combined_label, ""


def _format_rationale(combined: MetricRollup, label: str, extra: str) -> str:
    """Human-readable walkthrough mirroring §3.7's worked-example structure."""
    lines = [
        f"Recall@10 lift: {combined.recall_at_10.delta:+.2f}pp → {combined.recall_at_10.label}",
        f"MRR delta: {combined.mrr.delta:+.4f} → {combined.mrr.label}",
        f"Judge win-rate delta: {combined.judge_win_rate.delta:+.4f} → "
        f"{combined.judge_win_rate.label}",
        f"§3.3 combiner: {label}",
    ]
    if extra:
        lines.append(extra)
    return "\n".join(lines)


# ============================================================================
# Public entry — compute_verdict.
#
# The function is exposed as a class-with-__call__ so the fixture-driven
# tests can use compute_verdict.from_premeasured(…) without importing a
# second function. Production callers use compute_verdict(runner_output, …)
# directly per SC-009.
# ============================================================================


class _ComputeVerdict:
    """Callable that computes ABVerdict from either premeasured metrics or
    ``ABRunnerOutput`` instances.

    Two entry points:

    - ``compute_verdict(runner_outputs, judge_provider=...)`` — production
      path. Takes a list of ``ABRunnerOutput`` (per corpus × mode) and a
      configured llm-judge provider. Computes recall/MRR from retrieved[]
      and judge tallies from the provider.
    - ``compute_verdict.from_premeasured(payload)`` — fixture path. Takes a
      dict with shape ``{per_corpus: {corpus: {mode: {metric: value, ...}}}, combined: {...}}``.
      Used by SC-010 / SC-012 fixture tests to drive the verdict path
      without needing to back-fit retrieved[] arrays or run an LLM judge.
    """

    def __call__(
        self,
        runner_outputs: list[Any],
        *,
        judge_config: Any | None = None,
    ) -> ABVerdict:
        """Production path. Implementation lands when #49 emits real
        ABRunnerOutput files (Task B4 wires the file-loading path; the
        retrieval-metric + judge integration happens here).

        For now, raise NotImplementedError so callers know this path is the
        intended seam — fixture path (from_premeasured) is the only fully
        wired path until #49 ships.
        """
        raise NotImplementedError(
            "compute_verdict(runner_outputs, ...) requires #49 emission. "
            "Use compute_verdict.from_premeasured(payload) for fixture-based "
            "verdict computation until #49 lands."
        )

    @staticmethod
    def from_premeasured(payload: dict[str, Any]) -> ABVerdict:
        """Compute a verdict from a pre-aggregated payload (fixture path).

        Payload shape::

            {
              "per_corpus": {
                "<corpus_id>": {
                  "naive_vector": {"recall_at_10": float, "mrr": float,
                                   "judge_wins": int, "judge_total": int},
                  "graph_leg":    {…same shape…},
                },
                …
              },
              "combined": {
                "naive_vector": {…},
                "graph_leg":    {…},
              },
            }
        """
        per_corpus_rollups = [
            _build_rollup(scope=corpus_id, naive=cells["naive_vector"], graph=cells["graph_leg"])
            for corpus_id, cells in payload["per_corpus"].items()
        ]
        combined_rollup = _build_rollup(
            scope="combined",
            naive=payload["combined"]["naive_vector"],
            graph=payload["combined"]["graph_leg"],
        )

        combined_label = _combine(combined_rollup)
        final_label, extra = _apply_asymmetry_guard(combined_label, per_corpus_rollups)
        rationale = _format_rationale(combined_rollup, final_label, extra)

        return ABVerdict(
            per_corpus=per_corpus_rollups,
            combined=combined_rollup,
            label=final_label,
            rationale=rationale,
        )


compute_verdict = _ComputeVerdict()


# ============================================================================
# Verdict report writer — emits verdict.json + verdict.md + latency.json.
# ============================================================================


import json as _json  # noqa: E402
from pathlib import Path  # noqa: E402


def _render_markdown(verdict: ABVerdict) -> str:
    """Render an ABVerdict as Markdown mirroring chunkshop contract §3.7."""
    lines: list[str] = []
    lines.append("# A/B Gate Verdict")
    lines.append("")
    lines.append(
        "> Computed per chunkshop emission contract §3 (combiner) + §3.4 (asymmetry guard)."
    )
    lines.append("")

    # --- Inputs ---------------------------------------------------------
    lines.append("## Inputs")
    lines.append("")
    lines.append("| Corpus | Modes seen |")
    lines.append("|---|---|")
    for rollup in verdict.per_corpus:
        lines.append(f"| {rollup.scope} | naive_vector, graph_leg |")
    lines.append("")

    # --- Per-metric deltas (combined) ----------------------------------
    lines.append("## Per-metric deltas")
    lines.append("")
    if verdict.combined is not None:
        c = verdict.combined
        lines.append("| Metric | Naive | Graph | Delta | Label |")
        lines.append("|---|---|---|---|---|")
        lines.append(
            f"| Recall@10 | {c.recall_at_10.naive:.4f} | {c.recall_at_10.graph:.4f} "
            f"| {c.recall_at_10.delta:+.2f}pp | {c.recall_at_10.label} |"
        )
        lines.append(
            f"| MRR | {c.mrr.naive:.4f} | {c.mrr.graph:.4f} | {c.mrr.delta:+.4f} | {c.mrr.label} |"
        )
        lines.append(
            f"| Judge win-rate | {c.judge_win_rate.naive:.4f} | {c.judge_win_rate.graph:.4f} "
            f"| {c.judge_win_rate.delta:+.4f} | {c.judge_win_rate.label} |"
        )
    lines.append("")

    # --- Per-corpus breakdown ------------------------------------------
    lines.append("## Per-corpus breakdown")
    lines.append("")
    for rollup in verdict.per_corpus:
        lines.append(f"### {rollup.scope}")
        lines.append("")
        lines.append("| Metric | Naive | Graph | Delta | Label |")
        lines.append("|---|---|---|---|---|")
        lines.append(
            f"| Recall@10 | {rollup.recall_at_10.naive:.4f} | {rollup.recall_at_10.graph:.4f} "
            f"| {rollup.recall_at_10.delta:+.2f}pp | {rollup.recall_at_10.label} |"
        )
        lines.append(
            f"| MRR | {rollup.mrr.naive:.4f} | {rollup.mrr.graph:.4f} "
            f"| {rollup.mrr.delta:+.4f} | {rollup.mrr.label} |"
        )
        lines.append(
            f"| Judge win-rate | {rollup.judge_win_rate.naive:.4f} "
            f"| {rollup.judge_win_rate.graph:.4f} "
            f"| {rollup.judge_win_rate.delta:+.4f} | {rollup.judge_win_rate.label} |"
        )
        lines.append("")

    # --- Walkthrough ----------------------------------------------------
    lines.append("## Verdict computation walkthrough")
    lines.append("")
    lines.append("```")
    lines.append(verdict.rationale or "(no rationale)")
    lines.append("```")
    lines.append("")

    # --- Final verdict --------------------------------------------------
    lines.append("## Final verdict")
    lines.append("")
    lines.append(f"**{verdict.label}**")
    lines.append("")

    return "\n".join(lines)


def write_verdict_report(
    verdict: ABVerdict,
    *,
    out_dir: Path,
    latency_rows: list[dict[str, Any]],
) -> None:
    """Emit verdict.json, verdict.md, and latency.json under ``out_dir``.

    Parameters
    ----------
    verdict:
        The ``ABVerdict`` from ``compute_verdict``.
    out_dir:
        Output directory; created if missing.
    latency_rows:
        Informational latency rows shaped per SC-015. Caller's responsibility
        to populate; #50 does not consult this file when computing the verdict.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "verdict.json").write_text(
        _json.dumps(verdict.to_dict(), indent=2), encoding="utf-8"
    )
    (out_dir / "verdict.md").write_text(_render_markdown(verdict), encoding="utf-8")
    (out_dir / "latency.json").write_text(_json.dumps(latency_rows, indent=2), encoding="utf-8")
