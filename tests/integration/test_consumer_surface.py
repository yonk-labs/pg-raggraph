"""Integration tests for the PRG-1..4 consumer surface."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def _connect(**kwargs) -> GraphRAG:
    rag = GraphRAG(dsn=DSN, **kwargs)
    await rag.connect()
    return rag


async def test_prg1_metadata_round_trip_present():
    rag = await _connect(namespace="test_prg1_meta")
    try:
        await rag.delete("test_prg1_meta")
        await rag.ingest_records(
            [{"text": "Payment service outage on the checkout path.",
              "source_id": "doc:1", "metadata": {"k": "v", "stele_ref": "x://1"}}],
            namespace="test_prg1_meta",
        )
        res = await rag.query("payment outage", mode="naive", namespace="test_prg1_meta")
        assert res.chunks, "expected at least one hit"
        assert res.chunks[0].metadata == {"k": "v", "stele_ref": "x://1"}
    finally:
        await rag.delete("test_prg1_meta")
        await rag.close()


async def test_prg1_metadata_none_when_absent():
    rag = await _connect(namespace="test_prg1_nometa")
    try:
        await rag.delete("test_prg1_nometa")
        await rag.ingest_records(
            [{"text": "Payment service outage on the checkout path.",
              "source_id": "doc:1"}],
            namespace="test_prg1_nometa",
        )
        res = await rag.query("payment outage", mode="naive", namespace="test_prg1_nometa")
        assert res.chunks
        assert res.chunks[0].metadata is None
    finally:
        await rag.delete("test_prg1_nometa")
        await rag.close()


async def test_prg1_evolution_fields_none_when_tier_off():
    # Default evolution_tier == "off" (config.py:207).
    rag = await _connect(namespace="test_prg1_off")
    try:
        await rag.delete("test_prg1_off")
        await rag.ingest_records(
            [{"text": "Payment service outage.", "source_id": "doc:1",
              "metadata": {"k": "v"}}],
            namespace="test_prg1_off",
        )
        res = await rag.query("payment outage", mode="naive", namespace="test_prg1_off")
        assert res.chunks
        c = res.chunks[0]
        # metadata is tier-independent caller data — still returned
        assert c.metadata == {"k": "v"}
        # evolution fields are None when tier == "off" (DEC-5)
        assert c.retracted is None
        assert c.version_label is None
        assert c.effective_from is None
        assert c.effective_to is None
        assert c.superseded_by_id is None
    finally:
        await rag.delete("test_prg1_off")
        await rag.close()


async def test_prg1_retracted_true_under_flag():
    # evolution on + retracted_behavior="flag" (default): retracted docs still
    # surface, but chunk.retracted is True so the caller can act.
    rag = await _connect(
        namespace="test_prg1_flag",
        evolution_tier="structural",
        retracted_behavior="flag",
    )
    try:
        await rag.delete("test_prg1_flag")
        await rag.ingest_records(
            [{"text": "Deprecated API key rotation policy.",
              "source_id": "doc:1",
              "metadata": {"retracted": True, "retraction_reason": "obsolete"}}],
            namespace="test_prg1_flag",
        )
        res = await rag.query("API key rotation", mode="naive", namespace="test_prg1_flag")
        assert res.chunks
        assert res.chunks[0].retracted is True
    finally:
        await rag.delete("test_prg1_flag")
        await rag.close()


async def test_prg1_retracted_false_when_not_retracted():
    # evolution on, ordinary (non-retracted) doc → chunk.retracted is False
    # (not None, not True). Guards against an inverted column mapping on the
    # most common production path.
    rag = await _connect(
        namespace="test_prg1_notretracted",
        evolution_tier="structural",
    )
    try:
        await rag.delete("test_prg1_notretracted")
        await rag.ingest_records(
            [{"text": "Current API key rotation policy.",
              "source_id": "doc:1"}],
            namespace="test_prg1_notretracted",
        )
        res = await rag.query(
            "API key rotation", mode="naive", namespace="test_prg1_notretracted"
        )
        assert res.chunks
        assert res.chunks[0].retracted is False
    finally:
        await rag.delete("test_prg1_notretracted")
        await rag.close()


async def test_prg1_back_compat_scores_and_fields_unchanged():
    rag = await _connect(namespace="test_prg1_bc")
    try:
        await rag.delete("test_prg1_bc")
        await rag.ingest_records(
            [
                {"text": "Payment service outage on the checkout path.",
                 "source_id": "doc:1"},
                {"text": "Database failover runbook for the orders cluster.",
                 "source_id": "doc:2"},
            ],
            namespace="test_prg1_bc",
        )
        r1 = await rag.query("payment outage", mode="naive", namespace="test_prg1_bc")
        r2 = await rag.query("payment outage", mode="naive", namespace="test_prg1_bc")

        # Existing fields + scores are deterministic and unaffected.
        assert [c.content for c in r1.chunks] == [c.content for c in r2.chunks]
        assert [round(c.score, 9) for c in r1.chunks] == [
            round(c.score, 9) for c in r2.chunks
        ]
        assert [c.chunk_id for c in r1.chunks] == [c.chunk_id for c in r2.chunks]
        assert r1.top_score == r2.top_score
        # New optional fields are inert for a no-metadata ingest.
        for c in r1.chunks:
            assert c.metadata is None
            assert c.retracted is None
    finally:
        await rag.delete("test_prg1_bc")
        await rag.close()


async def test_prg2_retract_by_doc_id_and_temporal():
    rag = await _connect(
        namespace="test_prg2",
        evolution_tier="structural",
        retracted_behavior="flag",
    )
    try:
        await rag.delete("test_prg2")
        before_retract = datetime.now(timezone.utc) - timedelta(seconds=1)
        eff = datetime(2020, 1, 1, tzinfo=timezone.utc)
        await rag.ingest_records(
            [{"text": "Quarterly travel reimbursement policy details.",
              "source_id": "doc:1",
              "metadata": {"effective_from": eff}}],
            namespace="test_prg2",
        )
        row = await rag.db.fetch_one(
            "SELECT id FROM documents WHERE namespace=%s AND source_path=%s",
            ("test_prg2", "doc:1"),
        )
        doc_id = row["id"]

        out = await rag.retract(doc_id=doc_id, reason="superseded by FY26 policy")
        assert out == {"retracted_count": 1}

        # current query: retracted_behavior="flag" → still returned, flagged
        cur = await rag.query("travel reimbursement", mode="naive", namespace="test_prg2")
        assert cur.chunks and cur.chunks[0].retracted is True

        # document_versions captured the retraction
        dv = await rag.db.fetch_one(
            "SELECT retracted, retraction_reason FROM document_versions "
            "WHERE document_id=%s",
            (doc_id,),
        )
        assert dv["retracted"] is True
        assert dv["retraction_reason"] == "superseded by FY26 policy"

        # retraction is a non-temporal flag — it does NOT shrink the doc's
        # effective window. A historical (as_of before the retract) query
        # still returns the document (retraction did not delete it / alter
        # its effective_from). Document-level time-versioned retraction is
        # out of scope (PRG-5).
        hist = await rag.query(
            "travel reimbursement", mode="naive",
            namespace="test_prg2", as_of=before_retract,
        )
        assert hist.chunks
        assert any(c.document_source == "doc:1" for c in hist.chunks)

        # idempotent: second retract is a no-op success
        out2 = await rag.retract(doc_id=doc_id)
        assert out2 == {"retracted_count": 1}
        dv_count = await rag.db.fetch_one(
            "SELECT count(*) AS cnt FROM document_versions WHERE document_id=%s",
            (doc_id,),
        )
        assert dv_count["cnt"] == 1
    finally:
        await rag.delete("test_prg2")
        await rag.close()


async def test_prg2_retract_by_source_path_fans_out():
    rag = await _connect(namespace="test_prg2b", evolution_tier="structural")
    try:
        await rag.delete("test_prg2b")
        await rag.ingest_records(
            [{"text": "Alpha content one.", "source_id": "shared/path"},
             {"text": "Beta content two.", "source_id": "other/path"}],
            namespace="test_prg2b",
        )
        out = await rag.retract(source_path="shared/path", reason="cleanup")
        assert out == {"retracted_count": 1}
        other = await rag.db.fetch_one(
            "SELECT retracted FROM documents "
            "WHERE namespace=%s AND source_path=%s",
            ("test_prg2b", "other/path"),
        )
        assert other and other["retracted"] is False
    finally:
        await rag.delete("test_prg2b")
        await rag.close()


async def test_prg2_retract_rejects_naive_datetime_and_bad_args():
    rag = await _connect(namespace="test_prg2c")
    try:
        with pytest.raises(ValueError, match="timezone-aware"):
            await rag.retract(doc_id=1, retracted_at=datetime(2026, 1, 1))
        with pytest.raises(ValueError, match="exactly one"):
            await rag.retract()
        with pytest.raises(ValueError, match="exactly one"):
            await rag.retract(doc_id=1, source_path="x")
    finally:
        await rag.close()
