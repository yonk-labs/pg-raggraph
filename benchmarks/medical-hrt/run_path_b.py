"""Path B runner — exercises pgrg's retracted_behavior + as_of features.

retraction_aware Qs:
  - run with retracted_behavior="hide"
  - assert top-5 has ZERO retracted documents

time_travel Qs:
  - run with as_of=given datetime (1995-01-01)
  - assert top-5 has ≥1 pre-2002 supportive paper (we use effective_from year
    < 2002 as the proxy — that includes both retracted and non-retracted
    pre-WHI papers)

background Qs:
  - run with default flags (retracted_behavior="flag" by default)
  - just record top-5 retracted/year stats; pass on shape only

Writes results.json and prints summary.

Plan adaptations applied:
- documents.retracted is a real column; runner reads it directly via
  fetch_one. No metadata->>... lookups.
- ChunkResult.chunk_id is the DB id (Chunk.id).
- rag.query() does not accept top_k; default top_k=10 from config.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

from pg_raggraph import GraphRAG

ROOT = Path(__file__).parent
DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NAMESPACE = "medical_hrt"
TOP_FILTER_CHECK = 5  # top-N for retraction & time-travel checks


async def chunk_meta(rag: GraphRAG, chunk_id: int | None) -> dict:
    """Resolve a chunk DB id to {retracted, year}."""
    if chunk_id is None:
        return {}
    row = await rag.db.fetch_one(
        "SELECT d.retracted, EXTRACT(year FROM d.effective_from)::int AS y "
        "FROM chunks c JOIN documents d ON c.document_id = d.id "
        "WHERE c.id = %s",
        (chunk_id,),
    )
    return {"retracted": row["retracted"], "year": row["y"]} if row else {}


async def run_question(rag: GraphRAG, q: dict) -> dict:
    cat = q["category"]
    kwargs = {"namespace": NAMESPACE, "mode": "naive_boost"}
    # retracted_behavior is config-level (no per-call kwarg); toggle config.
    rag.config.retracted_behavior = "hide" if cat == "retraction_aware" else "flag"
    if cat == "time_travel":
        kwargs["as_of"] = datetime.fromisoformat(q["as_of"])
    result = await rag.query(q["question"], **kwargs)
    metas = [await chunk_meta(rag, c.chunk_id) for c in result.chunks[:TOP_FILTER_CHECK]]
    n_retracted_top = sum(1 for m in metas if m.get("retracted"))
    has_pre2002 = any(m.get("year") is not None and m["year"] < 2002 for m in metas)

    if cat == "retraction_aware":
        passed = n_retracted_top == 0
    elif cat == "time_travel":
        passed = has_pre2002
    else:
        # background: shape-only check (just confirm we get any results)
        passed = len(metas) > 0
    return {
        "id": q["id"],
        "category": cat,
        "as_of": q.get("as_of"),
        "n_chunks_returned": len(result.chunks),
        "top5_retracted_count": n_retracted_top,
        "top5_has_pre2002": has_pre2002,
        "top5_meta": metas,
        "passed": passed,
    }


async def main() -> None:
    qs = yaml.safe_load((ROOT / "gold.yaml").read_text())["questions"]
    rag = GraphRAG(dsn=DSN, evolution_tier="structural")
    await rag.connect()
    rows: list[dict] = []
    try:
        # Disable retraction_behavior for retrieval where we don't want
        # it; the retrieval-time kwargs handle it per-call.
        for q in qs:
            r = await run_question(rag, q)
            print(
                f"[{'PASS' if r['passed'] else 'FAIL'}] {r['id']} "
                f"({r['category']}): "
                f"retracted_top5={r['top5_retracted_count']} "
                f"pre2002={r['top5_has_pre2002']}",
                flush=True,
            )
            rows.append(r)
    finally:
        await rag.close()

    n_retraction = sum(1 for r in rows if r["category"] == "retraction_aware")
    n_retraction_pass = sum(1 for r in rows if r["category"] == "retraction_aware" and r["passed"])
    n_time = sum(1 for r in rows if r["category"] == "time_travel")
    n_time_pass = sum(1 for r in rows if r["category"] == "time_travel" and r["passed"])
    n_background_pass = sum(1 for r in rows if r["category"] == "background" and r["passed"])

    summary = {
        "namespace": NAMESPACE,
        "n_total": len(rows),
        "by_category": dict(Counter(r["category"] for r in rows)),
        "retraction_pass": f"{n_retraction_pass}/{n_retraction}",
        "sc006_threshold_retraction": "≥ 4/5 (zero retracted in top-5)",
        "sc006_retraction_pass": n_retraction_pass >= 4,
        "time_travel_pass": f"{n_time_pass}/{n_time}",
        "sc006_threshold_time_travel": "≥ 1/5 with pre-2002 paper in top-5",
        "sc006_time_travel_pass": n_time_pass >= 1,
        "sc006_overall_pass": (n_retraction_pass >= 4) and (n_time_pass >= 1),
        "background_pass": f"{n_background_pass}/5",
        "rows": rows,
    }
    out = ROOT / "results.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
