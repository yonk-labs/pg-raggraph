"""F1 validation: time pgrg storage step on SCOTUS extraction cache.

Loads the pre-extracted SCOTUS JSON, calls PgrgEngine.ingest() once,
prints elapsed seconds. Uses an isolated namespace so it doesn't
disturb the canonical bench_scotus data.

Pre-F1 measurement: ~14 minutes (per ingest-medical-v2.log timestamps).
Target after F1: <3 minutes.
Stretch with F1+F2: <90s.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "benchmarks" / "age-bakeoff" / "src"))

from age_bakeoff.corpora.scotus import ScotusCorpus  # noqa: E402
from age_bakeoff.engines.pgrg import PgrgEngine  # noqa: E402

DSN = "postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg"
NAMESPACE = "f1_validation_scotus"


async def main() -> None:
    print("Loading SCOTUS extraction (cache → chunked ExtractionOutput)")
    extraction = ScotusCorpus().load()
    print(
        f"  chunks: {len(extraction.chunks)}  "
        f"entities: {len(extraction.entities)}  "
        f"relationships: {len(extraction.relationships)}"
    )

    engine = PgrgEngine(dsn=DSN, namespace=NAMESPACE)

    print(f"Ingesting into namespace={NAMESPACE} ...")
    t0 = time.perf_counter()
    await engine.ingest(extraction)
    elapsed = time.perf_counter() - t0

    print()
    print("=" * 60)
    print(f"F1 storage step: {elapsed:.1f}s ({elapsed / 60:.2f} min)")
    print("Pre-F1 baseline: ~14 min (~840s) — see ingest-medical-v2.log")
    print(f"Speedup vs baseline: ~{840 / max(elapsed, 1):.1f}×")
    print(f"AGE reference:   ~50s")
    print(f"Ratio vs AGE:    {elapsed / 50:.1f}×")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
