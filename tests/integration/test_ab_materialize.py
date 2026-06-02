"""Entity materialization from fact endpoints + cooccur nodes (real-verdict wiring).

graph_leg resolves question terms against pg-raggraph's ``entities`` table, but
the chunkshop bridge only imports chunks. Without materializing entities from
the imported fact subjects/objects + cooccur nodes, graph_leg resolves nothing
and the A/B verdict is rigged NAIVE. This locks the materializer.
"""

from __future__ import annotations

import json

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.ab_gate.ingest import materialize_entities_from_corpus

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
NS = "test_ab_materialize"


async def _seed_chunk(rag, *, content, metadata):
    """Insert one document + one chunk with the given metadata under NS."""
    dim = rag.config.embedding_dim
    doc_id = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (NS, f"hash-{content[:16]}-{json.dumps(metadata)[:16]}", f"{NS}:{content[:12]}"),
    )
    await rag.db.execute(
        "INSERT INTO chunks (document_id, content, embedded_content, embedding, metadata) "
        "VALUES (%s, %s, %s, %s, %s::jsonb)",
        (doc_id, content, content, [0.0] * dim, json.dumps(metadata)),
    )


async def test_materializes_fact_and_cooccur_surfaces():
    rag = GraphRAG(dsn=DSN, namespace=NS, llm_base_url="http://localhost:99999/v1")
    await rag.connect()
    try:
        await rag.delete(NS)
        # A fact chunk: subject="Bostock", object="Title VII"
        await _seed_chunk(
            rag,
            content="Bostock cites Title VII",
            metadata={
                "kind": "fact",
                "subject": "Bostock",
                "predicate": "cites",
                "object": "Title VII",
            },
        )
        # An episode chunk with a cooccur edge between "apple" and "iphone"
        await _seed_chunk(
            rag,
            content="Apple makes the iPhone.",
            metadata={
                "kind": "episode",
                "cooccur": [{"a": "apple", "b": "iphone", "weight": 0.8}],
            },
        )

        count = await materialize_entities_from_corpus(rag, NS)
        # 4 distinct surfaces: Bostock, Title VII, apple, iphone
        assert count == 4

        rows = await rag.db.fetch_all(
            "SELECT name FROM entities WHERE namespace = %s ORDER BY name", (NS,)
        )
        names = {r["name"] for r in rows}
        assert names == {"Bostock", "Title VII", "apple", "iphone"}
    finally:
        await rag.delete(NS)
        await rag.close()


async def test_materialize_is_idempotent():
    rag = GraphRAG(dsn=DSN, namespace=NS, llm_base_url="http://localhost:99999/v1")
    await rag.connect()
    try:
        await rag.delete(NS)
        await _seed_chunk(
            rag,
            content="X relates to Y",
            metadata={"kind": "fact", "subject": "X", "predicate": "rel", "object": "Y"},
        )
        first = await materialize_entities_from_corpus(rag, NS)
        assert first == 2
        # Second run inserts nothing new (ON CONFLICT DO NOTHING)
        second = await materialize_entities_from_corpus(rag, NS)
        assert second == 0
        total = await rag.db.fetch_one(
            "SELECT count(*) AS n FROM entities WHERE namespace = %s", (NS,)
        )
        assert total["n"] == 2
    finally:
        await rag.delete(NS)
        await rag.close()


async def test_materialized_entity_resolves_via_lookup():
    """End-to-end: a materialized surface is then findable by resolve_entity_lookup."""
    from pg_raggraph.resolution import resolve_entity_lookup

    rag = GraphRAG(dsn=DSN, namespace=NS, llm_base_url="http://localhost:99999/v1")
    await rag.connect()
    try:
        await rag.delete(NS)
        await _seed_chunk(
            rag,
            content="Neil Armstrong walked on the Moon",
            metadata={
                "kind": "fact",
                "subject": "Neil Armstrong",
                "predicate": "walked on",
                "object": "the Moon",
            },
        )
        await materialize_entities_from_corpus(rag, NS)
        hit = await resolve_entity_lookup(
            "Neil Armstrong", corpus_id=NS, db=rag.db, config=rag.config
        )
        assert hit is not None
        assert hit.canonical_name == "Neil Armstrong"
        assert hit.match_type == "exact"
    finally:
        await rag.delete(NS)
        await rag.close()
