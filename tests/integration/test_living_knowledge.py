from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


@dataclass(frozen=True)
class CadenceCase:
    cadence: str
    first_ts: datetime
    second_same_bucket_ts: datetime
    next_bucket_ts: datetime
    first_bucket: str
    next_bucket: str


CADENCE_CASES = [
    CadenceCase(
        cadence="hour",
        first_ts=datetime(2026, 5, 25, 9, 5, tzinfo=timezone.utc),
        second_same_bucket_ts=datetime(2026, 5, 25, 9, 45, tzinfo=timezone.utc),
        next_bucket_ts=datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc),
        first_bucket="2026-05-25T09",
        next_bucket="2026-05-25T10",
    ),
    CadenceCase(
        cadence="day",
        first_ts=datetime(2026, 5, 25, 9, tzinfo=timezone.utc),
        second_same_bucket_ts=datetime(2026, 5, 25, 15, tzinfo=timezone.utc),
        next_bucket_ts=datetime(2026, 5, 26, 8, tzinfo=timezone.utc),
        first_bucket="2026-05-25",
        next_bucket="2026-05-26",
    ),
    CadenceCase(
        cadence="week",
        first_ts=datetime(2026, 5, 25, 9, tzinfo=timezone.utc),
        second_same_bucket_ts=datetime(2026, 5, 31, 15, tzinfo=timezone.utc),
        next_bucket_ts=datetime(2026, 6, 1, 8, tzinfo=timezone.utc),
        first_bucket="2026-W22",
        next_bucket="2026-W23",
    ),
    CadenceCase(
        cadence="month",
        first_ts=datetime(2026, 5, 1, 9, tzinfo=timezone.utc),
        second_same_bucket_ts=datetime(2026, 5, 31, 15, tzinfo=timezone.utc),
        next_bucket_ts=datetime(2026, 6, 1, 8, tzinfo=timezone.utc),
        first_bucket="2026-05",
        next_bucket="2026-06",
    ),
]


async def _new_rag(ns: str, **kwargs) -> GraphRAG:
    rag = GraphRAG(
        dsn=DSN,
        namespace=ns,
        skip_extraction=True,
        llm_base_url="",
        **kwargs,
    )
    await rag.connect()
    await rag.delete(ns)
    await rag.db.execute("DELETE FROM living_audit_log WHERE namespace = %s", (ns,))
    return rag


async def _cleanup(rag: GraphRAG, ns: str) -> None:
    await rag.delete(ns)
    await rag.db.execute("DELETE FROM living_audit_log WHERE namespace = %s", (ns,))
    await rag.close()


def _record(
    *,
    source_id: str,
    text: str,
    ts: datetime,
    logical_id: str = "account:acme",
    key: str = "account_id",
    key_location: str = "metadata",
    pre_chunked: bool = False,
) -> dict:
    metadata = {"effective_from": ts}
    rec = {"source_id": source_id, "text": text, "metadata": metadata}
    if key_location == "metadata":
        metadata[key] = logical_id
    else:
        rec[key] = logical_id
    if pre_chunked:
        rec["pre_chunked"] = [
            {
                "content": text,
                "embedding": [0.01] * 384,
                "token_count": len(text.split()),
            }
        ]
    return rec


async def _docs(rag: GraphRAG, ns: str) -> list[dict]:
    return await rag.db.fetch_all(
        "SELECT d.id, d.source_path, d.effective_from, d.effective_to, "
        "       d.version_label, d.metadata, "
        "       string_agg(c.content, E'\\n' ORDER BY c.id) AS content "
        "FROM documents d JOIN chunks c ON c.document_id = d.id "
        "WHERE d.namespace = %s "
        "GROUP BY d.id, d.source_path, d.effective_from, d.effective_to, "
        "         d.version_label, d.metadata "
        "ORDER BY d.source_path",
        (ns,),
    )


@pytest.mark.parametrize("case", CADENCE_CASES, ids=[c.cadence for c in CADENCE_CASES])
async def test_living_knowledge_cadence_overwrite_and_roll_forward(case: CadenceCase):
    ns = f"test_living_{case.cadence}"
    rag = await _new_rag(
        ns,
        living_knowledge=True,
        living_key="account_id",
        living_cadence=case.cadence,
        living_audit_diffs=True,
    )
    try:
        await rag.ingest_records(
            [
                _record(
                    source_id="event:1",
                    text=f"Account Acme status is initial for {case.cadence}.",
                    ts=case.first_ts,
                )
            ],
            namespace=ns,
        )
        await rag.ingest_records(
            [
                _record(
                    source_id="event:2",
                    text=f"Account Acme status is same-bucket replacement for {case.cadence}.",
                    ts=case.second_same_bucket_ts,
                )
            ],
            namespace=ns,
        )

        docs = await _docs(rag, ns)
        assert len(docs) == 1
        assert (
            docs[0]["source_path"]
            == f"living://{ns}/account:acme/{case.cadence}/{case.first_bucket}"
        )
        assert docs[0]["metadata"]["living_logical_id"] == "account:acme"
        assert docs[0]["metadata"]["living_cadence"] == case.cadence
        assert docs[0]["metadata"]["living_bucket"] == case.first_bucket
        assert docs[0]["metadata"]["living_current"] is True
        assert docs[0]["version_label"] == f"{case.cadence}:{case.first_bucket}"
        assert "same-bucket replacement" in docs[0]["content"]
        assert "initial" not in docs[0]["content"]

        await rag.ingest_records(
            [
                _record(
                    source_id="event:3",
                    text=f"Account Acme status is next-bucket state for {case.cadence}.",
                    ts=case.next_bucket_ts,
                )
            ],
            namespace=ns,
        )

        docs = await _docs(rag, ns)
        assert len(docs) == 2
        by_bucket = {doc["metadata"]["living_bucket"]: doc for doc in docs}
        assert set(by_bucket) == {case.first_bucket, case.next_bucket}
        assert by_bucket[case.first_bucket]["metadata"]["living_current"] is False
        assert by_bucket[case.first_bucket]["effective_to"] is not None
        assert by_bucket[case.next_bucket]["metadata"]["living_current"] is True
        assert by_bucket[case.next_bucket]["effective_to"] is None

        audit = await rag.db.fetch_all(
            "SELECT logical_id, cadence, bucket, metadata FROM living_audit_log "
            "WHERE namespace = %s ORDER BY id",
            (ns,),
        )
        assert [(row["cadence"], row["bucket"], row["metadata"]["event"]) for row in audit] == [
            (case.cadence, case.first_bucket, "overwrite_bucket"),
            (case.cadence, case.next_bucket, "new_bucket_supersedes_prior"),
        ]
    finally:
        await _cleanup(rag, ns)


@pytest.mark.parametrize("audit_diffs", [False, True], ids=["audit_off", "audit_on"])
@pytest.mark.parametrize(
    "key_location,key",
    [("metadata", "account_id"), ("record", "logical_id")],
    ids=["metadata_key", "record_key"],
)
async def test_living_knowledge_key_location_and_audit_options(key_location, key, audit_diffs):
    ns = f"test_living_opts_{key_location}_{int(audit_diffs)}"
    rag = await _new_rag(
        ns,
        living_knowledge=True,
        living_key=key,
        living_cadence="day",
        living_audit_diffs=audit_diffs,
    )
    try:
        await rag.ingest_records(
            [
                _record(
                    source_id="event:1",
                    text="Account Acme first state.",
                    ts=datetime(2026, 5, 25, 9, tzinfo=timezone.utc),
                    key=key,
                    key_location=key_location,
                )
            ],
            namespace=ns,
        )
        await rag.ingest_records(
            [
                _record(
                    source_id="event:2",
                    text="Account Acme replacement state.",
                    ts=datetime(2026, 5, 25, 17, tzinfo=timezone.utc),
                    key=key,
                    key_location=key_location,
                )
            ],
            namespace=ns,
        )

        docs = await _docs(rag, ns)
        assert len(docs) == 1
        assert docs[0]["metadata"]["living_logical_id"] == "account:acme"
        assert docs[0]["metadata"]["logical_id"] == "account:acme"
        assert docs[0]["metadata"]["living_source_id"] == "event:2"

        audit = await rag.db.fetch_all(
            "SELECT id FROM living_audit_log WHERE namespace = %s",
            (ns,),
        )
        assert (len(audit) == 1) is audit_diffs
    finally:
        await _cleanup(rag, ns)


async def test_living_knowledge_per_call_overrides_constructor_defaults_and_supports_prechunked():
    ns = "test_living_per_call"
    rag = await _new_rag(
        ns,
        living_knowledge=False,
        living_key="wrong_key",
        living_cadence="month",
        living_audit_diffs=False,
    )
    try:
        await rag.ingest_records(
            [
                _record(
                    source_id="event:1",
                    text="Prechunked Acme state one.",
                    ts=datetime(2026, 5, 25, 9, 5, tzinfo=timezone.utc),
                    pre_chunked=True,
                )
            ],
            namespace=ns,
            living_knowledge=True,
            living_key="account_id",
            living_cadence="hour",
            living_audit_diffs=True,
        )
        await rag.ingest_records(
            [
                _record(
                    source_id="event:2",
                    text="Prechunked Acme state two.",
                    ts=datetime(2026, 5, 25, 9, 55, tzinfo=timezone.utc),
                    pre_chunked=True,
                )
            ],
            namespace=ns,
            living_knowledge=True,
            living_key="account_id",
            living_cadence="hour",
            living_audit_diffs=True,
        )

        docs = await _docs(rag, ns)
        assert len(docs) == 1
        assert docs[0]["metadata"]["living_cadence"] == "hour"
        assert docs[0]["metadata"]["living_bucket"] == "2026-05-25T09"
        assert "state two" in docs[0]["content"]

        audit = await rag.db.fetch_all(
            "SELECT metadata FROM living_audit_log WHERE namespace = %s",
            (ns,),
        )
        assert [row["metadata"]["event"] for row in audit] == ["overwrite_bucket"]
    finally:
        await _cleanup(rag, ns)


@pytest.mark.parametrize("living_current_only", [True, False], ids=["current_only", "include_old"])
async def test_living_knowledge_latest_retrieval_current_only_option(living_current_only):
    ns = f"test_living_retrieval_{int(living_current_only)}"
    rag = await _new_rag(
        ns,
        living_knowledge=True,
        living_current_only=living_current_only,
        living_key="account_id",
        living_cadence="day",
        evolution_tier="structural",
    )
    try:
        await rag.ingest_records(
            [
                _record(
                    source_id="event:1",
                    text="Acme old bucket uniqueoldtoken.",
                    ts=datetime(2026, 5, 25, 9, tzinfo=timezone.utc),
                ),
                _record(
                    source_id="event:2",
                    text="Acme current bucket uniquenewtoken.",
                    ts=datetime(2026, 5, 26, 9, tzinfo=timezone.utc),
                ),
            ],
            namespace=ns,
            max_concurrent_docs=1,
        )

        result = await rag.query(
            "Acme uniqueoldtoken",
            mode="naive",
            namespace=ns,
            profile="raw",
            as_of=None,
        )
        text = "\n".join(chunk.content for chunk in result.chunks)
        assert ("uniqueoldtoken" in text) is (not living_current_only)
        assert "uniquenewtoken" in text

        historical = await rag.query(
            "Acme uniqueoldtoken",
            mode="naive",
            namespace=ns,
            profile="raw",
            as_of=datetime(2026, 5, 25, 12, tzinfo=timezone.utc),
        )
        historical_text = "\n".join(chunk.content for chunk in historical.chunks)
        assert "uniqueoldtoken" in historical_text
        assert "uniquenewtoken" not in historical_text
    finally:
        await _cleanup(rag, ns)


async def test_living_knowledge_disabled_preserves_normal_source_id_replacement():
    ns = "test_living_disabled"
    rag = await _new_rag(ns, living_knowledge=False)
    try:
        await rag.ingest_records(
            [
                {
                    "source_id": "account:acme",
                    "text": "Normal state one.",
                    "metadata": {"account_id": "account:acme"},
                }
            ],
            namespace=ns,
        )
        await rag.ingest_records(
            [
                {
                    "source_id": "account:acme",
                    "text": "Normal state two.",
                    "metadata": {"account_id": "account:acme"},
                }
            ],
            namespace=ns,
        )

        docs = await _docs(rag, ns)
        assert len(docs) == 1
        assert docs[0]["source_path"] == "account:acme"
        assert "living_bucket" not in docs[0]["metadata"]
        assert "Normal state two" in docs[0]["content"]
    finally:
        await _cleanup(rag, ns)


async def test_living_knowledge_rejects_missing_logical_id_and_invalid_cadence():
    ns = "test_living_invalid"
    rag = await _new_rag(ns, living_knowledge=True, living_key="account_id")
    try:
        with pytest.raises(ValueError, match="missing living logical id key"):
            await rag.ingest_records(
                [{"source_id": "event:1", "text": "No logical id.", "metadata": {}}],
                namespace=ns,
            )
        with pytest.raises(ValueError, match="living_cadence"):
            await rag.ingest_records(
                [
                    {
                        "source_id": "event:2",
                        "text": "Bad cadence.",
                        "metadata": {"account_id": "account:acme"},
                    }
                ],
                namespace=ns,
                living_cadence="minute",
            )
    finally:
        await _cleanup(rag, ns)
