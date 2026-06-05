"""Integration tests for bounded-batch / streaming ingest_records (issue #46).

These prove the streaming API is correct and back-compatible: a list, a sync
generator, and an async iterator all ingest the same way, batch boundaries do
not change results, and cross-batch entity dedup still collapses (resolution is
DB-backed, so PostgreSQL is the dedup authority regardless of batching).
"""

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def _make_rag(namespace: str) -> GraphRAG:
    rag = GraphRAG(
        dsn=DSN,
        namespace=namespace,
        # No reachable LLM; records below set skip_llm=True so extraction is
        # deterministic and offline (known entities only).
        llm_base_url="http://localhost:99999/v1",
    )
    await rag.connect()
    return rag


def _rec(i: int, *, entity: str | None = None):
    rec = {
        "text": f"document number {i} with some body content",
        "source_id": f"stream:{i}",
        "skip_llm": True,
    }
    if entity:
        rec["entities"] = [{"name": entity, "entity_type": "org"}]
    return rec


async def _doc_count(rag, ns):
    row = await rag.db.fetch_one("SELECT count(*) AS n FROM documents WHERE namespace = %s", (ns,))
    return row["n"]


async def _entity_count(rag, ns, name=None):
    if name is None:
        row = await rag.db.fetch_one(
            "SELECT count(*) AS n FROM entities WHERE namespace = %s", (ns,)
        )
        return row["n"]
    row = await rag.db.fetch_one(
        "SELECT count(*) AS n FROM entities WHERE namespace = %s AND name = %s",
        (ns, name),
    )
    return row["n"]


async def test_list_and_generator_ingest_identically():
    """A list and a generator of the same records land the same documents."""
    ns_list, ns_gen = "stream_eq_list", "stream_eq_gen"
    rag = await _make_rag(ns_list)
    try:
        records = [_rec(i, entity=f"Org{i}") for i in range(6)]

        await rag.ingest_records(list(records), namespace=ns_list)
        await rag.ingest_records((r for r in records), namespace=ns_gen, batch_size=2)

        assert await _doc_count(rag, ns_list) == 6
        assert await _doc_count(rag, ns_gen) == 6
        assert await _entity_count(rag, ns_list) == await _entity_count(rag, ns_gen)
    finally:
        await rag.delete(ns_list)
        await rag.delete(ns_gen)
        await rag.close()


async def test_batch_size_does_not_change_results():
    """batch_size=1 and a large batch_size produce the same document count."""
    ns_small, ns_big = "stream_bs_small", "stream_bs_big"
    rag = await _make_rag(ns_small)
    try:
        records = [_rec(i) for i in range(5)]
        await rag.ingest_records(list(records), namespace=ns_small, batch_size=1)
        await rag.ingest_records(list(records), namespace=ns_big, batch_size=1000)
        assert await _doc_count(rag, ns_small) == 5
        assert await _doc_count(rag, ns_big) == 5
    finally:
        await rag.delete(ns_small)
        await rag.delete(ns_big)
        await rag.close()


async def test_cross_batch_entity_dedup():
    """The same entity seeded in two different batches collapses to one row."""
    ns = "stream_dedup"
    rag = await _make_rag(ns)
    try:
        # Docs 0 and 3 both seed "SharedCorp"; with batch_size=1 they land in
        # separate batches, so dedup must happen across the batch boundary.
        records = [
            _rec(0, entity="SharedCorp"),
            _rec(1, entity="Alpha"),
            _rec(2, entity="Beta"),
            _rec(3, entity="SharedCorp"),
        ]
        await rag.ingest_records(records, namespace=ns, batch_size=1)
        assert await _entity_count(rag, ns, "SharedCorp") == 1
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_async_iterator_ingests():
    """An async iterator source ingests correctly."""
    ns = "stream_async"
    rag = await _make_rag(ns)
    try:

        async def asource():
            for i in range(4):
                yield _rec(i)

        await rag.ingest_records(asource(), namespace=ns, batch_size=2)
        assert await _doc_count(rag, ns) == 4
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_invalid_batch_size_raises():
    rag = await _make_rag("stream_badbs")
    try:
        with pytest.raises(ValueError, match="batch_size"):
            await rag.ingest_records([_rec(0)], namespace="stream_badbs", batch_size=0)
    finally:
        await rag.delete("stream_badbs")
        await rag.close()


async def test_list_bad_record_fails_before_any_write():
    """Back-compat: a bad row in a list raises before ANY document is written."""
    ns = "stream_list_badrow"
    rag = await _make_rag(ns)
    try:
        records = [_rec(0), {"text": "no source id here"}, _rec(2)]
        with pytest.raises(ValueError, match="source_id"):
            await rag.ingest_records(records, namespace=ns)
        # Eager validation means nothing landed.
        assert await _doc_count(rag, ns) == 0
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_stream_bad_record_commits_prior_batches():
    """A stream validates per batch: prior good batches commit, bad batch raises."""
    ns = "stream_gen_badrow"
    rag = await _make_rag(ns)
    try:

        def gen():
            yield _rec(0)
            yield {"text": "no source id"}  # bad: missing source_id

        with pytest.raises(ValueError, match="source_id"):
            await rag.ingest_records(gen(), namespace=ns, batch_size=1)
        # First batch (good) committed before the bad one was pulled.
        assert await _doc_count(rag, ns) == 1
    finally:
        await rag.delete(ns)
        await rag.close()
