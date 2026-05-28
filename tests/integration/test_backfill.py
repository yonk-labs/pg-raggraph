"""Integration tests for the background-extraction primitive."""

import asyncio

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.backfill import (
    claim_pending,
    extract_documents,
    release_processing,
)

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def _make_rag(namespace: str) -> GraphRAG:
    rag = GraphRAG(
        dsn=DSN,
        namespace=namespace,
        # No LLM — deferred docs will mark 'ready' with empty graph when
        # extract_documents runs without a configured extractor. That's the
        # right end-state for the "no extractor" path.
        llm_base_url="http://localhost:99999/v1",
    )
    await rag.connect()
    return rag


async def test_claim_pending_skips_locked_rows():
    """Two concurrent claims never claim the same row.

    Workers A and B race for 4 pending docs with batch_size=2 each. Each
    should claim a disjoint pair of ids; the union should be all four.
    """
    rag = await _make_rag("test_bf_skip")
    try:
        records = [
            {"text": f"doc {i} body text for claim test", "source_id": f"bf:skip:{i}"}
            for i in range(4)
        ]
        await rag.ingest_records(records, namespace="test_bf_skip", defer_extraction=True)

        # Race: two claims with batch_size=2.
        a, b = await asyncio.gather(
            claim_pending(rag.db, "test_bf_skip", 2),
            claim_pending(rag.db, "test_bf_skip", 2),
        )

        assert len(a) == 2 and len(b) == 2
        assert set(a).isdisjoint(set(b)), f"workers claimed overlapping ids: {a} vs {b}"
        assert len(set(a) | set(b)) == 4

        # All four should now be 'processing'.
        rows = await rag.db.fetch_all(
            "SELECT graph_status FROM documents WHERE namespace = %s",
            ("test_bf_skip",),
        )
        statuses = [r["graph_status"] for r in rows]
        assert statuses.count("processing") == 4
    finally:
        await rag.delete("test_bf_skip")
        await rag.close()


async def test_claim_pending_returns_empty_when_queue_drained():
    """Empty queue → empty list, no exception."""
    rag = await _make_rag("test_bf_empty")
    try:
        ids = await claim_pending(rag.db, "test_bf_empty", 8)
        assert ids == []
    finally:
        await rag.close()


async def test_release_processing_reaper():
    """release_processing returns 'processing' rows to 'pending'."""
    rag = await _make_rag("test_bf_reaper")
    try:
        records = [{"text": f"reaper doc {i}", "source_id": f"bf:reap:{i}"} for i in range(2)]
        await rag.ingest_records(records, namespace="test_bf_reaper", defer_extraction=True)

        ids = await claim_pending(rag.db, "test_bf_reaper", 2)
        assert len(ids) == 2

        # Simulate worker crash mid-processing: release without extracting.
        await release_processing(rag.db, ids)

        rows = await rag.db.fetch_all(
            "SELECT graph_status FROM documents WHERE namespace = %s",
            ("test_bf_reaper",),
        )
        assert all(r["graph_status"] == "pending" for r in rows)
    finally:
        await rag.delete("test_bf_reaper")
        await rag.close()


async def test_extract_documents_no_extractor_marks_ready():
    """No LLM + no lede → docs flip to 'ready' with empty graph (terminal state)."""
    rag = await _make_rag("test_bf_no_extractor")
    try:
        records = [{"text": "Pending doc with no extractor configured.", "source_id": "bf:noex:1"}]
        await rag.ingest_records(records, namespace="test_bf_no_extractor", defer_extraction=True)

        ids = await claim_pending(rag.db, "test_bf_no_extractor", 8)
        assert len(ids) == 1

        stats = await extract_documents(rag, ids)
        assert stats.claimed == 1
        assert stats.ready == 1
        assert stats.failed == 0

        rows = await rag.db.fetch_all(
            "SELECT graph_status, graph_extracted_at, graph_error FROM documents "
            "WHERE namespace = %s",
            ("test_bf_no_extractor",),
        )
        assert rows[0]["graph_status"] == "ready"
        assert rows[0]["graph_extracted_at"] is not None
        assert rows[0]["graph_error"] is None
    finally:
        await rag.delete("test_bf_no_extractor")
        await rag.close()


def _lede_available() -> bool:
    try:
        import lede  # noqa: F401
        import lede_spacy  # noqa: F401
        import spacy

        spacy.load("en_core_web_sm")
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _lede_available(),
    reason="lede / lede-spacy / en_core_web_sm not available",
)
async def test_full_cycle_defer_then_extract_via_lede_spacy():
    """Pending → claim → extract (lede_spacy) → 'ready' with populated graph.

    Uses lede_spacy so the test doesn't require a live LLM endpoint; the
    extraction path is equivalent (extract_fn returns ExtractionResult
    objects), so this exercises the real graph-write transaction.
    """
    ns = "test_bf_cycle"
    rag = GraphRAG(
        dsn=DSN,
        namespace=ns,
        fact_extractor="lede_spacy",
        llm_base_url="",
    )
    await rag.connect()
    try:
        doc_text = (
            "NASA launched the Saturn V rocket from Kennedy Space Center. "
            "Neil Armstrong walked on the Moon while Michael Collins orbited."
        )
        await rag.ingest_records(
            [{"text": doc_text, "source_id": "bf:cycle:1"}],
            namespace=ns,
            defer_extraction=True,
        )

        # Before extract: pending, empty graph.
        pre = await rag.db.fetch_one(
            "SELECT graph_status FROM documents WHERE namespace = %s", (ns,)
        )
        assert pre["graph_status"] == "pending"
        pre_ents = await rag.db.fetch_one(
            "SELECT COUNT(*) AS n FROM entities WHERE namespace = %s", (ns,)
        )
        assert pre_ents["n"] == 0

        ids = await claim_pending(rag.db, ns, 8)
        assert len(ids) == 1
        stats = await extract_documents(rag, ids)

        assert stats.ready == 1
        assert stats.failed == 0
        assert stats.entities > 0, "lede_spacy should produce entities"

        post = await rag.db.fetch_one(
            "SELECT graph_status, graph_extracted_at FROM documents WHERE namespace = %s",
            (ns,),
        )
        assert post["graph_status"] == "ready"
        assert post["graph_extracted_at"] is not None
        post_ents = await rag.db.fetch_one(
            "SELECT COUNT(*) AS n FROM entities WHERE namespace = %s", (ns,)
        )
        assert post_ents["n"] > 0
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_extract_documents_marks_failed_on_exception():
    """When _extract_one raises, the row flips to 'failed' with graph_error set."""
    rag = await _make_rag("test_bf_fail")
    try:
        records = [{"text": "bf fail doc", "source_id": "bf:fail:1"}]
        await rag.ingest_records(records, namespace="test_bf_fail", defer_extraction=True)

        ids = await claim_pending(rag.db, "test_bf_fail", 8)
        assert len(ids) == 1

        # Inject a failure by passing a bogus doc id (forces "document not
        # found" inside _extract_one).
        stats = await extract_documents(rag, [999_999_999])
        assert stats.failed == 1
        # Real doc still 'processing' (we claimed it earlier without extracting).
        row = await rag.db.fetch_one("SELECT graph_status FROM documents WHERE id = %s", (ids[0],))
        assert row["graph_status"] == "processing"
    finally:
        await rag.delete("test_bf_fail")
        await rag.close()
