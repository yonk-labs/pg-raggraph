"""End-to-end matrix suite runner.

This wrapper prepares matrix cases, optionally runs llm-judge, then writes the
baseline-relative report. The lower-level modules remain independently usable
when operators want to pause between preparation and judging.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
from pathlib import Path

import yaml

from benchmarks.matrix import report, run


def _read_config(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("matrix config must be a mapping")
    return data


def _run_llm_judge(config_path: Path) -> None:
    subprocess.run(
        ["uv", "run", "llm-judge", "evaluate", "--config", str(config_path)], check=True
    )


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="prepare, judge, and report a matrix suite")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out", type=Path, help="override run output directory")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--judge", action="store_true", help="run llm-judge after case preparation"
    )
    parser.add_argument(
        "--report", action="store_true", help="write matrix-report.md after judging"
    )
    parser.add_argument("--rag-baseline", default="classic_chunks:top_k=25")
    parser.add_argument("--full-baseline", default="full_selected_docs:top_k=25")
    args = parser.parse_args(argv)

    config = _read_config(args.config)
    run_cfg = config.get("run") or {}
    run_id = run_cfg.get("id") or "matrix"
    out_dir = args.out or Path(run_cfg.get("output_dir") or f".matrix-runs/{run_id}")

    prepare_args = ["--config", str(args.config)]
    if args.out:
        prepare_args.extend(["--out", str(args.out)])
    await run.main(prepare_args)

    llm_config = out_dir / "llm_judge.yaml"
    results_path = out_dir / "llm-judge" / "results.jsonl"
    report_path = out_dir / "matrix-report.md"

    if args.prepare_only:
        return
    if args.judge:
        _run_llm_judge(llm_config)
    if args.report:
        report.write_report(
            rows_path=results_path,
            out_path=report_path,
            rag_baseline=args.rag_baseline,
            full_doc_baseline=args.full_baseline,
        )
        print(f"wrote {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
