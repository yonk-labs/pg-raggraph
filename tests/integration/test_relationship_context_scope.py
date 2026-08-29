"""Regression tests for #113: relationship answer-context must be scoped to
the retrieved documents' provenance, not fetched namespace-wide.

A generic entity shared across documents ("reversal") must not bridge one
document's query to another document's relationships — that injected other
cases' actor/date facts into the synthesis prompt (cross-document answer
bleed, reported downstream as EnterpriseDB/bento#970).
"""

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.retrieval import RELATIONSHIPS_FOR_ENTITIES

pytestmark = pytest.mark.integration

TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
NS = "test_rel_scope"


@pytest.fixture
async def seeded(request):
    """Two documents sharing one generic entity, one relationship each, plus
    one unprovenanced (manually seeded) relationship.

    doc A: "Aisha Nexbel" --[PROCESSED]--> "reversal"   (provenance: chunk A)
    doc B: "Maria Haldun" --[PROCESSED]--> "reversal"   (provenance: chunk B)
    global: "reversal" --[GOVERNED_BY]--> "dispute policy"  (no provenance)
    """
    rag = GraphRAG(dsn=TEST_DSN, namespace=NS)
    await rag.connect()

    async def _doc_with_chunk(source: str, content: str) -> int:
        doc_id = await rag.db.insert_returning_id(
            "INSERT INTO documents (namespace, content_hash, source_path) "
            "VALUES (%s, %s, %s) RETURNING id",
            (NS, f"hash_{source}", source),
        )
        return await rag.db.insert_returning_id(
            "INSERT INTO chunks (document_id, content, token_count) "
            "VALUES (%s, %s, %s) RETURNING id",
            (doc_id, content, len(content.split())),
        )

    chunk_a = await _doc_with_chunk(
        "case-a.md", "Aisha Nexbel processed the reversal on 2026-11-03."
    )
    chunk_b = await _doc_with_chunk(
        "case-b.md", "Maria Haldun processed the reversal on 2026-04-10."
    )

    async def _entity(name: str, etype: str) -> int:
        return await rag.db.insert_returning_id(
            "INSERT INTO entities (namespace, name, entity_type) VALUES (%s, %s, %s) RETURNING id",
            (NS, name, etype),
        )

    aisha = await _entity("Aisha Nexbel", "person")
    maria = await _entity("Maria Haldun", "person")
    reversal = await _entity("reversal", "event")  # shared across both docs
    policy = await _entity("dispute policy", "document")

    for eid, cid in [
        (aisha, chunk_a),
        (reversal, chunk_a),
        (maria, chunk_b),
        (reversal, chunk_b),
    ]:
        await rag.db.execute(
            "INSERT INTO entity_chunks (entity_id, chunk_id) VALUES (%s, %s)",
            (eid, cid),
        )

    async def _rel(src: int, dst: int, rel_type: str, prov_chunk: int | None) -> int:
        rid = await rag.db.insert_returning_id(
            "INSERT INTO relationships (namespace, src_id, dst_id, rel_type) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (NS, src, dst, rel_type),
        )
        if prov_chunk is not None:
            await rag.db.execute(
                "INSERT INTO relationship_chunks (relationship_id, chunk_id) VALUES (%s, %s)",
                (rid, prov_chunk),
            )
        return rid

    await _rel(aisha, reversal, "PROCESSED", chunk_a)
    await _rel(maria, reversal, "PROCESSED", chunk_b)
    await _rel(reversal, policy, "GOVERNED_BY", None)  # manually seeded, no provenance

    yield rag, chunk_a, chunk_b

    await rag.delete(NS)
    await rag.close()


def _pairs(rows) -> set[tuple[str, str, str]]:
    return {(r["source"], r["rel_type"], r["target"]) for r in rows}


async def test_other_documents_relationships_excluded(seeded):
    """Retrieving only doc A's chunk must not surface doc B's relationship,
    even though the shared "reversal" entity is 1-hop from both."""
    rag, chunk_a, _ = seeded
    rows = await rag.db.fetch_all(RELATIONSHIPS_FOR_ENTITIES, {"chunk_ids": [chunk_a]})
    pairs = _pairs(rows)
    assert ("Aisha Nexbel", "PROCESSED", "reversal") in pairs
    assert ("Maria Haldun", "PROCESSED", "reversal") not in pairs, (
        "cross-document bleed: doc B's edge reached doc A's answer context (#113)"
    )


async def test_unprovenanced_relationships_kept(seeded):
    """Manually seeded relationships (no relationship_chunks rows) stay visible."""
    rag, chunk_a, _ = seeded
    rows = await rag.db.fetch_all(RELATIONSHIPS_FOR_ENTITIES, {"chunk_ids": [chunk_a]})
    assert ("reversal", "GOVERNED_BY", "dispute policy") in _pairs(rows)


async def test_multi_document_retrieval_keeps_both(seeded):
    """When retrieval legitimately spans both docs, both edges are in scope."""
    rag, chunk_a, chunk_b = seeded
    rows = await rag.db.fetch_all(RELATIONSHIPS_FOR_ENTITIES, {"chunk_ids": [chunk_a, chunk_b]})
    pairs = _pairs(rows)
    assert ("Aisha Nexbel", "PROCESSED", "reversal") in pairs
    assert ("Maria Haldun", "PROCESSED", "reversal") in pairs
