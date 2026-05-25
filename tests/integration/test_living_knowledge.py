from datetime import datetime, timezone

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def test_living_knowledge_overwrites_same_bucket_and_rolls_current_forward():
    ns = "test_living_knowledge"
    rag = GraphRAG(
        dsn=DSN,
        namespace=ns,
        skip_extraction=True,
        llm_base_url="",
        living_knowledge=True,
        living_key="account_id",
        living_cadence="day",
        living_audit_diffs=True,
    )
    await rag.connect()
    try:
        await rag.delete(ns)
        await rag.db.execute("DELETE FROM living_audit_log WHERE namespace = %s", (ns,))

        await rag.ingest_records(
            [
                {
                    "source_id": "event:1",
                    "text": "Account Acme status is pending.",
                    "metadata": {
                        "account_id": "account:acme",
                        "effective_from": datetime(2026, 5, 25, 9, tzinfo=timezone.utc),
                    },
                }
            ],
            namespace=ns,
        )
        await rag.ingest_records(
            [
                {
                    "source_id": "event:2",
                    "text": "Account Acme status is active.",
                    "metadata": {
                        "account_id": "account:acme",
                        "effective_from": datetime(2026, 5, 25, 15, tzinfo=timezone.utc),
                    },
                }
            ],
            namespace=ns,
        )

        rows = await rag.db.fetch_all(
            "SELECT d.id, d.source_path, d.content_hash, d.metadata, c.content "
            "FROM documents d JOIN chunks c ON c.document_id = d.id "
            "WHERE d.namespace = %s ORDER BY d.id, c.id",
            (ns,),
        )
        assert len({row["id"] for row in rows}) == 1
        assert rows[0]["source_path"] == "living://test_living_knowledge/account:acme/day/2026-05-25"
        assert rows[0]["metadata"]["living_logical_id"] == "account:acme"
        assert rows[0]["metadata"]["living_bucket"] == "2026-05-25"
        assert rows[0]["metadata"]["living_current"] is True
        assert "active" in rows[0]["content"]
        assert "pending" not in rows[0]["content"]

        await rag.ingest_records(
            [
                {
                    "source_id": "event:3",
                    "text": "Account Acme status is renewed.",
                    "metadata": {
                        "account_id": "account:acme",
                        "effective_from": datetime(2026, 5, 26, 8, tzinfo=timezone.utc),
                    },
                }
            ],
            namespace=ns,
        )

        docs = await rag.db.fetch_all(
            "SELECT id, source_path, effective_to, metadata "
            "FROM documents WHERE namespace = %s ORDER BY source_path",
            (ns,),
        )
        assert len(docs) == 2
        by_bucket = {doc["metadata"]["living_bucket"]: doc for doc in docs}
        assert by_bucket["2026-05-25"]["metadata"]["living_current"] is False
        assert by_bucket["2026-05-25"]["effective_to"] is not None
        assert by_bucket["2026-05-26"]["metadata"]["living_current"] is True

        audit = await rag.db.fetch_all(
            "SELECT logical_id, bucket, metadata FROM living_audit_log "
            "WHERE namespace = %s ORDER BY id",
            (ns,),
        )
        assert [row["metadata"]["event"] for row in audit] == [
            "overwrite_bucket",
            "new_bucket_supersedes_prior",
        ]
        assert {row["logical_id"] for row in audit} == {"account:acme"}
    finally:
        await rag.delete(ns)
        await rag.db.execute("DELETE FROM living_audit_log WHERE namespace = %s", (ns,))
        await rag.close()
