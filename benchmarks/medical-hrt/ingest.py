"""Ingest medical-hrt corpus into pgrg with full Tier 1 evolution metadata.

Each abstract becomes one document under namespace `medical_hrt`. The
ingest API auto-promotes effective_from / retracted / retracted_at /
version_label keys from `metadata` to dedicated columns on `documents`.

Re-runs are idempotent (content_hash UNIQUE constraint). The synthetic
fixture at tests/fixtures/evolving/medical_retraction/ is NOT touched.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import yaml

from pg_raggraph import GraphRAG

ROOT = Path(__file__).parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NAMESPACE = "medical_hrt"


def parse_dt(s: str | None) -> datetime | None:
    """Parse ISO-8601; require tz-aware (cookbook requires it)."""
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"Naive datetime not allowed: {s}")
    return dt


async def main() -> None:
    manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text())["abstracts"]
    rag = GraphRAG(dsn=DSN, namespace=NAMESPACE, evolution_tier="structural")
    await rag.connect()
    try:
        n = 0
        for entry in manifest:
            # manifest stores project-root-relative paths
            doc = json.loads((PROJECT_ROOT / entry["file"]).read_text())
            tmp = ROOT / "_tmp" / f"{entry['pmid']}.md"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(f"# {doc['title']}\n\n{doc['abstract']}")
            md: dict = {
                "effective_from": parse_dt(entry["effective_from"]),
                "retracted": entry["retracted"],
            }
            if entry.get("retracted_at"):
                md["retracted_at"] = parse_dt(entry["retracted_at"])
            if entry.get("retraction_reason"):
                md["retraction_reason"] = entry["retraction_reason"]
            await rag.ingest([str(tmp)], namespace=NAMESPACE, metadata=md)
            n += 1
            print(
                f"  + {entry['pmid']} ({entry['pub_year']}) retracted={entry['retracted']}",
                flush=True,
            )
        print(f"ingested {n} abstracts")
    finally:
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
