"""Integration test for defer_lexical_stats bulk-load path (issue #97).

Requires PG on :5434 (override with PGRG_TEST_DSN). Verifies that
ingest_records(defer_lexical_stats=True) skips the migration-016 lexstats
triggers during the load (so lexeme_stats stays empty) while still populating
chunks.search_vector, and that rebuild_lexical_stats() then reconstructs exact
stats — the documented bulk-load workflow.
"""

from __future__ import annotations

import os

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NS = "test_defer_lexstats"

RECORDS = [
    {"source_id": "d1", "text": "validate_billing_archive checks every record before rollover."},
    {"source_id": "d2", "text": "The billing team reviews valid records every quarter."},
]


async def _lexeme_count(db, ns) -> int:
    row = await db.fetch_one(
        "SELECT count(*) AS n FROM lexeme_stats WHERE namespace = %s AND df > 0", (ns,)
    )
    return row["n"]


async def _chunks_with_vector(db, ns) -> int:
    row = await db.fetch_one(
        "SELECT count(*) AS n FROM chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE d.namespace = %s AND c.search_vector IS NOT NULL",
        (ns,),
    )
    return row["n"]


@pytest.mark.asyncio
async def test_defer_skips_triggers_then_rebuild_reconstructs():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    try:
        await rag.delete(NS)

        # Deferred bulk load: triggers skipped, but search_vector still lands.
        await rag.ingest_records(
            RECORDS, namespace=NS, defer_lexical_stats=True, defer_extraction=True
        )

        assert await _chunks_with_vector(rag.db, NS) == 2, "search_vector must still populate"
        assert await _lexeme_count(rag.db, NS) == 0, "lexstats triggers must be deferred"

        # Rebuild reconstructs exact stats from chunks.search_vector.
        result = await rag.rebuild_lexical_stats(NS)
        assert result["lexemes"] > 0
        assert await _lexeme_count(rag.db, NS) > 0
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_non_deferred_ingest_populates_immediately():
    """Control: without the flag, triggers maintain stats during the load."""
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    try:
        await rag.delete(NS)
        await rag.ingest_records(RECORDS, namespace=NS, defer_extraction=True)
        assert await _lexeme_count(rag.db, NS) > 0, "triggers should populate stats inline"
    finally:
        await rag.delete(NS)
        await rag.close()
