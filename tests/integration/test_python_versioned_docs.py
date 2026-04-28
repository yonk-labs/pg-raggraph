"""Integration test — Python versioned docs corpus is ingested with three
distinct version_labels in one namespace (SC-003 evidence).

Skips if the corpus hasn't been ingested yet (the corpus is benchmark
infrastructure, not a unit-test fixture). Run after
`benchmarks/python-versioned-docs/ingest.py`.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.asyncio

DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)


@pytest.fixture
async def db():
    from pg_raggraph.config import PGRGConfig
    from pg_raggraph.db import Database

    cfg = PGRGConfig(dsn=DSN, namespace="python_docs")
    database = Database(cfg)
    await database.connect()
    yield database
    await database.close()


async def _has_corpus(database) -> bool:
    row = await database.fetch_one(
        "SELECT COUNT(*) AS n FROM documents WHERE namespace = %s",
        ("python_docs",),
    )
    return bool(row and row["n"] > 0)


async def test_three_version_labels_present(db):
    """SC-003: three distinct version_labels in `python_docs` namespace."""
    if not await _has_corpus(db):
        pytest.skip(
            "python_docs corpus not ingested. "
            "Run `benchmarks/python-versioned-docs/ingest.py` first."
        )
    rows = await db.fetch_all(
        "SELECT DISTINCT version_label "
        "FROM documents "
        "WHERE namespace = %s AND version_label IS NOT NULL",
        ("python_docs",),
    )
    labels = {r["version_label"] for r in rows}
    assert labels == {"Python 3.10", "Python 3.11", "Python 3.12"}, labels


async def test_at_least_one_doc_per_version(db):
    """SC-003: each version has ≥ 1 ingested document."""
    if not await _has_corpus(db):
        pytest.skip(
            "python_docs corpus not ingested. "
            "Run `benchmarks/python-versioned-docs/ingest.py` first."
        )
    rows = await db.fetch_all(
        "SELECT version_label, COUNT(*) AS n FROM documents WHERE namespace = %s GROUP BY 1",
        ("python_docs",),
    )
    counts = {r["version_label"]: r["n"] for r in rows}
    for label in ("Python 3.10", "Python 3.11", "Python 3.12"):
        assert counts.get(label, 0) >= 1, f"{label}: {counts}"
