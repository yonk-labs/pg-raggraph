"""Integration test — medical_hrt corpus has correct evolution metadata,
synthetic fixture untouched (SC-005 evidence).

Skips if the corpus hasn't been ingested yet (this is a benchmark corpus,
not a unit-test fixture). Run after `benchmarks/medical-hrt/ingest.py`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio

DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def db():
    from pg_raggraph.config import PGRGConfig
    from pg_raggraph.db import Database

    cfg = PGRGConfig(dsn=DSN, namespace="medical_hrt")
    database = Database(cfg)
    await database.connect()
    yield database
    await database.close()


async def _has_corpus(database) -> bool:
    row = await database.fetch_one(
        "SELECT COUNT(*) AS n FROM documents WHERE namespace = %s",
        ("medical_hrt",),
    )
    return bool(row and row["n"] > 0)


async def test_min_30_docs_with_metadata(db):
    """SC-005: ≥30 docs with effective_from populated and ≥1 retracted."""
    if not await _has_corpus(db):
        pytest.skip(
            "medical_hrt corpus not ingested. Run `benchmarks/medical-hrt/ingest.py` first."
        )
    row = await db.fetch_one(
        "SELECT COUNT(*) AS n, COUNT(effective_from) AS ne, "
        "SUM(CASE WHEN retracted THEN 1 ELSE 0 END) AS nr "
        "FROM documents WHERE namespace = %s",
        ("medical_hrt",),
    )
    assert row["n"] >= 30, row
    assert row["ne"] == row["n"], "every doc must have effective_from"
    assert row["nr"] >= 1, "at least 1 retracted abstract expected"


@pytest.mark.asyncio(loop_scope="function")
async def test_synthetic_fixture_files_untouched():
    """SC-005 constraint: tests/fixtures/evolving/medical_retraction/ unchanged.

    Brief explicitly forbids modifying the synthetic fixture for the unit
    tests that depend on it. Async wrapper added only because pytest-asyncio
    auto-mode flags every test as async.
    """
    expected = {
        "manifest.yaml",
        "guidance_2002_hrt_contraindicated.md",
        "meta_2008_hrt_no_cardio.md",
        "paper_1992_hrt_cardio.md",
        "paper_1998_hrt_cardio_replication.md",
    }
    fixture_dir = PROJECT_ROOT / "tests/fixtures/evolving/medical_retraction"
    actual = {p.name for p in fixture_dir.iterdir()}
    assert actual == expected, actual.symmetric_difference(expected)
