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
            [
                {
                    "text": "Payment service outage on the checkout path.",
                    "source_id": "doc:1",
                    "metadata": {"k": "v", "stele_ref": "x://1"},
                }
            ],
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
            [{"text": "Payment service outage on the checkout path.", "source_id": "doc:1"}],
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
            [{"text": "Payment service outage.", "source_id": "doc:1", "metadata": {"k": "v"}}],
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
            [
                {
                    "text": "Deprecated API key rotation policy.",
                    "source_id": "doc:1",
                    "metadata": {"retracted": True, "retraction_reason": "obsolete"},
                }
            ],
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
            [{"text": "Current API key rotation policy.", "source_id": "doc:1"}],
            namespace="test_prg1_notretracted",
        )
        res = await rag.query("API key rotation", mode="naive", namespace="test_prg1_notretracted")
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
                {"text": "Payment service outage on the checkout path.", "source_id": "doc:1"},
                {
                    "text": "Database failover runbook for the orders cluster.",
                    "source_id": "doc:2",
                },
            ],
            namespace="test_prg1_bc",
        )
        r1 = await rag.query("payment outage", mode="naive", namespace="test_prg1_bc")
        r2 = await rag.query("payment outage", mode="naive", namespace="test_prg1_bc")

        # Existing fields + scores are deterministic and unaffected.
        assert [c.content for c in r1.chunks] == [c.content for c in r2.chunks]
        assert [round(c.score, 9) for c in r1.chunks] == [round(c.score, 9) for c in r2.chunks]
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
            [
                {
                    "text": "Quarterly travel reimbursement policy details.",
                    "source_id": "doc:1",
                    "metadata": {"effective_from": eff},
                }
            ],
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
            "SELECT retracted, retraction_reason FROM document_versions WHERE document_id=%s",
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
            "travel reimbursement",
            mode="naive",
            namespace="test_prg2",
            as_of=before_retract,
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
            [
                {"text": "Alpha content one.", "source_id": "shared/path"},
                {"text": "Beta content two.", "source_id": "other/path"},
            ],
            namespace="test_prg2b",
        )
        out = await rag.retract(source_path="shared/path", reason="cleanup")
        assert out == {"retracted_count": 1}
        other = await rag.db.fetch_one(
            "SELECT retracted FROM documents WHERE namespace=%s AND source_path=%s",
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


async def test_prg3_supersede_temporal_and_behavior():
    rag = await _connect(
        namespace="test_prg3",
        evolution_tier="structural",
        supersession_behavior="hide",
    )
    try:
        await rag.delete("test_prg3")
        a_eff = datetime(2020, 1, 1, tzinfo=timezone.utc)
        await rag.ingest_records(
            [
                {
                    "text": "Onboarding checklist version A.",
                    "source_id": "doc:A",
                    "metadata": {"effective_from": a_eff},
                },
                {
                    "text": "Onboarding checklist version B revised.",
                    "source_id": "doc:B",
                    "metadata": {"effective_from": a_eff},
                },
            ],
            namespace="test_prg3",
        )
        a = await rag.db.fetch_one(
            "SELECT id FROM documents WHERE namespace=%s AND source_path=%s",
            ("test_prg3", "doc:A"),
        )
        b = await rag.db.fetch_one(
            "SELECT id FROM documents WHERE namespace=%s AND source_path=%s",
            ("test_prg3", "doc:B"),
        )

        before = datetime(2021, 1, 1, tzinfo=timezone.utc)
        eff_at = datetime.now(timezone.utc)
        out = await rag.supersede(
            old_doc_id=a["id"],
            new_doc_id=b["id"],
            reason="B revises A",
            effective_at=eff_at,
        )
        assert out == {"updated": 1}

        # supersedes pointer (new -> old) recorded
        dv = await rag.db.fetch_one(
            "SELECT supersedes_document_id, metadata FROM document_versions WHERE document_id=%s",
            (b["id"],),
        )
        assert dv["supersedes_document_id"] == a["id"]
        assert dv["metadata"].get("supersede_reason") == "B revises A"

        # old doc got effective_to = eff_at
        ad = await rag.db.fetch_one("SELECT effective_to FROM documents WHERE id=%s", (a["id"],))
        assert ad["effective_to"] is not None

        # supersession_behavior="hide": A no longer surfaces in current query
        cur = await rag.query("onboarding checklist", mode="naive", namespace="test_prg3")
        assert all(c.document_source != "doc:A" for c in cur.chunks)

        # as_of before effective_at still returns A (temporal window)
        hist = await rag.query(
            "onboarding checklist", mode="naive", namespace="test_prg3", as_of=before
        )
        assert any(c.document_source == "doc:A" for c in hist.chunks)
    finally:
        await rag.delete("test_prg3")
        await rag.close()


async def test_prg3_supersede_ambiguous_path_raises():
    rag = await _connect(namespace="test_prg3b")
    try:
        await rag.delete("test_prg3b")
        # Two docs share a source_path → ambiguous for a doc->doc pointer.
        await rag.db.execute(
            "INSERT INTO documents (namespace, content_hash, source_path) "
            "VALUES (%s,%s,%s),(%s,%s,%s)",
            ("test_prg3b", "h1", "dup/path", "test_prg3b", "h2", "dup/path"),
        )
        await rag.ingest_records(
            [{"text": "Unique target doc.", "source_id": "unique/path"}],
            namespace="test_prg3b",
        )
        with pytest.raises(ValueError, match="resolved to 2 documents"):
            await rag.supersede(old_source_path="dup/path", new_source_path="unique/path")
        with pytest.raises(ValueError, match="exactly one"):
            await rag.supersede(new_source_path="unique/path")
    finally:
        await rag.delete("test_prg3b")
        await rag.close()


async def test_prg3_legacy_supersede_without_effective_to_stays_hidden():
    # Back-compat guard: a doc superseded the LEGACY way (a document_versions
    # supersedes pointer with NO effective_to on the old doc) must stay hidden
    # under supersession_behavior="hide" even in an as_of query — the as_of
    # branch only relaxes the existence-hide for docs that have an
    # effective_to (set by supersede()).
    rag = await _connect(
        namespace="test_prg3c",
        evolution_tier="structural",
        supersession_behavior="hide",
    )
    try:
        await rag.delete("test_prg3c")
        old_eff = datetime(2020, 1, 1, tzinfo=timezone.utc)
        await rag.ingest_records(
            [
                {
                    "text": "Legacy onboarding doc OLD.",
                    "source_id": "leg:OLD",
                    "metadata": {"effective_from": old_eff},
                },
                {
                    "text": "Legacy onboarding doc NEW.",
                    "source_id": "leg:NEW",
                    "metadata": {"effective_from": old_eff},
                },
            ],
            namespace="test_prg3c",
        )
        old = await rag.db.fetch_one(
            "SELECT id, effective_to FROM documents WHERE namespace=%s AND source_path=%s",
            ("test_prg3c", "leg:OLD"),
        )
        new = await rag.db.fetch_one(
            "SELECT id FROM documents WHERE namespace=%s AND source_path=%s",
            ("test_prg3c", "leg:NEW"),
        )
        # Simulate the legacy ingest-time supersedes pointer: NEW supersedes
        # OLD, but OLD.effective_to is left NULL (supersede() was NOT used).
        await rag.db.execute(
            "INSERT INTO document_versions "
            "(namespace, document_id, supersedes_document_id) "
            "VALUES (%s, %s, %s)",
            ("test_prg3c", new["id"], old["id"]),
        )
        assert old["effective_to"] is None  # legacy: no temporal boundary

        # current query: existence-hide → OLD hidden
        cur = await rag.query("legacy onboarding", mode="naive", namespace="test_prg3c")
        assert all(c.document_source != "leg:OLD" for c in cur.chunks)

        # historical query: OLD has no effective_to, so the guard keeps the
        # existence-hide → OLD still hidden (no back-compat regression).
        before = datetime(2021, 1, 1, tzinfo=timezone.utc)
        hist = await rag.query(
            "legacy onboarding", mode="naive", namespace="test_prg3c", as_of=before
        )
        assert all(c.document_source != "leg:OLD" for c in hist.chunks)
    finally:
        await rag.delete("test_prg3c")
        await rag.close()


async def test_prg3_supersede_arg_validation_parity():
    rag = await _connect(namespace="test_prg3d")
    try:
        with pytest.raises(ValueError, match="exactly one"):
            await rag.supersede(old_doc_id=1, old_source_path="x", new_doc_id=2)
        with pytest.raises(ValueError, match="exactly one"):
            await rag.supersede(old_doc_id=1)  # new side missing
    finally:
        await rag.close()


async def test_prg3_retract_then_supersede_uses_live_version_row():
    # DEC-9 (amended): if retract() wrote a retraction-audit version row for
    # the NEW doc first, supersede() must NOT commingle the supersedes pointer
    # onto that retraction row — it targets a live (retracted=false) row,
    # inserting one if none exists.
    rag = await _connect(
        namespace="test_prg3e",
        evolution_tier="structural",
        retracted_behavior="flag",
    )
    try:
        await rag.delete("test_prg3e")
        await rag.ingest_records(
            [
                {"text": "Old doc OLD.", "source_id": "e:OLD"},
                {"text": "New doc NEW.", "source_id": "e:NEW"},
            ],
            namespace="test_prg3e",
        )
        old = await rag.db.fetch_one(
            "SELECT id FROM documents WHERE namespace=%s AND source_path=%s",
            ("test_prg3e", "e:OLD"),
        )
        new = await rag.db.fetch_one(
            "SELECT id FROM documents WHERE namespace=%s AND source_path=%s",
            ("test_prg3e", "e:NEW"),
        )
        # Retract NEW first → writes a retraction-audit document_versions row.
        await rag.retract(doc_id=new["id"], reason="temp retraction")
        retraction_row = await rag.db.fetch_one(
            "SELECT id FROM document_versions WHERE document_id=%s AND retracted=true",
            (new["id"],),
        )
        assert retraction_row is not None

        out = await rag.supersede(
            old_doc_id=old["id"], new_doc_id=new["id"], reason="NEW supersedes OLD"
        )
        assert out == {"updated": 1}

        # The supersedes pointer must NOT have been written onto the
        # retraction-audit row.
        contaminated = await rag.db.fetch_one(
            "SELECT supersedes_document_id FROM document_versions WHERE id=%s",
            (retraction_row["id"],),
        )
        assert contaminated["supersedes_document_id"] is None

        # It must live on a non-retracted row pointing new -> old.
        live = await rag.db.fetch_one(
            "SELECT supersedes_document_id, retracted FROM document_versions "
            "WHERE document_id=%s AND supersedes_document_id=%s",
            (new["id"], old["id"]),
        )
        assert live is not None
        assert live["retracted"] is False
    finally:
        await rag.delete("test_prg3e")
        await rag.close()


async def test_prg3_legacy_supersede_with_effective_to_uses_window():
    # DEC-10 precise boundary: legacy data with BOTH a supersedes pointer AND
    # an ingest-time effective_to is, under as_of, governed by the temporal
    # window (the one intended narrow refinement) — NOT the blunt
    # existence-hide. Current/non-as_of queries remain hidden.
    rag = await _connect(
        namespace="test_prg3f",
        evolution_tier="structural",
        supersession_behavior="hide",
    )
    try:
        await rag.delete("test_prg3f")
        old_eff = datetime(2020, 1, 1, tzinfo=timezone.utc)
        # OLD has an ingest-time effective_to that ends in 2023.
        old_eff_to = datetime(2023, 1, 1, tzinfo=timezone.utc)
        await rag.ingest_records(
            [
                {
                    "text": "Legacy windowed OLD doc.",
                    "source_id": "f:OLD",
                    "metadata": {"effective_from": old_eff, "effective_to": old_eff_to},
                },
                {
                    "text": "Legacy windowed NEW doc.",
                    "source_id": "f:NEW",
                    "metadata": {"effective_from": old_eff},
                },
            ],
            namespace="test_prg3f",
        )
        old = await rag.db.fetch_one(
            "SELECT id, effective_to FROM documents WHERE namespace=%s AND source_path=%s",
            ("test_prg3f", "f:OLD"),
        )
        new = await rag.db.fetch_one(
            "SELECT id FROM documents WHERE namespace=%s AND source_path=%s",
            ("test_prg3f", "f:NEW"),
        )
        assert old["effective_to"] is not None  # ingest-time window present
        # Legacy ingest-time supersedes pointer (NOT via supersede()).
        await rag.db.execute(
            "INSERT INTO document_versions "
            "(namespace, document_id, supersedes_document_id) "
            "VALUES (%s, %s, %s)",
            ("test_prg3f", new["id"], old["id"]),
        )

        # Current query (no as_of): existence-hide → OLD hidden (unchanged).
        cur = await rag.query("legacy windowed", mode="naive", namespace="test_prg3f")
        assert all(c.document_source != "f:OLD" for c in cur.chunks)

        # as_of WITHIN OLD's window (2020-01-01 .. 2023-01-01): DEC-10 lets
        # the temporal window govern (OLD has effective_to) → OLD surfaces.
        within = datetime(2022, 1, 1, tzinfo=timezone.utc)
        hist = await rag.query(
            "legacy windowed", mode="naive", namespace="test_prg3f", as_of=within
        )
        assert any(c.document_source == "f:OLD" for c in hist.chunks)
    finally:
        await rag.delete("test_prg3f")
        await rag.close()


async def test_prg4_chunk_id_stable_and_non_null():
    rag = await _connect(namespace="test_prg4")
    try:
        await rag.delete("test_prg4")
        await rag.ingest_records(
            [
                {
                    "text": "Incident postmortem for the cache stampede event.",
                    "source_id": "doc:1",
                }
            ],
            namespace="test_prg4",
        )
        r1 = await rag.query("cache stampede", mode="naive", namespace="test_prg4")
        r2 = await rag.query("cache stampede", mode="naive", namespace="test_prg4")
        assert r1.chunks and r2.chunks
        for c in r1.chunks + r2.chunks:
            assert c.chunk_id is not None
        ids1 = {c.content: c.chunk_id for c in r1.chunks}
        ids2 = {c.content: c.chunk_id for c in r2.chunks}
        for content, cid in ids1.items():
            assert ids2.get(content) == cid
    finally:
        await rag.delete("test_prg4")
        await rag.close()
