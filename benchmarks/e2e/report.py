"""Report generator — per-arm JSON + cross-dataset summary md/json.

Pivots ``ScoredCell`` lists into pooled and stratified tables. Markdown
follows the findings-doc template: Scope → Headline → Robust conclusions
→ What NOT to trust → Next steps. The harness pre-fills the data; the
human writes the headline interpretation.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from benchmarks.e2e.config import LADDER
from benchmarks.e2e.ingest import IngestStats
from benchmarks.e2e.score import ScoredCell

METRICS = ("span_recall", "hit_at_1", "mrr", "ndcg", "judge_score")
RUNG_ORDER = [label for label, _ in LADDER]


def write_per_arm_json(scored: list[ScoredCell], out_dir: Path, date: str) -> Path:
    if not scored:
        raise ValueError("no scored cells")
    dataset = scored[0].cell["dataset"]
    arm = scored[0].cell["arm"]
    path = out_dir / f"{date}-{dataset}-{arm}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([_serialize(s) for s in scored], indent=2, ensure_ascii=False))
    return path


def _serialize(s: ScoredCell) -> dict:
    d = asdict(s)
    # cell is already a dict
    return d


def _agg(values: list[float]) -> dict:
    valid = [v for v in values if v is not None]
    if not valid:
        return {"n": 0, "mean": None, "ci95": None}
    mean = statistics.fmean(valid)
    # 95% CI from sample stdev / sqrt(n)
    if len(valid) > 1:
        s = statistics.stdev(valid)
        ci = 1.96 * s / math.sqrt(len(valid))
    else:
        ci = 0.0
    return {"n": len(valid), "mean": mean, "ci95": ci}


def pivot(scored: list[ScoredCell]) -> dict:
    """Pivot into {arm: {rung: {metric: agg}}} pooled + per-stratum."""
    pooled: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    per_stratum: dict = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    )
    for s in scored:
        c = s.cell
        arm, rung = c["arm"], c["rung"]
        for m in METRICS:
            v = getattr(s, m)
            if v is None:
                continue
            pooled[arm][rung][m].append(v)
            for sk, sv in (c.get("strata") or {}).items():
                per_stratum[arm][rung][f"{sk}={sv}"][m].append(v)

    out_pooled: dict = {}
    for arm, rungs in pooled.items():
        out_pooled[arm] = {}
        for rung, metrics in rungs.items():
            out_pooled[arm][rung] = {m: _agg(vs) for m, vs in metrics.items()}

    out_strata: dict = {}
    for arm, rungs in per_stratum.items():
        out_strata[arm] = {}
        for rung, strata in rungs.items():
            out_strata[arm][rung] = {}
            for stratum, metrics in strata.items():
                out_strata[arm][rung][stratum] = {m: _agg(vs) for m, vs in metrics.items()}

    return {"pooled": out_pooled, "stratified": out_strata}


def latency_pivot(scored: list[ScoredCell]) -> dict:
    """{arm: {rung: {p50, p95, p99, mean}}}."""
    by: dict = defaultdict(lambda: defaultdict(list))
    for s in scored:
        if s.cell.get("error"):
            continue
        by[s.cell["arm"]][s.cell["rung"]].append(s.cell["latency_ms"])
    out: dict = {}
    for arm, rungs in by.items():
        out[arm] = {}
        for rung, vals in rungs.items():
            if not vals:
                continue
            vals_sorted = sorted(vals)
            n = len(vals_sorted)
            out[arm][rung] = {
                "p50": vals_sorted[n // 2],
                "p95": vals_sorted[min(n - 1, int(n * 0.95))],
                "p99": vals_sorted[min(n - 1, int(n * 0.99))],
                "mean": statistics.fmean(vals),
                "n": n,
            }
    return out


def write_summary(
    all_scored: dict[str, list[ScoredCell]],
    all_ingest: list[IngestStats],
    out_dir: Path,
    date: str,
) -> tuple[Path, Path]:
    """Per-dataset pivots + cross-dataset markdown."""
    summary: dict = {
        "date": date,
        "datasets": {},
        "ingest": [asdict(s) for s in all_ingest],
    }
    for dataset, scored in all_scored.items():
        summary["datasets"][dataset] = {
            "accuracy": pivot(scored),
            "latency_ms": latency_pivot(scored),
            "n_cells": len(scored),
        }

    json_path = out_dir / f"{date}-summary.json"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    md_path = out_dir / f"{date}-summary.md"
    md_path.write_text(_render_markdown(summary))
    return json_path, md_path


def _render_markdown(summary: dict) -> str:
    lines: list[str] = []
    lines.append(f"# E2E Benchmark Summary — {summary['date']}\n")
    lines.append(
        "**Pre-registered hypothesis:** graph-primary modes (`GP_local` / `GP_global` / "
        "`GP_hybrid`) beat `L1_naive` and `L4_rerank` on multi-hop question strata "
        "(MHR `inference_query`/`comparison_query`, MuSiQue/2Wiki compositional), "
        "even though aggregate parity is the going-in expectation.\n"
    )
    lines.append("\n---\n")

    # 1. Scope
    lines.append("\n## 1. Scope of what ran\n")
    for ing in summary["ingest"]:
        if ing["skipped"]:
            note = " (skipped — namespace already populated)"
        else:
            note = f" — staged in {ing['wall_seconds']:.1f}s"
        lines.append(
            f"- **{ing['dataset']} / {ing['arm']}**: {ing['documents']} docs, "
            f"{ing['chunks']} chunks, {ing['entities']} entities, "
            f"{ing['relationships']} relationships{note}"
        )
    lines.append("")

    # 2. Headline table per dataset
    for ds, ds_data in summary["datasets"].items():
        lines.append(f"\n## 2. Headline — {ds}\n")
        lines.append("Pooled accuracy across the full query subset (mean ± 95% CI):\n")
        lines.append(_render_accuracy_table(ds_data["accuracy"]["pooled"]))
        lines.append("")
        # Stratified
        lines.append(f"### {ds} — stratified by query type\n")
        lines.append(_render_stratified_tables(ds_data["accuracy"]["stratified"]))
        # Latency
        lines.append(f"### {ds} — query latency (server-side, ms)\n")
        lines.append(_render_latency_table(ds_data["latency_ms"]))
        lines.append("")

    # 3. Caveats
    lines.append("\n## 3. What NOT to trust\n")
    lines.append(
        "- Span recall is the floor metric and overstates accuracy ~2× vs LLM-judge "
        "(the 'verbatim-span artifact'). Never quote it alone."
    )
    lines.append(
        "- The judge is self-grading — internally consistent across cells in a single "
        "run, but absolute scores differ between providers (gpt-5-mini vs local Qwen). "
        "Each cell records `judge_provider`; do not compare across providers."
    )
    lines.append("- Strata with `n < 30` carry wide CIs; treat single-digit pp gaps as noise.")
    lines.append(
        "- All retrieval numbers assume the pre-K1 retrieval path. Re-baseline after K1 "
        "lands using the per-cell `git_sha` to anchor."
    )
    lines.append("")

    lines.append("\n## 4. Next steps\n")
    lines.append("- Human writes the interpretation of the headline tables above.")
    lines.append(
        "- Compare to the pinned hypothesis: did graph-primary beat lexical+rerank "
        "on multi-hop strata specifically?"
    )
    lines.append(
        "- If yes: graph-primary is a per-stratum deployment recommendation. "
        "If no: graph as enhancer is the only viable shape."
    )
    return "\n".join(lines)


def _render_accuracy_table(pooled: dict) -> str:
    if not pooled:
        return "_(no data)_\n"
    arms = sorted(pooled.keys())
    rungs = [r for r in RUNG_ORDER if any(r in pooled[a] for a in arms)]
    header = (
        "| Rung | "
        + " | ".join(
            f"{arm} {m}" for arm in arms for m in ("span", "hit@1", "mrr", "ndcg", "judge")
        )
        + " |"
    )
    sep = "|---|" + "---|" * (len(arms) * 5)
    body: list[str] = [header, sep]
    for rung in rungs:
        row = [rung]
        for arm in arms:
            cell = pooled.get(arm, {}).get(rung, {})
            row.append(_fmt_cell(cell.get("span_recall")))
            row.append(_fmt_cell(cell.get("hit_at_1")))
            row.append(_fmt_cell(cell.get("mrr")))
            row.append(_fmt_cell(cell.get("ndcg")))
            row.append(_fmt_cell(cell.get("judge_score")))
        body.append("| " + " | ".join(row) + " |")
    return "\n".join(body) + "\n"


def _render_stratified_tables(stratified: dict) -> str:
    if not stratified:
        return "_(no strata)_\n"
    out: list[str] = []
    # Collect all stratum keys across arms/rungs.
    strata_keys: set[str] = set()
    for arm, rungs in stratified.items():
        for rung, strata in rungs.items():
            strata_keys.update(strata.keys())
    if not strata_keys:
        return "_(no strata)_\n"
    arms = sorted(stratified.keys())
    rungs = [r for r in RUNG_ORDER if any(r in stratified[a] for a in arms)]
    for sk in sorted(strata_keys):
        out.append(f"\n**Stratum `{sk}`** — LLM-judge score:\n")
        header = "| Rung | " + " | ".join(arms) + " |"
        sep = "|---|" + "---|" * len(arms)
        body = [header, sep]
        for rung in rungs:
            row = [rung]
            for arm in arms:
                cell = stratified.get(arm, {}).get(rung, {}).get(sk, {})
                row.append(_fmt_cell(cell.get("judge_score")))
            body.append("| " + " | ".join(row) + " |")
        out.append("\n".join(body))
    return "\n".join(out) + "\n"


def _render_latency_table(lat: dict) -> str:
    if not lat:
        return "_(no latency data)_\n"
    arms = sorted(lat.keys())
    rungs = [r for r in RUNG_ORDER if any(r in lat[a] for a in arms)]
    header = "| Rung | " + " | ".join(f"{a} p50/p95" for a in arms) + " |"
    sep = "|---|" + "---|" * len(arms)
    body = [header, sep]
    for rung in rungs:
        row = [rung]
        for arm in arms:
            c = lat.get(arm, {}).get(rung)
            if c is None:
                row.append("—")
            else:
                row.append(f"{c['p50']:.0f} / {c['p95']:.0f}")
        body.append("| " + " | ".join(row) + " |")
    return "\n".join(body) + "\n"


def _fmt_cell(agg: dict | None) -> str:
    if agg is None or agg.get("mean") is None:
        return "—"
    mean = agg["mean"]
    ci = agg.get("ci95")
    if ci:
        return f"{mean:.2f}±{ci:.2f}"
    return f"{mean:.2f}"
