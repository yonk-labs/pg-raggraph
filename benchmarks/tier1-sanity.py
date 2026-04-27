"""Tier 1 sanity benchmark — runs tune_scoring_weights against the synthetic
medical-retraction and policy fixtures. Not a real-world benchmark — use it
to confirm the integration is wired and to inspect cell-by-cell scores.

Run:
    uv run python benchmarks/tier1-sanity.py
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from pg_raggraph import GraphRAG

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures" / "evolving"


async def _ingest_fixture_corpus(rag: GraphRAG, corpus_dir: Path) -> None:
    """Mirror of the test helper — coerces YAML dates to tz-aware UTC datetimes
    and strips the not-yet-wired supersedes_version_label hint."""
    import datetime as _dt

    manifest = yaml.safe_load((corpus_dir / "manifest.yaml").read_text())
    for entry in manifest["docs"]:
        path = str(corpus_dir / entry["path"])
        metadata = {
            k: v for k, v in entry.items() if k not in ("path", "supersedes_version_label")
        }
        for k in ("effective_from", "effective_to", "retracted_at"):
            v = metadata.get(k)
            if isinstance(v, str):
                parsed = datetime.fromisoformat(v)
                metadata[k] = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            elif isinstance(v, datetime):
                if v.tzinfo is None:
                    metadata[k] = v.replace(tzinfo=timezone.utc)
            elif isinstance(v, _dt.date):
                metadata[k] = datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
        await rag.ingest([path], namespace=corpus_dir.name, metadata=metadata)


async def run_corpus(corpus: str, gold: list[dict]) -> dict:
    rag = GraphRAG(
        dsn=DSN,
        namespace=corpus,
        evolution_tier="structural",
        retracted_behavior="hide",
        llm_base_url="http://localhost:99999/v1",  # unreachable — extraction skipped
    )
    await rag.connect()
    try:
        await rag.delete(corpus)
        await _ingest_fixture_corpus(rag, FIXTURES / corpus)
        # Strip per-question filters that tune_scoring_weights doesn't pass through.
        gold_clean = [
            {"question": g["question"], "expected_substring": g["expected_substring"]}
            for g in gold
        ]
        report = await rag.tune_scoring_weights(
            namespace=corpus,
            gold=gold_clean,
            grid={
                "w_sem": [0.3, 0.5, 0.7],
                "w_bm25": [0.1, 0.3],
                "w_recent": [0.0, 0.1, 0.3],
                "w_supersession": [0.0, 0.1],
            },
            mode="naive",
            write_back=False,  # don't mutate live config
        )
        return report
    finally:
        await rag.close()


async def main() -> None:
    gold = yaml.safe_load((FIXTURES / "gold_questions.yaml").read_text())["corpora"]

    print("=" * 72)
    print("Tier 1 sanity benchmark — synthetic fixture corpora")
    print("=" * 72)

    summary = {}
    for corpus in ("medical_retraction", "policy_effective_dates"):
        print(f"\n{corpus} ({len(gold[corpus]['questions'])} gold questions)")
        print("-" * 72)
        report = await run_corpus(corpus, gold[corpus]["questions"])
        max_score = len(gold[corpus]["questions"])
        best = report["best"]
        print(f"  best:    {best['score']}/{max_score}  weights={best['weights']}")
        print(f"  cells evaluated: {len(report['cells'])}")
        # Worst cell for contrast
        worst = min(report["cells"], key=lambda c: c["score"])
        print(f"  worst:   {worst['score']}/{max_score}  weights={worst['weights']}")
        # Score distribution
        from collections import Counter

        dist = Counter(c["score"] for c in report["cells"])
        print(f"  distribution: {dict(sorted(dist.items()))}")
        summary[corpus] = {
            "best_score": best["score"],
            "max_score": max_score,
            "best_weights": best["weights"],
            "cells": len(report["cells"]),
            "score_distribution": dict(sorted(dist.items())),
        }

    out = Path(__file__).parent / "tier1-sanity-results.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
