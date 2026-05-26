"""Integration test: chunkshop top_terms are folded into chunks.search_vector.

The trigger pgrg_update_search_vector() should index the 'term' values from
chunks.metadata->'top_terms' (a JSON array of {term, score, kind} objects)
with weight 'B', so BM25 queries can surface a chunk by its salient terms
even when those terms do not appear in the chunk body.
"""

import json
import os
import uuid

import pytest

from pg_raggraph import GraphRAG

DSN = os.environ.get("PGRG_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="requires PGRG_TEST_DSN")
NS = "test_search_vector_top_terms"


@pytest.mark.asyncio
async def test_top_terms_folded_into_search_vector():
    """A term present only in top_terms (not in the chunk body) must be queryable via FTS."""
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)
    db = rag._db
    try:
        # Insert a parent document (namespace + content_hash are the only NOT NULLs).
        chash = uuid.uuid4().hex
        doc = await db.fetch_one(
            "INSERT INTO documents (namespace, content_hash) "
            "VALUES (%s, %s) RETURNING id",
            (NS, chash),
        )

        # Chunk body: 'alpha beta' — no trace of 'zonkterm'.
        # metadata.top_terms: adds 'zonkterm' as a salient term.
        meta = json.dumps(
            {"top_terms": [{"term": "zonkterm", "score": 1.0, "kind": "keyword"}]}
        )
        chunk = await db.fetch_one(
            "INSERT INTO chunks (document_id, content, embedded_content, metadata) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (doc["id"], "alpha beta", "alpha beta", meta),
        )

        row = await db.fetch_one(
            "SELECT "
            "  (search_vector @@ to_tsquery('english', 'zonkterm')) AS by_term, "
            "  (search_vector @@ to_tsquery('english', 'alpha'))    AS by_body "
            "FROM chunks WHERE id = %s",
            (chunk["id"],),
        )
        assert row["by_body"] is True, "Body terms must still be indexed"
        assert row["by_term"] is True, (
            "top_terms 'zonkterm' must be folded into search_vector — "
            "migration 011 redefines pgrg_update_search_vector() to include top_terms"
        )
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_no_top_terms_still_works():
    """Chunks without top_terms in metadata must continue to index normally."""
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)
    db = rag._db
    try:
        chash = uuid.uuid4().hex
        doc = await db.fetch_one(
            "INSERT INTO documents (namespace, content_hash) "
            "VALUES (%s, %s) RETURNING id",
            (NS, chash),
        )

        # No metadata at all — empty JSONB default.
        chunk = await db.fetch_one(
            "INSERT INTO chunks (document_id, content, embedded_content) "
            "VALUES (%s, %s, %s) RETURNING id",
            (doc["id"], "plain content", "plain content"),
        )

        row = await db.fetch_one(
            "SELECT (search_vector @@ to_tsquery('english', 'plain')) AS by_body "
            "FROM chunks WHERE id = %s",
            (chunk["id"],),
        )
        assert row["by_body"] is True, "Chunks without top_terms must still index body content"
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_multiple_top_terms():
    """All terms in top_terms array must be indexed, not just the first."""
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)
    db = rag._db
    try:
        chash = uuid.uuid4().hex
        doc = await db.fetch_one(
            "INSERT INTO documents (namespace, content_hash) "
            "VALUES (%s, %s) RETURNING id",
            (NS, chash),
        )

        meta = json.dumps(
            {
                "top_terms": [
                    {"term": "quantumflux", "score": 0.9, "kind": "keyword"},
                    {"term": "hypervector", "score": 0.7, "kind": "entity"},
                    {"term": "splorganism", "score": 0.5, "kind": "concept"},
                ]
            }
        )
        chunk = await db.fetch_one(
            "INSERT INTO chunks (document_id, content, embedded_content, metadata) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (doc["id"], "ordinary text", "ordinary text", meta),
        )

        for term in ("quantumflux", "hypervector", "splorganism"):
            row = await db.fetch_one(
                "SELECT (search_vector @@ to_tsquery('english', %s)) AS hit "
                "FROM chunks WHERE id = %s",
                (term, chunk["id"]),
            )
            assert row["hit"] is True, f"top_term '{term}' must be indexed in search_vector"
    finally:
        await rag.delete(NS)
        await rag.close()
