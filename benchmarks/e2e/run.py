"""E2E benchmark harness entry point.

Usage:
    python -m benchmarks.e2e.run --dataset all --subset 500
    python -m benchmarks.e2e.run --dataset mhr --arms lede_spacy,llm --judge openai
    python -m benchmarks.e2e.run --dataset twowiki --subset 5 --modes L1_naive,GP_local

Defaults:
    DSN              -> postgresql://postgres:postgres@localhost:5437/pg_raggraph_bench
                        (override: $PGRG_BENCH_DSN or --dsn)
    Embedder         -> BAAI/bge-large-en-v1.5 (dim=1024). The bench DB MUST
                        be initialized with this dim.
    Judge            -> auto (openai if OPENAI_API_KEY set, else local Qwen).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.e2e.config import ARMS, DEFAULT_DSN, LADDER, RunConfig
from benchmarks.e2e.datasets import get as get_loader
from benchmarks.e2e.datasets import names as dataset_names
from benchmarks.e2e.ingest import IngestStats, namespace_for, stage
from benchmarks.e2e.judge import Judge
from benchmarks.e2e.report import write_per_arm_json, write_summary
from benchmarks.e2e.retrieve import sweep
from benchmarks.e2e.score import score_cells

ALL_DATASETS = ["mhr", "musique", "twowiki"]
ALL_ARMS = ["lede_spacy", "llm"]


def parse_args(argv: list[str] | None = None) -> RunConfig:
    p = argparse.ArgumentParser(description="pg-raggraph e2e benchmark harness")
    p.add_argument(
        "--dataset",
        default="all",
        help=f"comma-separated subset of {ALL_DATASETS} or 'all' (default: all)",
    )
    p.add_argument(
        "--arms",
        default="lede_spacy",
        help=f"comma-separated subset of {ALL_ARMS} (default: lede_spacy)",
    )
    p.add_argument("--subset", type=int, default=500, help="per-dataset query subset size")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--modes",
        default=None,
        help=f"comma-separated rung labels from {[label for label, _ in LADDER]} (default: all)",
    )
    p.add_argument("--reingest", action="store_true", help="drop namespaces before staging")
    p.add_argument(
        "--skip-ingest",
        action="store_true",
        help="skip ingest when the namespace already has documents",
    )
    p.add_argument("--judge", default="auto", choices=["auto", "openai", "local", "none"])
    p.add_argument("--dsn", default=None, help=f"PGRG DSN (default: {DEFAULT_DSN})")
    p.add_argument(
        "--output-dir", default=None, help="results dir (default: benchmarks/e2e/results)"
    )
    a = p.parse_args(argv)

    datasets = ALL_DATASETS if a.dataset == "all" else [d.strip() for d in a.dataset.split(",")]
    for d in datasets:
        if d not in dataset_names():
            p.error(f"unknown dataset {d!r}; known: {dataset_names()}")

    arms = [s.strip() for s in a.arms.split(",")]
    for arm in arms:
        if arm not in ARMS:
            p.error(f"unknown arm {arm!r}; known: {list(ARMS)}")

    modes = [m.strip() for m in a.modes.split(",")] if a.modes else None
    if modes:
        known = {label for label, _ in LADDER}
        bad = [m for m in modes if m not in known]
        if bad:
            p.error(f"unknown mode(s) {bad}; known: {sorted(known)}")

    return RunConfig(
        dataset=",".join(datasets),
        arms=arms,
        subset=a.subset,
        seed=a.seed,
        modes=modes,
        reingest=a.reingest,
        skip_ingest=a.skip_ingest,
        judge=a.judge,
        dsn=a.dsn,
        output_dir=a.output_dir,
    )


async def run(cfg: RunConfig) -> None:
    dsn = cfg.dsn or DEFAULT_DSN
    out_dir = Path(cfg.output_dir or "benchmarks/e2e/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    datasets = cfg.dataset.split(",")
    judge = None if cfg.judge == "none" else Judge(mode=cfg.judge)
    if judge is not None:
        print(f"[judge] provider: {judge.provider_name}", file=sys.stderr)

    all_scored: dict[str, list] = {}
    all_ingest: list[IngestStats] = []

    for ds_name in datasets:
        print(f"\n=== {ds_name} ===", file=sys.stderr)
        bundle = get_loader(ds_name)(subset=cfg.subset, seed=cfg.seed)
        print(f"  {bundle.summary()}", file=sys.stderr)

        ds_scored: list = []
        for arm in cfg.arms:
            print(f"  [{arm}] staging…", file=sys.stderr)
            ing = await stage(
                bundle,
                arm,
                dsn=dsn,
                reingest=cfg.reingest,
                skip_ingest=cfg.skip_ingest,
            )
            note = " (skipped)" if ing.skipped else f" ({ing.wall_seconds:.1f}s)"
            print(
                f"  [{arm}] staged: {ing.documents} docs / {ing.chunks} chunks / "
                f"{ing.entities} entities / {ing.relationships} relationships{note}",
                file=sys.stderr,
            )
            all_ingest.append(ing)

            print(f"  [{arm}] sweeping ladder…", file=sys.stderr)
            cells = await sweep(
                bundle,
                arm,
                namespace=namespace_for(ds_name, arm),
                dsn=dsn,
                modes=cfg.modes,
            )
            print(f"  [{arm}] sweep done: {len(cells)} cells", file=sys.stderr)

            print(f"  [{arm}] scoring…", file=sys.stderr)
            scored = await score_cells(cells, judge=judge)
            ds_scored.extend(scored)

            arm_json = write_per_arm_json(scored, out_dir, date)
            print(f"  [{arm}] wrote {arm_json}", file=sys.stderr)

        all_scored[ds_name] = ds_scored

    print("\n=== summary ===", file=sys.stderr)
    json_path, md_path = write_summary(all_scored, all_ingest, out_dir, date)
    print(f"  {json_path}", file=sys.stderr)
    print(f"  {md_path}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    cfg = parse_args(argv)
    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
