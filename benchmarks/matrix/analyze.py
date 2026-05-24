"""Cross-run deep-benchmark analyzer.

Reads one or more llm-judge ``results.jsonl`` files (the ensemble-aggregated
rows produced by ``benchmarks.matrix.suite``), groups them by the *full* recipe
(dataset x chunker x retrieval mode x top_k x context strategy), and emits a
single consolidated report:

  * per-dataset baselines (classic RAG vs full-document oracle),
  * a global top-N table (macro-averaged across datasets),
  * computed "general + specialist" recommendations,
  * a per-dataset best-recipe table,
  * a chunker comparison on the structured corpus (MHR).

Unlike ``report.py`` this keys on the whole recipe, so retrieval modes are
never conflated, and it spans multiple run directories so Phase A and Phase B
land in one report.

Usage:
    uv run python -m benchmarks.matrix.analyze \
        --results '.matrix-runs/deep-a-modes-context/llm-judge/results.jsonl' \
        --results '.matrix-runs/deep-b-chunkers/llm-judge/results.jsonl' \
        --out .matrix-runs/DEEP-REPORT.md
"""

from __future__ import annotations

import argparse
import glob
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Recipes whose context strategy is one of these are the two mandated baselines.
RAG_CONTEXT = "classic_chunks"
ORACLE_CONTEXT = "full_selected_docs"
BASELINE_TOP_K = 25

# Provisional 7-rung profile ladder (cheap -> accurate). Each rung names the
# benchmarked context strategy that implements it; the emitter pulls measured
# tokens/accuracy/latency for that strategy out of the result rows. This is the
# bridge between the benchmark harness and the planned `retrieval_profile`
# feature (see skill-output/mission-brief/Mission-Brief-retrieval-profile-ladder.md).
#
# STATUS: Phase F-informed. Phase E showed coverage is the dominant lever;
# Phase F (LoCoMo) showed conversational memory rewards stacked summary+raw
# context. `raw` remains a profile escape hatch in product code, but is not an
# ordered ladder rung because its aggregate accuracy is below cheaper stacked
# and full-doc rungs.
DEFAULT_LADDER: list[dict] = [
    # Phase E/F verdict: concat doc-summary is the cheap end; whole docs and
    # stacked summary+raw variants form the robust accurate end. Per-doc
    # summaries and chunk_summary_facts stay non-default.
    {"index": 0, "name": "cheap", "note": "doc-summary+facts, top-3 docs — cheapest",
     "match": {"context_strategy": "doc_summary_facts@3", "top_k": 25}},
    {"index": 1, "name": "cheap_plus", "note": "doc-summary+facts, top-5 docs",
     "match": {"context_strategy": "doc_summary_facts@5", "top_k": 25}},
    {"index": 2, "name": "lean", "note": "whole docs, top-3",
     "match": {"context_strategy": "full_selected_docs@3", "top_k": 25}},
    {"index": 3, "name": "balanced", "note": "doc+chunk summaries with top-5 raw chunks (default)",
     "match": {"context_strategy": "doc_and_chunk_summary_toc_facts_plus_top5", "top_k": 25}},
    {"index": 4, "name": "rich", "note": "whole docs, top-5",
     "match": {"context_strategy": "full_selected_docs@5", "top_k": 25}},
    {"index": 5, "name": "stacked", "note": "per-doc summaries + retrieved-chunk summary + top-5 raw chunks",
     "match": {"context_strategy": "per_doc5_chunksum_top5", "top_k": 25}},
    {"index": 6, "name": "accurate", "note": "whole docs, top-10 — the ceiling",
     "match": {"context_strategy": "full_selected_docs@10", "top_k": 25}},
]


@dataclass
class Recipe:
    dataset: str
    chunk_strategy: str
    retrieval_mode: str
    top_k: int
    context_strategy: str

    def key(self) -> tuple:
        return (
            self.dataset,
            self.chunk_strategy,
            self.retrieval_mode,
            self.top_k,
            self.context_strategy,
        )

    def recipe_label(self) -> str:
        """Recipe identity without the dataset (for macro-averaging)."""
        return (
            f"{self.chunk_strategy}|{self.retrieval_mode}|"
            f"top_k={self.top_k}|{self.context_strategy}"
        )


@dataclass
class Agg:
    recipe: Recipe
    n: int = 0
    passed: int = 0
    score_sum: float = 0.0
    ctx_tokens_sum: float = 0.0
    source_tokens_sum: float = 0.0
    answer_ms_sum: float = 0.0
    judge_ms_sum: float = 0.0
    fact_cov_sum: float = 0.0
    fact_cov_n: int = 0
    errors: int = 0

    def add(self, row: dict[str, Any]) -> None:
        self.n += 1
        if row.get("passed"):
            self.passed += 1
        self.score_sum += float(row.get("score") or 0.0)
        meta = row.get("metadata") or {}
        self.ctx_tokens_sum += float(meta.get("context_tokens") or 0.0)
        self.source_tokens_sum += float(meta.get("source_tokens") or 0.0)
        self.answer_ms_sum += float((meta.get("answer_generation") or {}).get("latency_ms") or 0.0)
        self.judge_ms_sum += float(row.get("latency_ms") or 0.0)
        if row.get("verdict") == "ERROR":
            self.errors += 1
        # Fact coverage: supported / (supported + missing) when the judge
        # populated fact lists. Skip cases where the gold answer is itself
        # "insufficient information" (no real facts to recall).
        supported = row.get("supported") or []
        missing = row.get("missing") or []
        denom = len(supported) + len(missing)
        if denom > 0 and not _is_insufficient(row.get("expected_facts")):
            self.fact_cov_sum += len(supported) / denom
            self.fact_cov_n += 1

    # --- derived metrics -------------------------------------------------
    @property
    def pass_rate(self) -> float:
        return self.passed / self.n if self.n else 0.0

    @property
    def avg_score(self) -> float:
        return self.score_sum / self.n if self.n else 0.0

    @property
    def avg_ctx_tokens(self) -> float:
        return self.ctx_tokens_sum / self.n if self.n else 0.0

    @property
    def avg_source_tokens(self) -> float:
        return self.source_tokens_sum / self.n if self.n else 0.0

    @property
    def avg_answer_ms(self) -> float:
        return self.answer_ms_sum / self.n if self.n else 0.0

    @property
    def avg_judge_ms(self) -> float:
        return self.judge_ms_sum / self.n if self.n else 0.0

    @property
    def fact_coverage(self) -> float | None:
        return self.fact_cov_sum / self.fact_cov_n if self.fact_cov_n else None


@dataclass
class MacroRecipe:
    """A recipe averaged across the datasets it appears in (macro-average)."""

    recipe_label: str
    chunk_strategy: str
    retrieval_mode: str
    top_k: int
    context_strategy: str
    datasets: list[str] = field(default_factory=list)
    pass_rate: float = 0.0
    avg_score: float = 0.0
    avg_ctx_tokens: float = 0.0
    avg_answer_ms: float = 0.0
    avg_judge_ms: float = 0.0
    fact_coverage: float | None = None


def _is_insufficient(expected_facts: Any) -> bool:
    if not expected_facts:
        return False
    joined = " ".join(str(f) for f in expected_facts).lower()
    return "insufficient information" in joined and len(expected_facts) <= 1


def _load_rows(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _recipe_of(row: dict[str, Any]) -> Recipe:
    s = row["settings"]
    return Recipe(
        dataset=str(s.get("dataset", "")),
        chunk_strategy=str(s.get("chunk_strategy", "")),
        retrieval_mode=str(s.get("retrieval_mode", "")),
        top_k=int(s.get("top_k", 0) or 0),
        context_strategy=str(s.get("context_strategy", "")),
    )


def _aggregate(rows: list[dict[str, Any]]) -> dict[tuple, Agg]:
    groups: dict[tuple, Agg] = {}
    for row in rows:
        recipe = _recipe_of(row)
        agg = groups.get(recipe.key())
        if agg is None:
            agg = Agg(recipe=recipe)
            groups[recipe.key()] = agg
        agg.add(row)
    return groups


def _macro(groups: dict[tuple, Agg]) -> dict[str, MacroRecipe]:
    """Macro-average each recipe across the datasets it appears in."""
    by_label: dict[str, list[Agg]] = defaultdict(list)
    for agg in groups.values():
        by_label[agg.recipe.recipe_label()].append(agg)

    out: dict[str, MacroRecipe] = {}
    for label, aggs in by_label.items():
        r0 = aggs[0].recipe
        n = len(aggs)
        covs = [a.fact_coverage for a in aggs if a.fact_coverage is not None]
        out[label] = MacroRecipe(
            recipe_label=label,
            chunk_strategy=r0.chunk_strategy,
            retrieval_mode=r0.retrieval_mode,
            top_k=r0.top_k,
            context_strategy=r0.context_strategy,
            datasets=sorted(a.recipe.dataset for a in aggs),
            pass_rate=sum(a.pass_rate for a in aggs) / n,
            avg_score=sum(a.avg_score for a in aggs) / n,
            avg_ctx_tokens=sum(a.avg_ctx_tokens for a in aggs) / n,
            avg_answer_ms=sum(a.avg_answer_ms for a in aggs) / n,
            avg_judge_ms=sum(a.avg_judge_ms for a in aggs) / n,
            fact_coverage=(sum(covs) / len(covs)) if covs else None,
        )
    return out


def _baseline_for(groups: dict[tuple, Agg], dataset: str, context: str) -> Agg | None:
    # Prefer the canonical top_k=25 hybrid baseline; fall back to any matching
    # (dataset, context) recipe with the largest n.
    candidates = [
        a
        for a in groups.values()
        if a.recipe.dataset == dataset and a.recipe.context_strategy == context
    ]
    if not candidates:
        return None
    exact = [
        a
        for a in candidates
        if a.recipe.top_k == BASELINE_TOP_K and a.recipe.retrieval_mode == "hybrid"
    ]
    pool = exact or candidates
    return max(pool, key=lambda a: a.n)


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _savings(value: float, baseline: float | None) -> str:
    if not baseline:
        return "n/a"
    return f"{(1 - value / baseline) * 100:+.1f}%"


def _cov(v: float | None) -> str:
    return f"{v * 100:.0f}%" if v is not None else "n/a"


def _fmt_macro_row(m: MacroRecipe, rag_tok: float | None, oracle_tok: float | None) -> str:
    return (
        f"| {m.recipe_label} | {len(m.datasets)} | {_pct(m.pass_rate)} | "
        f"{m.avg_score:.3f} | {_cov(m.fact_coverage)} | {m.avg_ctx_tokens:.0f} | "
        f"{_savings(m.avg_ctx_tokens, rag_tok)} | {_savings(m.avg_ctx_tokens, oracle_tok)} | "
        f"{m.avg_answer_ms + m.avg_judge_ms:.0f} |"
    )


def write_report(results: list[Path], out_path: Path, datasets_order: list[str]) -> None:
    rows = _load_rows(results)
    groups = _aggregate(rows)
    macro = _macro(groups)

    present_datasets = sorted({a.recipe.dataset for a in groups.values()})

    # Macro RAG / oracle token references (mean over datasets of each baseline).
    rag_tok_per_ds: dict[str, float] = {}
    oracle_tok_per_ds: dict[str, float] = {}
    for ds in present_datasets:
        rb = _baseline_for(groups, ds, RAG_CONTEXT)
        ob = _baseline_for(groups, ds, ORACLE_CONTEXT)
        if rb:
            rag_tok_per_ds[ds] = rb.avg_ctx_tokens
        if ob:
            oracle_tok_per_ds[ds] = ob.avg_ctx_tokens
    rag_tok = (sum(rag_tok_per_ds.values()) / len(rag_tok_per_ds)) if rag_tok_per_ds else None
    oracle_tok = (
        sum(oracle_tok_per_ds.values()) / len(oracle_tok_per_ds) if oracle_tok_per_ds else None
    )

    lines: list[str] = [
        "# pg-raggraph Deep Benchmark — Consolidated Report",
        "",
        f"- Sources: {', '.join(f'`{p}`' for p in results)}",
        f"- Judged rows: {len(rows)}  |  distinct recipes: {len(groups)}",
        f"- Datasets: {', '.join(present_datasets)}",
        "- Baselines per dataset: classic RAG = `classic_chunks @ top_k=25 (hybrid)`; "
        "full-doc oracle = `full_selected_docs @ top_k=25 (hybrid)`",
        "- Token savings are vs the macro-mean baseline context tokens.",
        "",
        "## 1. Baselines (per dataset)",
        "",
        "| dataset | baseline | n | pass rate | avg score | fact cov | avg ctx tokens | avg latency ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for ds in [d for d in datasets_order if d in present_datasets] + [
        d for d in present_datasets if d not in datasets_order
    ]:
        for ctx, name in ((RAG_CONTEXT, "classic RAG"), (ORACLE_CONTEXT, "full-doc oracle")):
            b = _baseline_for(groups, ds, ctx)
            if not b:
                continue
            lines.append(
                f"| {ds} | {name} | {b.n} | {_pct(b.pass_rate)} | {b.avg_score:.3f} | "
                f"{_cov(b.fact_coverage)} | {b.avg_ctx_tokens:.0f} | "
                f"{b.avg_answer_ms + b.avg_judge_ms:.0f} |"
            )

    # --- global top-N (macro) -------------------------------------------
    ranked = sorted(
        macro.values(),
        key=lambda m: (-m.pass_rate, -m.avg_score, m.avg_ctx_tokens),
    )
    lines += [
        "",
        "## 2. Top Recipes (macro-averaged across datasets)",
        "",
        "Ranked by pass rate, then avg score, then fewest context tokens. "
        "Only recipes present in every dataset are macro-comparable; the "
        "`#ds` column shows coverage.",
        "",
        "| rank | recipe (chunker \\| mode \\| top_k \\| context) | #ds | pass rate | "
        "avg score | fact cov | avg ctx tokens | savings vs RAG | savings vs oracle | latency ms |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    full_ds = max((len(m.datasets) for m in macro.values()), default=0)
    comparable = [m for m in ranked if len(m.datasets) == full_ds]
    for i, m in enumerate(comparable[:15], 1):
        lines.append(f"| {i} {_fmt_macro_row(m, rag_tok, oracle_tok)}")

    # --- specialist recommendations -------------------------------------
    lines += ["", "## 3. Recommended Combos", ""]
    lines += _recommendations(comparable, rag_tok, oracle_tok)

    # --- per-dataset best recipe ----------------------------------------
    lines += [
        "",
        "## 4. Best Recipe Per Dataset",
        "",
        "| dataset | best recipe | pass rate | avg score | fact cov | ctx tokens | savings vs RAG |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for ds in present_datasets:
        ds_aggs = [a for a in groups.values() if a.recipe.dataset == ds]
        # Exclude the oracle (full doc) from "best recipe" — it is the upper
        # bound, not a recommendation; report it in baselines instead.
        ds_pool = [a for a in ds_aggs if a.recipe.context_strategy != ORACLE_CONTEXT]
        if not ds_pool:
            continue
        best = max(ds_pool, key=lambda a: (a.pass_rate, a.avg_score, -a.avg_ctx_tokens))
        lines.append(
            f"| {ds} | {best.recipe.recipe_label()} | {_pct(best.pass_rate)} | "
            f"{best.avg_score:.3f} | {_cov(best.fact_coverage)} | "
            f"{best.avg_ctx_tokens:.0f} | {_savings(best.avg_ctx_tokens, rag_tok_per_ds.get(ds))} |"
        )

    # --- chunker comparison (MHR) ---------------------------------------
    lines += _chunker_section(groups)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


def _recommendations(
    comparable: list[MacroRecipe], rag_tok: float | None, oracle_tok: float | None
) -> list[str]:
    if not comparable:
        return ["_No recipes are present across all datasets; cannot rank globally._"]

    out: list[str] = []
    best_pass = max(m.pass_rate for m in comparable)

    def line(tag: str, m: MacroRecipe, why: str) -> str:
        return (
            f"- **{tag}** — `{m.recipe_label}`  \n"
            f"  pass {_pct(m.pass_rate)}, score {m.avg_score:.3f}, fact cov {_cov(m.fact_coverage)}, "
            f"{m.avg_ctx_tokens:.0f} ctx tokens "
            f"({_savings(m.avg_ctx_tokens, rag_tok)} vs RAG, {_savings(m.avg_ctx_tokens, oracle_tok)} vs oracle), "
            f"{m.avg_answer_ms + m.avg_judge_ms:.0f} ms.  \n  {why}"
        )

    # General best: balance accuracy and tokens. Among recipes within 3pp of
    # the top pass rate, pick the one with the fewest context tokens.
    near_top = [m for m in comparable if m.pass_rate >= best_pass - 0.03]
    general = min(near_top, key=lambda m: m.avg_ctx_tokens)
    out.append(
        line(
            "General default (balanced)",
            general,
            "Best accuracy/token balance — top-tier accuracy at the lowest token cost.",
        )
    )

    # Max accuracy.
    max_acc = max(comparable, key=lambda m: (m.pass_rate, m.avg_score))
    out.append(line("Max accuracy", max_acc, "Use when correctness dominates and budget is secondary."))

    # Token-frugal: fewest tokens that still clears 90% of the best pass rate.
    frugal_pool = [m for m in comparable if m.pass_rate >= best_pass * 0.9]
    frugal = min(frugal_pool, key=lambda m: m.avg_ctx_tokens) if frugal_pool else None
    if frugal:
        out.append(
            line(
                "Token-frugal",
                frugal,
                "Cheapest context that retains ~90%+ of peak accuracy — high-volume/cost-sensitive.",
            )
        )

    # Fastest end-to-end.
    fastest = min(comparable, key=lambda m: m.avg_answer_ms + m.avg_judge_ms)
    out.append(line("Lowest latency", fastest, "Smallest answer+judge wall time — interactive use."))

    # Best vs oracle: matches oracle-level accuracy at least tokens.
    if oracle_tok:
        oracle_level = [m for m in comparable if m.pass_rate >= best_pass - 0.05]
        vs_oracle = min(oracle_level, key=lambda m: m.avg_ctx_tokens)
        out.append(
            line(
                "Replace the full-doc oracle",
                vs_oracle,
                "Near-oracle accuracy without sending whole documents — the headline savings story.",
            )
        )

    # Summary-first (lede): best recipe whose context is a lede summary variant.
    summary_pool = [m for m in comparable if "summary" in m.context_strategy]
    if summary_pool:
        best_summary = max(summary_pool, key=lambda m: (m.pass_rate, m.avg_score))
        out.append(
            line(
                "Summary-first (lede)",
                best_summary,
                "Best of the lede summary/TOC/facts packings — maximal token compression.",
            )
        )
    return out


def _chunker_section(groups: dict[tuple, Agg]) -> list[str]:
    # Compare chunkers on MHR at a fixed recipe (hybrid, top_k=25) so the only
    # varying axis is the chunk strategy. Includes auto (from Phase A) plus the
    # Phase B chunkers.
    mhr = [
        a
        for a in groups.values()
        if a.recipe.dataset == "mhr"
        and a.recipe.retrieval_mode == "hybrid"
        and a.recipe.top_k == BASELINE_TOP_K
        and a.recipe.context_strategy in (RAG_CONTEXT, "doc_summary_toc_facts")
    ]
    if not mhr:
        return []
    lines = [
        "",
        "## 5. Chunker Comparison (MHR, hybrid, top_k=25)",
        "",
        "Only the chunking strategy varies. `classic_chunks` isolates retrieval "
        "quality; `doc_summary_toc_facts` shows the compressed-context behavior.",
        "",
        "| chunker | context | pass rate | avg score | fact cov | avg ctx tokens |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for a in sorted(mhr, key=lambda a: (a.recipe.context_strategy, a.recipe.chunk_strategy)):
        lines.append(
            f"| {a.recipe.chunk_strategy} | {a.recipe.context_strategy} | "
            f"{_pct(a.pass_rate)} | {a.avg_score:.3f} | {_cov(a.fact_coverage)} | "
            f"{a.avg_ctx_tokens:.0f} |"
        )
    return lines


def _rung_stats(groups: dict[tuple, Agg], match: dict) -> dict[str, Agg]:
    """Return {dataset: Agg} for recipes matching a rung's strategy selector."""
    chunk = match.get("chunk_strategy", "auto")
    mode = match.get("retrieval_mode", "hybrid")
    out: dict[str, Agg] = {}
    for agg in groups.values():
        r = agg.recipe
        if r.context_strategy != match["context_strategy"]:
            continue
        if r.chunk_strategy != chunk or r.retrieval_mode != mode:
            continue
        if "top_k" in match and r.top_k != match["top_k"]:
            continue
        out[r.dataset] = agg
    return out


def _emit_calibration(
    groups: dict[tuple, Agg], ladder: list[dict], out_path: Path, sources: list[Path]
) -> None:
    """Write profile_calibration.json: per-rung tokens/accuracy/latency.

    est_accuracy and est_tokens carry both a per-corpus map and an aggregate
    (macro-mean across corpora present in the results). Rungs whose strategy is
    absent from the supplied results get null estimates + calibrated=false.
    """
    rungs: list[dict] = []
    missing: list[str] = []
    for spec in ladder:
        per = _rung_stats(groups, spec["match"])
        if not per:
            missing.append(f"{spec['name']} ({spec['match']['context_strategy']})")
        n = len(per)
        rungs.append(
            {
                "index": spec["index"],
                "name": spec["name"],
                "strategy": spec["match"]["context_strategy"],
                "match": spec["match"],
                "note": spec.get("note", ""),
                "calibrated": bool(per),
                "est_tokens": {
                    "aggregate": round(sum(a.avg_ctx_tokens for a in per.values()) / n) if n else None,
                    "by_corpus": {ds: round(a.avg_ctx_tokens) for ds, a in sorted(per.items())},
                },
                "est_accuracy": {
                    "aggregate": round(sum(a.pass_rate for a in per.values()) / n, 4) if n else None,
                    "by_corpus": {ds: round(a.pass_rate, 4) for ds, a in sorted(per.items())},
                },
                "est_latency_ms": (
                    round(sum(a.avg_answer_ms + a.avg_judge_ms for a in per.values()) / n)
                    if n
                    else None
                ),
            }
        )
    doc = {
        "ladder_version": "f-informed-1",
        "status": (
            "Phase F-informed ladder. Numbers combine Phase D/E/F; LoCoMo confirms "
            "conversational memory benefits from stacked summary+raw context, while "
            "chunk_summary_facts and plain per-doc summaries remain non-default. "
            "profile='raw' remains a separate legacy escape hatch."
        ),
        "raw_escape_hatch": {"context_strategy": "classic_chunks", "top_k": 25},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_results": [str(p) for p in sources],
        "n_rungs": len(rungs),
        "rungs": rungs,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path}  ({len(rungs)} rungs, {len(rungs) - len(missing)} calibrated)")
    if missing:
        print("  uncalibrated (strategy absent from results): " + "; ".join(missing))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="consolidate deep benchmark results")
    parser.add_argument(
        "--results",
        action="append",
        required=True,
        help="path or glob to a results.jsonl (repeatable)",
    )
    parser.add_argument("--out", type=Path, help="consolidated markdown report path")
    parser.add_argument(
        "--emit-calibration",
        type=Path,
        help="also write profile_calibration.json (per-rung tokens/accuracy/latency)",
    )
    parser.add_argument(
        "--datasets-order",
        default="mhr,musique,twowiki",
        help="preferred dataset display order",
    )
    args = parser.parse_args(argv)
    if not args.out and not args.emit_calibration:
        parser.error("nothing to do: pass --out and/or --emit-calibration")

    paths: list[Path] = []
    for pattern in args.results:
        matched = [Path(p) for p in glob.glob(pattern)]
        paths.extend(matched or [Path(pattern)])
    paths = [p for p in paths if p.exists()]
    if not paths:
        raise SystemExit("no results.jsonl files matched")

    if args.out:
        write_report(paths, args.out, args.datasets_order.split(","))
    if args.emit_calibration:
        groups = _aggregate(_load_rows(paths))
        _emit_calibration(groups, DEFAULT_LADDER, args.emit_calibration, paths)


if __name__ == "__main__":
    main()
