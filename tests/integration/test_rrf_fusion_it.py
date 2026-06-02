"""Integration tests for RRF fusion (issue #57). Requires PG on :5434."""

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


@pytest.fixture
async def seeded_rag():
    """GraphRAG with pre-seeded chunks/entities/relationships (no LLM needed).

    Self-contained copy adapted from tests/integration/test_retrieval.py so the
    RRF integration tests do not depend on a fixture defined in another module.
    """
    rag = GraphRAG(dsn=TEST_DSN, namespace="test_rrf_fusion")
    await rag.connect()

    from pg_raggraph.embedding import get_embedding_provider

    embedder = get_embedding_provider(rag.config)
    ns = "test_rrf_fusion"

    doc_id = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (ns, "test_hash_rrf", "test/rrf.md"),
    )

    chunk_texts = [
        "PostgreSQL is a powerful open source database with pgvector for vector search.",
        "LightRAG uses dual-level retrieval with entity and topic keywords.",
        "Microsoft GraphRAG costs $33,000 for large datasets due to community summaries.",
        "Apache AGE was rejected because it only works on Azure managed PostgreSQL.",
    ]
    embeddings = await embedder.embed(chunk_texts)
    chunk_ids = []
    for text, emb in zip(chunk_texts, embeddings):
        cid = await rag.db.insert_returning_id(
            "INSERT INTO chunks (document_id, content, embedding, token_count) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (doc_id, text, emb, len(text.split())),
        )
        chunk_ids.append(cid)

    entity_data = [
        ("PostgreSQL", "technology", "Open source relational database"),
        ("LightRAG", "technology", "Lightweight GraphRAG framework"),
        ("Microsoft GraphRAG", "technology", "Original GraphRAG implementation"),
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

    rels = [
        ("PostgreSQL", "pgvector", "HAS_EXTENSION", "pgvector extends PostgreSQL"),
        ("LightRAG", "PostgreSQL", "USES", "LightRAG has a PostgreSQL backend"),
        ("Microsoft GraphRAG", "LightRAG", "INSPIRED", "LightRAG is an alternative"),
    ]
    for src, dst, rtype, desc in rels:
        rid = await rag.db.insert_returning_id(
            "INSERT INTO relationships (namespace, src_id, dst_id, rel_type, description) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (ns, entity_ids[src], entity_ids[dst], rtype, desc),
        )
        await rag.db.execute(
            "INSERT INTO relationship_chunks (relationship_id, chunk_id) "
            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (rid, chunk_ids[0]),
        )

    entity_chunk_map = {
        "PostgreSQL": [0, 3],
        "LightRAG": [1],
        "Microsoft GraphRAG": [2],
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

    await rag.delete("test_rrf_fusion")
    await rag.close()


@pytest.fixture
async def seeded_rag_evolution():
    """GraphRAG with evolution_tier='structural' on a distinct namespace.

    Proves the RRF outer SELECT keeps d.effective_from / d.created_at in scope
    when the evolution re-join is active (SC-005).
    """
    rag = GraphRAG(dsn=TEST_DSN, namespace="test_rrf_evolution", evolution_tier="structural")
    await rag.connect()

    from pg_raggraph.embedding import get_embedding_provider

    embedder = get_embedding_provider(rag.config)
    ns = "test_rrf_evolution"

    doc_id = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (ns, "test_hash_rrf_evo", "test/rrf_evo.md"),
    )

    chunk_texts = [
        "On 2024-01-01 the policy rate was set to 5 percent, a dated fact.",
        "The migration completed and the dated fact about the rate changed.",
    ]
    embeddings = await embedder.embed(chunk_texts)
    for text, emb in zip(chunk_texts, embeddings):
        await rag.db.insert_returning_id(
            "INSERT INTO chunks (document_id, content, embedding, token_count) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (doc_id, text, emb, len(text.split())),
        )

    yield rag

    await rag.delete("test_rrf_evolution")
    await rag.close()


async def test_naive_rrf_runs_via_public_api(seeded_rag):
    """SC-002/SC-003: naive RRF runs end-to-end through the public override."""
    rag = seeded_rag
    linear = await rag.query("PostgreSQL vector search", mode="naive", fusion="linear")
    rrf = await rag.query("PostgreSQL vector search", mode="naive", fusion="rrf")
    assert linear.chunks
    assert rrf.chunks


async def test_hybrid_rrf_runs_via_public_api(seeded_rag):
    """SC-004: hybrid RRF path executes and returns ranked chunks."""
    res = await seeded_rag.query("GraphRAG frameworks", mode="hybrid", fusion="rrf")
    assert res.chunks
    assert all(c.score is not None for c in res.chunks)


async def test_ask_forwards_fusion(seeded_rag):
    """ask() forwards the fusion override down to retrieval without error."""
    res = await seeded_rag.ask("PostgreSQL vector search", mode="naive", fusion="rrf")
    assert res is not None


async def test_naive_rrf_with_evolution_on(seeded_rag_evolution):
    """SC-005: naive RRF executes under evolution_tier='structural'.

    Executing without a SQL error proves the d.effective_from / d.created_at
    columns from the evolution re-join resolve in the RRF outer SELECT.
    """
    res = await seeded_rag_evolution.query("a dated fact", mode="naive", fusion="rrf")
    assert res is not None  # executing without SQL error is the assertion
