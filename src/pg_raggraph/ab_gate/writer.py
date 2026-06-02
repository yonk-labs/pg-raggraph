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
# Production-path helpers — retrieval scoring + judge + payload assembly.
# ============================================================================


def _verdict_from_payload(payload: dict[str, Any]) -> ABVerdict:
    """Build an ABVerdict from a per_corpus + combined metrics payload.

    Shared by both the production ``__call__`` and the fixture
    ``from_premeasured`` path — the §3.3 combiner + §3.4 asymmetry guard live
    here so the two entry points can never diverge on verdict logic.
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


def _coerce_runner_outputs(runner_outputs: list[Any]) -> list[Any]:
    """Accept a mixed list of ABRunnerOutput instances and/or JSON paths."""
    import json as _j
    from pathlib import Path as _P

    from pg_raggraph.ab_gate.io import ABRunnerOutput

    out: list[ABRunnerOutput] = []
    for item in runner_outputs:
        if isinstance(item, ABRunnerOutput):
            out.append(item)
        elif isinstance(item, (str, _P)):
            data = _j.loads(_P(item).read_text())
            out.append(ABRunnerOutput.from_dict(data))
        elif isinstance(item, dict):
            out.append(ABRunnerOutput.from_dict(item))
        else:
            raise TypeError(
                f"runner_outputs items must be ABRunnerOutput, path, or dict; got {type(item)}"
            )
    return out


def _source_matches_gold(source: str, gold_doc_id: str) -> bool:
    """A retrieved source matches the gold target if the gold_doc_id is present.

    pg-raggraph stores sources as ``source_path`` (e.g. ``chunkshop:<doc_id>``)
    or ``namespace:doc_id``; the chunkshop gold gives the bare ``doc_id``. A
    substring match tolerates the prefix without false-positives because the
    bakeoff doc ids are full, suffix-distinct strings (…-decision vs …-overview).
    """
    if not gold_doc_id or not source:
        return False
    return gold_doc_id == source or gold_doc_id in source


def _score_retrieval(output: Any, cutoff: int) -> tuple[list[int], list[float]]:
    """Per-question (hit, reciprocal-rank) arrays for one runner output.

    hit = 1 if gold_doc_id appears in the top-`cutoff` retrieved sources.
    rr  = 1 / rank_of_first_gold_hit (0 if not in top-cutoff). Cases without a
    gold_doc_id are skipped (can't score retrieval without a target).
    """
    hits: list[int] = []
    rrs: list[float] = []
    for case in output.results:
        gold = case.gold_doc_id
        if not gold:
            continue
        rank_hit = 0
        for item in case.retrieved[:cutoff]:
            if _source_matches_gold(item.source, gold):
                rank_hit = item.rank
                break
        hits.append(1 if rank_hit else 0)
        rrs.append(1.0 / rank_hit if rank_hit else 0.0)
    return hits, rrs


def _judge_output(output: Any, judge_provider: Any | None) -> list[bool]:
    """Per-question acceptability flags via llm-judge (empty when no provider).

    For each case: synthesize an answer from the mode's retrieved chunks
    (``generate_answer``), then score it (``llm_score``). ``passed`` is the
    contract's "acceptable" bar. The same provider doubles as answer generator
    and judge — both legs use identical machinery so the graph-vs-naive
    comparison is fair (the only difference is the retrieved context).
    """
    if judge_provider is None:
        return []
    from llm_judge.models import EvalCase
    from llm_judge.scorers import generate_answer, llm_score

    flags: list[bool] = []
    for case in output.results:
        chunks = [item.content_snippet for item in case.retrieved if item.content_snippet]
        eval_case = EvalCase(
            case_id=case.question_id,
            question=case.question,
            answer="",
            expected=case.gold_answer or "",
            chunks=chunks,
        )
        answer = generate_answer(eval_case, judge_provider)
        eval_case.answer = answer.answer or ""
        decision = llm_score(eval_case, judge_provider)
        flags.append(bool(decision.passed))
    return flags


def _metrics_dict(hits: list[int], rrs: list[float], judge_flags: list[bool]) -> dict[str, float]:
    """Aggregate per-question arrays into the {recall_at_10, mrr, judge_*} dict
    that ``_build_rollup`` consumes."""
    n = len(hits)
    recall = (sum(hits) / n) if n else 0.0
    mrr = (sum(rrs) / len(rrs)) if rrs else 0.0
    judge_wins = sum(1 for f in judge_flags if f)
    judge_total = len(judge_flags)
    return {
        "recall_at_10": recall,
        "mrr": mrr,
        "judge_wins": judge_wins,
        "judge_total": judge_total,
    }


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
        recall_cutoff: int = 10,
        graph_mode: str = "graph_leg",
    ) -> ABVerdict:
        """Production path: compute a verdict from real A/B runner output.

        Parameters
        ----------
        runner_outputs:
            A list of ``ABRunnerOutput`` instances, or paths (str / Path) to
            their JSON files. Must include ``naive_vector`` and ``graph_mode``
            for each corpus.
        judge_config:
            Chunkshop-shaped ``JudgingConfig`` dict (see ``judge_seam``). When
            None, the LLM-judge metric is skipped (judge_total = 0 → TIE on
            that metric); recall@10 + MRR still decide the verdict.
        recall_cutoff:
            Top-K for recall (contract §3.1 uses 10).
        graph_mode:
            Which mode plays the "graph" side of the naive-vs-graph comparison.
            ``"graph_leg"`` (default) tests graph-as-primary; ``"hybrid"`` tests
            graph-as-augmentation (the production-shaped mode). The contract's
            gate is over both — run this twice, once per graph_mode.

        Recall@10 and MRR are computed by matching each case's ``gold_doc_id``
        against ``retrieved[].source`` (contract §3.1). The judge metric runs
        llm-judge: an answer is synthesized from each mode's retrieved chunks,
        then scored for acceptability; win-rate = fraction of "passed" answers.
        """
        outputs = _coerce_runner_outputs(runner_outputs)

        # Group by corpus → {mode: ABRunnerOutput}.
        by_corpus: dict[str, dict[str, Any]] = {}
        for out in outputs:
            by_corpus.setdefault(out.corpus_id, {})[out.mode] = out

        judge_provider = None
        if judge_config is not None:
            from pg_raggraph.ab_gate.judge_seam import (
                _chunkshop_judge_config_to_llm_judge_provider,
            )

            judge_provider = _chunkshop_judge_config_to_llm_judge_provider(judge_config)

        # Score naive_vector + the chosen graph_mode into per-question arrays.
        # The chosen graph_mode is remapped into the payload's "graph_leg" slot
        # so the §3 rollup/combiner logic stays mode-name-agnostic.
        per_corpus_payload: dict[str, dict[str, dict[str, float]]] = {}
        combined_raw: dict[str, dict[str, list]] = {
            "naive_vector": {"hits": [], "rrs": [], "judge": []},
            "graph": {"hits": [], "rrs": [], "judge": []},
        }

        for corpus_id, modes in by_corpus.items():
            cells: dict[str, dict[str, float]] = {}
            for mode, slot in (("naive_vector", "naive_vector"), (graph_mode, "graph")):
                out = modes.get(mode)
                if out is None:
                    raise ValueError(
                        f"corpus {corpus_id!r} is missing the {mode!r} runner output; "
                        f"naive_vector and {graph_mode} are required to compute this verdict."
                    )
                hits, rrs = _score_retrieval(out, recall_cutoff)
                judge_flags = _judge_output(out, judge_provider)
                cells[slot] = _metrics_dict(hits, rrs, judge_flags)
                combined_raw[slot]["hits"].extend(hits)
                combined_raw[slot]["rrs"].extend(rrs)
                combined_raw[slot]["judge"].extend(judge_flags)
            # _build_rollup expects keys "naive_vector" + "graph_leg".
            per_corpus_payload[corpus_id] = {
                "naive_vector": cells["naive_vector"],
                "graph_leg": cells["graph"],
            }

        combined_payload = {
            "naive_vector": _metrics_dict(
                combined_raw["naive_vector"]["hits"],
                combined_raw["naive_vector"]["rrs"],
                combined_raw["naive_vector"]["judge"],
            ),
            "graph_leg": _metrics_dict(
                combined_raw["graph"]["hits"],
                combined_raw["graph"]["rrs"],
                combined_raw["graph"]["judge"],
            ),
        }

        return _verdict_from_payload(
            {"per_corpus": per_corpus_payload, "combined": combined_payload}
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
        return _verdict_from_payload(payload)


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
