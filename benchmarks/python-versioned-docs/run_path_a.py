"""Path A runner — exercises pgrg's version_filter against the gold set.

For each question:
  - filtered_match / cross_version / whatsnew: run with version_filter; assert
    top-5 chunks come ONLY from the matching version_label.
  - unfiltered_target: run without filter; assert top-3 contains a chunk from
    the expected version.

Writes results.json with per-category pass rates and SC-004 verdict.

Plan adaptations applied:
- pgrg's Database API uses %s-style params and fetch_one(query, tuple) — not
  asyncpg's $1/.acquire().
- ChunkResult.chunk_id is the DB row id (Chunk.id), not .id on ChunkResult.
- documents.version_label is a real column (promoted from metadata at ingest);
  the resolver SQL uses d.version_label, NOT d.metadata->>'version_label'.
"""
from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from pathlib import Path

import yaml

from pg_raggraph import GraphRAG

ROOT = Path(__file__).parent
DSN = os.environ.get(
    "PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
)
NAMESPACE = "python_docs"
# rag.query() honors config.top_k (default 10); not exposed as a kwarg.
TOP_FILTER_CHECK = 5  # top-N for filtered version_label purity check
TOP_TARGET_CHECK = 3  # top-N for unfiltered target check


async def chunk_version(rag: GraphRAG, chunk_id: int | None) -> str | None:
    """Resolve a chunk DB id to its document's version_label."""
    if chunk_id is None:
        return None
    row = await rag.db.fetch_one(
        "SELECT d.version_label "
        "FROM chunks c JOIN documents d ON c.document_id = d.id "
        "WHERE c.id = %s",
        (chunk_id,),
    )
    return row["version_label"] if row else None


async def run_question(rag: GraphRAG, q: dict) -> dict:
    kwargs = {"namespace": NAMESPACE, "mode": "naive_boost"}
    if "version_filter" in q:
        kwargs["version_filter"] = q["version_filter"]
    result = await rag.query(q["question"], **kwargs)
    top_versions = [
        await chunk_version(rag, c.chunk_id) for c in result.chunks[:TOP_FILTER_CHECK]
    ]
    top3_versions = top_versions[:TOP_TARGET_CHECK]

    pass_filter = (
        "version_filter" not in q
        or all(v == q["version_filter"] for v in top_versions if v)
    )
    pass_target = (
        "expected_version_in_top3" not in q
        or q["expected_version_in_top3"] in top3_versions
    )
    return {
        "id": q["id"],
        "category": q["category"],
        "version_filter": q.get("version_filter"),
        "expected_version_in_top3": q.get("expected_version_in_top3"),
        "top_versions": top_versions,
        "n_chunks_returned": len(result.chunks),
        "pass_filter": pass_filter,
        "pass_target": pass_target,
        "passed": pass_filter and pass_target,
    }


async def main() -> None:
    qs = yaml.safe_load((ROOT / "gold.yaml").read_text())["questions"]
    rag = GraphRAG(dsn=DSN, evolution_tier="structural")
    await rag.connect()
    rows: list[dict] = []
    try:
        for q in qs:
            r = await run_question(rag, q)
            print(
                f"[{'PASS' if r['passed'] else 'FAIL'}] {r['id']} "
                f"({r['category']}): top5={r['top_versions']}",
                flush=True,
            )
            rows.append(r)
    finally:
        await rag.close()

    # Compute SC-004 metrics.
    filtered = [
        r
        for r in rows
        if r["category"] in ("filtered_match", "cross_version", "whatsnew")
    ]
    target = [r for r in rows if r["category"] == "unfiltered_target"]
    n_filt_pass = sum(1 for r in filtered if r["pass_filter"])
    n_target_pass = sum(1 for r in target if r["pass_target"])
    sc004_filter_rate = n_filt_pass / max(len(filtered), 1)
    sc004_target_pass = n_target_pass >= 1

    n_overall_pass = sum(1 for r in rows if r["passed"])
    by_cat: dict[str, dict] = {}
    for cat in {r["category"] for r in rows}:
        rs = [r for r in rows if r["category"] == cat]
        by_cat[cat] = {
            "n": len(rs),
            "n_passed": sum(1 for r in rs if r["passed"]),
            "rate": round(sum(1 for r in rs if r["passed"]) / max(len(rs), 1), 3),
        }

    summary = {
        "namespace": NAMESPACE,
        "n_total": len(rows),
        "n_overall_pass": n_overall_pass,
        "by_category": by_cat,
        "filtered": {
            "n": len(filtered),
            "n_pass_filter": n_filt_pass,
            "filter_rate": round(sc004_filter_rate, 3),
        },
        "target": {
            "n": len(target),
            "n_pass_target": n_target_pass,
        },
        "sc004_threshold_filter": "≥ 0.80",
        "sc004_filter_pass": sc004_filter_rate >= 0.80,
        "sc004_threshold_target": "≥ 1 of 2",
        "sc004_target_pass": sc004_target_pass,
        "sc004_overall_pass": (sc004_filter_rate >= 0.80) and sc004_target_pass,
        "rows": rows,
    }
    out = ROOT / "results.json"
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
