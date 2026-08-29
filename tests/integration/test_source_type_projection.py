"""Integration test for documents.source_type (issue #38): ingest-time stamp
surfaces through retrieval so multi-source responses are identifiable.
"""

from __future__ import annotations

import os
import time

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NS = f"test_pgrg_{int(time.time())}_source_type"


@pytest.fixture
async def rag():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)
    try:
        yield rag
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_source_type_projects_through_query(rag):
    """Call-level stamp + per-record override + unstamped default, all
    visible on QueryResult.chunks[*].source_type."""
    await rag.ingest_records(
        [
            {"text": "The quarterly sales figures for Acme improved.", "source_id": "crm:1"},
            {
                "text": "Ticket about Acme quarterly sales dashboard bug.",
                "source_id": "jira:1",
                "source_type": "ticket",
            },
        ],
        namespace=NS,
        source_type="crm_note",
        defer_extraction=True,
    )
    await rag.ingest_records(
        [{"text": "Acme quarterly sales meeting notes, unlabeled.", "source_id": "misc:1"}],
        namespace=NS,
        defer_extraction=True,
    )

    result = await rag.query("Acme quarterly sales", namespace=NS, mode="naive", top_k=10)
    by_doc = {c.document_source: c.source_type for c in result.chunks}
    assert by_doc["crm:1"] == "crm_note"  # call-level stamp
    assert by_doc["jira:1"] == "ticket"  # per-record override wins
    assert by_doc["misc:1"] is None  # unstamped stays NULL


@pytest.mark.asyncio
async def test_reingest_without_source_type_keeps_existing(rag):
    """Re-ingesting the same content without a stamp must not wipe the
    stored source_type (COALESCE semantics, same as version_label)."""
    rec = [{"text": "Stable content for the coalesce check.", "source_id": "s:1"}]
    await rag.ingest_records(rec, namespace=NS, source_type="wiki", defer_extraction=True)
    await rag.ingest_records(rec, namespace=NS, defer_extraction=True)

    result = await rag.query("stable coalesce check", namespace=NS, mode="naive", top_k=5)
    assert any(c.source_type == "wiki" for c in result.chunks)
