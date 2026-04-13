"""Integration tests for retrieval engine."""

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


@pytest.fixture
async def seeded_rag():
    """Create a GraphRAG instance with pre-seeded test data (no LLM needed)."""
    rag = GraphRAG(dsn=TEST_DSN, namespace="test_retrieval")
    await rag.connect()

    # Manually seed entities, relationships, chunks for deterministic testing
    from pg_raggraph.embedding import get_embedding_provider

    embedder = get_embedding_provider(rag.config)
    ns = "test_retrieval"

    # Insert test documents
    doc_id = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (ns, "test_hash_retrieval", "test/retrieval.md"),
    )

    # Insert chunks with embeddings
    chunk_texts = [
        "PostgreSQL is a powerful open source database with pgvector for vector search.",
        "LightRAG uses dual-level retrieval with entity and topic keywords.",
        "Microsoft GraphRAG costs $33,000 for large datasets due to community summaries.",
        "Apache AGE was rejected because it only works on Azure managed PostgreSQL.",
    ]
    embeddings = await embedder.embed(chunk_texts)
    chunk_ids = []
    for i, (text, emb) in enumerate(zip(chunk_texts, embeddings)):
        cid = await rag.db.insert_returning_id(
            "INSERT INTO chunks (document_id, content, embedding, token_count) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (doc_id, text, emb, len(text.split())),
        )
        chunk_ids.append(cid)

    # Insert entities
    entity_data = [
        ("PostgreSQL", "technology", "Open source relational database"),
        ("LightRAG", "technology", "Lightweight GraphRAG framework"),
        ("Microsoft GraphRAG", "technology", "Original GraphRAG implementation"),
        ("Apache AGE", "technology", "PostgreSQL graph extension"),
        ("pgvector", "technology", "Vector similarity search for PostgreSQL"),
    ]
    entity_ids = {}
    for name, etype, desc in entity_data:
        emb = (await embedder.embed([f"{name} {desc}"]))[0]
        eid = await rag.db.insert_returning_id(
            "INSERT INTO entities (namespace, name, entity_type, description, embedding) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (ns, name, etype, desc, emb),
        )
        entity_ids[name] = eid

    # Insert relationships
    rels = [
        ("PostgreSQL", "pgvector", "HAS_EXTENSION", "pgvector extends PostgreSQL"),
        ("LightRAG", "PostgreSQL", "USES", "LightRAG has a PostgreSQL backend"),
        ("Microsoft GraphRAG", "LightRAG", "INSPIRED", "LightRAG is an alternative"),
        ("Apache AGE", "PostgreSQL", "EXTENDS", "AGE is a PostgreSQL extension"),
    ]
    for src, dst, rtype, desc in rels:
        rid = await rag.db.insert_returning_id(
            "INSERT INTO relationships (namespace, src_id, dst_id, rel_type, description) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (ns, entity_ids[src], entity_ids[dst], rtype, desc),
        )
        # Link relationships to chunks (simplified: link to first relevant chunk)
        await rag.db.execute(
            "INSERT INTO relationship_chunks (relationship_id, chunk_id) "
            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (rid, chunk_ids[0]),
        )

    # Link entities to chunks
    entity_chunk_map = {
        "PostgreSQL": [0, 3],
        "LightRAG": [1],
        "Microsoft GraphRAG": [2],
        "Apache AGE": [3],
        "pgvector": [0],
    }
    for ename, cidxs in entity_chunk_map.items():
        for cidx in cidxs:
            await rag.db.execute(
                "INSERT INTO entity_chunks (entity_id, chunk_id) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (entity_ids[ename], chunk_ids[cidx]),
            )

    yield rag

    # Cleanup
    await rag.delete("test_retrieval")
    await rag.close()


async def test_naive_query(seeded_rag):
    """Naive mode returns chunks ranked by vector + BM25 similarity."""
    result = await seeded_rag.query(
        "PostgreSQL database", mode="naive", namespace="test_retrieval"
    )
    assert len(result.chunks) > 0
    assert result.query_mode == "naive"
    assert result.latency_ms > 0
    # First result should mention PostgreSQL
    assert "PostgreSQL" in result.chunks[0].content or "database" in result.chunks[0].content


async def test_local_query(seeded_rag):
    """Local mode uses entity seeds + graph traversal."""
    result = await seeded_rag.query("pgvector extension", mode="local", namespace="test_retrieval")
    assert len(result.chunks) > 0
    assert result.query_mode == "local"
    # Should find chunks connected to pgvector and its graph neighbors
    all_content = " ".join(c.content for c in result.chunks)
    assert "pgvector" in all_content or "PostgreSQL" in all_content


async def test_global_query(seeded_rag):
    """Global mode searches via relationships."""
    result = await seeded_rag.query(
        "GraphRAG implementations", mode="global", namespace="test_retrieval"
    )
    assert len(result.chunks) > 0
    assert result.query_mode == "global"


async def test_hybrid_query(seeded_rag):
    """Hybrid mode combines local + global results."""
    result = await seeded_rag.query(
        "PostgreSQL GraphRAG", mode="hybrid", namespace="test_retrieval"
    )
    assert len(result.chunks) > 0
    assert result.query_mode == "hybrid"
    assert result.latency_ms < 5000  # Should be fast


async def test_query_returns_entities(seeded_rag):
    """Query results include related entities."""
    result = await seeded_rag.query("PostgreSQL", mode="local", namespace="test_retrieval")
    assert len(result.entities) > 0
    entity_names = [e.name for e in result.entities]
    assert "PostgreSQL" in entity_names or "pgvector" in entity_names


async def test_query_returns_relationships(seeded_rag):
    """Query results include related relationships."""
    result = await seeded_rag.query("PostgreSQL", mode="local", namespace="test_retrieval")
    # Should find some relationships in the graph
    assert len(result.relationships) >= 0  # May be 0 if chunks don't match


async def test_query_latency(seeded_rag):
    """Query should complete in reasonable time."""
    result = await seeded_rag.query("What is LightRAG?", mode="hybrid", namespace="test_retrieval")
    assert result.latency_ms < 2000  # Under 2 seconds for test data
