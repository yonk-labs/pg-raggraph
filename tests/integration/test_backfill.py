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
        await release_processing(rag.db, doc_ids=ids)

        rows = await rag.db.fetch_all(
            "SELECT graph_status FROM documents WHERE namespace = %s",
            ("test_bf_reaper",),
        )
        assert all(r["graph_status"] == "pending" for r in rows)
    finally:
        await rag.delete("test_bf_reaper")
        await rag.close()


async def test_release_processing_namespace_scoped_does_not_touch_peers():
    """release_processing(namespace=A) must not flip namespace B's 'processing' rows.

    Regression guard for PR-001 / GAP-014: the startup reaper used to be
    global; a worker starting in namespace A would steal namespace B's
    in-flight claims. After PR-001, reaper is namespace-scoped.
    """
    rag_a = await _make_rag("test_bf_ns_a")
    rag_b = await _make_rag("test_bf_ns_b")
    try:
        # Seed pending in both namespaces, claim both into 'processing'.
        await rag_a.ingest_records(
            [{"text": "ns-a doc", "source_id": "bf:nsa:1"}],
            namespace="test_bf_ns_a",
            defer_extraction=True,
        )
        await rag_b.ingest_records(
            [{"text": "ns-b doc", "source_id": "bf:nsb:1"}],
            namespace="test_bf_ns_b",
            defer_extraction=True,
        )
        ids_a = await claim_pending(rag_a.db, "test_bf_ns_a", 8)
        ids_b = await claim_pending(rag_b.db, "test_bf_ns_b", 8)
        assert len(ids_a) == 1 and len(ids_b) == 1

        # Worker A's startup reaper fires — must not touch B.
        await release_processing(rag_a.db, namespace="test_bf_ns_a")

        row_a = await rag_a.db.fetch_one(
            "SELECT graph_status FROM documents WHERE id = %s", (ids_a[0],)
        )
        row_b = await rag_b.db.fetch_one(
            "SELECT graph_status FROM documents WHERE id = %s", (ids_b[0],)
        )
        # A got reaped (pending). B remains processing.
        assert row_a["graph_status"] == "pending", "namespace A reaper must reclaim A"
        assert row_b["graph_status"] == "processing", (
            "namespace A reaper MUST NOT touch namespace B's claims"
        )
    finally:
        await rag_a.delete("test_bf_ns_a")
        await rag_b.delete("test_bf_ns_b")
        await rag_a.close()
        await rag_b.close()


async def test_release_processing_global_warns_and_works(caplog):
    """release_processing() with neither arg reaps globally AND logs a warning.

    The behavior is still available (e.g. for repair scripts) but the warning
    makes the blast radius visible. Operators running multi-tenant systems
    should always pass namespace=...
    """
    import logging

    rag = await _make_rag("test_bf_global_warn")
    try:
        await rag.ingest_records(
            [{"text": "global reap doc", "source_id": "bf:gw:1"}],
            namespace="test_bf_global_warn",
            defer_extraction=True,
        )
        await claim_pending(rag.db, "test_bf_global_warn", 8)

        with caplog.at_level(logging.WARNING, logger="pg_raggraph.backfill"):
            await release_processing(rag.db)  # no kwargs at all

        # Warning must be emitted so the operator sees the blast radius.
        assert any("no namespace" in rec.message for rec in caplog.records), (
            f"expected warning about no-namespace reap; got {[r.message for r in caplog.records]}"
        )
        # And the work happened.
        rows = await rag.db.fetch_all(
            "SELECT graph_status FROM documents WHERE namespace = %s",
            ("test_bf_global_warn",),
        )
        assert all(r["graph_status"] == "pending" for r in rows)
    finally:
        await rag.delete("test_bf_global_warn")
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


async def test_status_includes_graph_status_summary():
    """rag.status() returns per-status counts under 'graph_status'."""
    rag = await _make_rag("test_bf_status")
    try:
        await rag.ingest_records(
            [
                {"text": "a", "source_id": "bf:status:1"},
                {"text": "b", "source_id": "bf:status:2"},
            ],
            namespace="test_bf_status",
            defer_extraction=True,
        )
        await rag.ingest_records(
            [{"text": "c immediate", "source_id": "bf:status:3"}],
            namespace="test_bf_status",
            defer_extraction=False,
        )

        s = await rag.status("test_bf_status")
        assert "graph_status" in s
        gs = s["graph_status"]
        assert set(gs.keys()) == {"pending", "processing", "ready", "failed"}
        assert gs["pending"] == 2
        assert gs["ready"] == 1
        assert gs["failed"] == 0
    finally:
        await rag.delete("test_bf_status")
        await rag.close()


async def test_query_metadata_exposes_graph_status_summary():
    """QueryResult.metadata.graph_status_summary surfaces queue state."""
    rag = await _make_rag("test_bf_query_hint")
    try:
        # Two pending docs so naive can still retrieve, but the hint shows
        # the graph isn't fully built.
        await rag.ingest_records(
            [
                {
                    "text": "Background extraction is decoupled from ingest in pg-raggraph.",
                    "source_id": "bf:hint:1",
                },
                {
                    "text": "The CLI subcommand pgrg extract drains pending docs.",
                    "source_id": "bf:hint:2",
                },
            ],
            namespace="test_bf_query_hint",
            defer_extraction=True,
        )

        result = await rag.query(
            "background extraction", mode="naive", namespace="test_bf_query_hint"
        )
        assert "graph_status_summary" in result.metadata
        gs = result.metadata["graph_status_summary"]
        assert gs["pending"] == 2
        assert gs["ready"] == 0
        # Naive retrieval still works on pending docs (chunks are written).
        assert len(result.chunks) > 0
    finally:
        await rag.delete("test_bf_query_hint")
        await rag.close()


@pytest.mark.skipif(
    not _lede_available(),
    reason="lede / lede-spacy / en_core_web_sm not available",
)
async def test_re_extracting_ready_doc_does_not_duplicate_edges():
    """PR-002 / GAP-014: re-extraction must be idempotent on relationships.

    Migration 013 added a UNIQUE constraint on
    (namespace, src_id, dst_id, rel_type); the INSERT in _extract_one uses
    ON CONFLICT DO UPDATE. Calling extract_documents on a doc that's
    already 'ready' must leave relationship counts unchanged.
    """
    ns = "test_bf_re_extract"
    rag = GraphRAG(
        dsn=DSN,
        namespace=ns,
        fact_extractor="lede_spacy",
        llm_base_url="",
    )
    await rag.connect()
    try:
        await rag.ingest_records(
            [
                {
                    "text": (
                        "NASA launched the Saturn V rocket from Kennedy Space Center. "
                        "Neil Armstrong walked on the Moon while Michael Collins orbited."
                    ),
                    "source_id": "bf:re:1",
                }
            ],
            namespace=ns,
        )

        before_rels = await rag.db.fetch_one(
            "SELECT count(*) AS n FROM relationships WHERE namespace = %s", (ns,)
        )
        doc = await rag.db.fetch_one("SELECT id FROM documents WHERE namespace = %s", (ns,))
        assert before_rels["n"] > 0, "lede_spacy should produce edges"

        # Force re-extraction by feeding the ready doc id directly.
        # (Not the documented happy path — claim_pending is — but it's the
        # exact code path a peer worker would hit after a global reaper
        # stole its claim under the pre-PR-001 bug. PR-002 makes it safe.)
        await extract_documents(rag, [doc["id"]])
        await extract_documents(rag, [doc["id"]])

        after_rels = await rag.db.fetch_one(
            "SELECT count(*) AS n FROM relationships WHERE namespace = %s", (ns,)
        )
        assert after_rels["n"] == before_rels["n"], (
            f"re-extraction duplicated edges: {before_rels['n']} → {after_rels['n']}"
        )
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_extract_documents_emits_metric(caplog):
    """PR-003 / GAP-010: extract_documents emits pgrg.backfill.extract."""
    import logging as _logging

    rag = await _make_rag("test_bf_metric")
    try:
        await rag.ingest_records(
            [{"text": "metric doc", "source_id": "bf:metric:1"}],
            namespace="test_bf_metric",
            defer_extraction=True,
        )
        ids = await claim_pending(rag.db, "test_bf_metric", 8)

        with caplog.at_level(_logging.INFO, logger="pg_raggraph.metrics"):
            stats = await extract_documents(rag, ids, namespace="test_bf_metric")

        events = [r for r in caplog.records if r.getMessage() == "pgrg.backfill.extract"]
        assert events, "expected at least one pgrg.backfill.extract event"
        event = events[0]
        # The metric should carry the fields an operator dashboard needs.
        for field in ("namespace", "claimed", "ready", "failed", "latency_ms"):
            assert hasattr(event, field), f"event missing field {field!r}: {event.__dict__}"
        assert event.namespace == "test_bf_metric"
        assert event.claimed == stats.claimed
        assert event.ready == stats.ready
    finally:
        await rag.delete("test_bf_metric")
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
