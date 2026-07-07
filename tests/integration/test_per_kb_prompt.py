"""Integration tests for per-KB extraction prompt selection (#94).

A recording fake LLM captures which SYSTEM prompt each extraction call
received — the whole per-KB contract is "the right prompt reaches the LLM",
so that is what these tests pin, on both the sync ingest path and the
deferred-ingest → `pgrg extract` drain path.
"""

import json
import os
import uuid

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.backfill import claim_pending, extract_documents
from pg_raggraph.extraction import get_prompt

pytestmark = pytest.mark.integration

DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")


class RecordingLLM:
    """Fake LLM that records (system, user) per call and returns one entity."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def complete(self, messages: list[dict]) -> str:
        self.calls.append((messages[0]["content"], messages[1]["content"]))
        return json.dumps(
            {
                "entities": [
                    {"name": "Widget", "entity_type": "thing", "description": "a widget"}
                ],
                "relationships": [],
            }
        )

    async def complete_text(self, messages: list[dict], temperature: float = 0.2) -> str:
        return "ok"

    def system_prompt_for(self, marker: str) -> str:
        """The system prompt that accompanied the chunk containing ``marker``."""
        hits = [system for system, user in self.calls if marker in user]
        assert hits, f"no extraction call saw marker {marker!r}"
        return hits[0]


def _doc(marker: str, **extra) -> dict:
    # uuid marker keeps content unique per run so the prompt-aware LLM cache
    # (pgrg_llm_cache) never satisfies a call before it reaches the fake.
    return {"text": f"Ana lives in Lisbon and craves dim sum. ref={marker}", **extra}


async def _make_rag(namespace: str, **kw) -> GraphRAG:
    rag = GraphRAG(dsn=DSN, namespace=namespace, **kw)
    await rag.connect()
    rag._llm = RecordingLLM()
    return rag


async def test_sync_per_call_override_no_stamp():
    """extraction_prompt kwarg wins for the call; sync docs are NOT stamped
    (documents.metadata surfaces on query results — PRG-1 round-trip)."""
    ns = "t94_sync"
    rag = await _make_rag(ns)
    marker = uuid.uuid4().hex
    try:
        await rag.ingest_records(
            [_doc(marker, source_id=f"t94:sync:{marker}")],
            namespace=ns,
            extraction_prompt="prose",
        )
        assert rag._llm.system_prompt_for(marker) == get_prompt("prose")
        row = await rag.db.fetch_one("SELECT metadata FROM documents WHERE namespace = %s", (ns,))
        assert "extraction_prompt" not in (row["metadata"] or {})
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_sync_namespace_map_and_record_metadata():
    """Sync path consults the namespace map; record metadata stamp beats it."""
    ns = "t94_mapsync"
    rag = await _make_rag(ns, extraction_prompt_by_namespace={ns: "code"})
    m_map = uuid.uuid4().hex
    m_meta = uuid.uuid4().hex
    try:
        await rag.ingest_records(
            [
                _doc(m_map, source_id=f"t94:map:{m_map}"),
                _doc(
                    m_meta,
                    source_id=f"t94:meta:{m_meta}",
                    metadata={"extraction_prompt": "prose"},
                ),
            ],
            namespace=ns,
        )
        assert rag._llm.system_prompt_for(m_map) == get_prompt("code")
        assert rag._llm.system_prompt_for(m_meta) == get_prompt("prose")
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_deferred_drain_uses_stamped_prompt_per_namespace():
    """Two namespaces, two prompts, deferred → a plain-config drain worker
    extracts each doc with the prompt it was ingested under."""
    ns_prose = "t94_drain_prose"
    ns_dflt = "t94_drain_dflt"
    m_prose = uuid.uuid4().hex
    m_dflt = uuid.uuid4().hex

    ingest_a = await _make_rag(ns_prose)
    ingest_b = await _make_rag(ns_dflt)
    drain = await _make_rag("t94_drain_worker")  # global config: default prompt
    try:
        await ingest_a.ingest_records(
            [_doc(m_prose, source_id=f"t94:dp:{m_prose}")],
            namespace=ns_prose,
            defer_extraction=True,
            extraction_prompt="prose",
        )
        await ingest_b.ingest_records(
            [_doc(m_dflt, source_id=f"t94:dd:{m_dflt}")],
            namespace=ns_dflt,
            defer_extraction=True,
        )
        # No extraction happened at ingest time; deferred docs are stamped.
        assert ingest_a._llm.calls == [] and ingest_b._llm.calls == []
        row = await ingest_a.db.fetch_one(
            "SELECT metadata FROM documents WHERE namespace = %s", (ns_prose,)
        )
        assert row["metadata"]["extraction_prompt"] == "prose"

        for ns in (ns_prose, ns_dflt):
            ids = await claim_pending(drain.db, ns, 8)
            assert len(ids) == 1
            stats = await extract_documents(drain, ids, namespace=ns)
            assert stats.ready == 1 and stats.failed == 0, stats.errors

        assert drain._llm.system_prompt_for(m_prose) == get_prompt("prose")
        assert drain._llm.system_prompt_for(m_dflt) == get_prompt("default")
    finally:
        await drain.delete(ns_prose)
        await drain.delete(ns_dflt)
        await ingest_a.close()
        await ingest_b.close()
        await drain.close()


async def test_drain_falls_back_to_namespace_map_when_unstamped():
    """Pre-#94 docs carry no stamp — the drain worker's namespace map wins."""
    ns = "t94_drain_map"
    m = uuid.uuid4().hex
    ingest = await _make_rag(ns)
    drain = await _make_rag("t94_drain_map_worker", extraction_prompt_by_namespace={ns: "dev"})
    try:
        await ingest.ingest_records(
            [_doc(m, source_id=f"t94:dm:{m}")], namespace=ns, defer_extraction=True
        )
        # Simulate a pre-feature row: strip the ingest-time stamp.
        await ingest.db.execute(
            "UPDATE documents SET metadata = metadata - 'extraction_prompt' WHERE namespace = %s",
            (ns,),
        )
        ids = await claim_pending(drain.db, ns, 8)
        stats = await extract_documents(drain, ids, namespace=ns)
        assert stats.ready == 1 and stats.failed == 0, stats.errors
        assert drain._llm.system_prompt_for(m) == get_prompt("dev")
    finally:
        await drain.delete(ns)
        await ingest.close()
        await drain.close()


async def test_drain_marks_doc_failed_on_bogus_stamp():
    """An unknown stamped prompt fails loud: doc → 'failed' with the error."""
    ns = "t94_drain_bogus"
    m = uuid.uuid4().hex
    rag = await _make_rag(ns)
    try:
        await rag.ingest_records(
            [_doc(m, source_id=f"t94:db:{m}")], namespace=ns, defer_extraction=True
        )
        await rag.db.execute(
            "UPDATE documents SET metadata = jsonb_set(metadata, "
            "'{extraction_prompt}', '\"bogus\"') WHERE namespace = %s",
            (ns,),
        )
        ids = await claim_pending(rag.db, ns, 8)
        stats = await extract_documents(rag, ids, namespace=ns)
        assert stats.failed == 1
        row = await rag.db.fetch_one(
            "SELECT graph_status, graph_error FROM documents WHERE namespace = %s", (ns,)
        )
        assert row["graph_status"] == "failed"
        assert "bogus" in row["graph_error"]
    finally:
        await rag.delete(ns)
        await rag.close()
