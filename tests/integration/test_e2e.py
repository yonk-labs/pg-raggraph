"""Cumulative E2E test — grows with each sprint."""

import os

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.db import SCHEMA_VERSION

TEST_DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)

pytestmark = pytest.mark.integration


FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")


async def test_e2e_sprint0_schema():
    """Sprint 0: Connect, create schema, verify tables exist."""
    rag = GraphRAG(dsn=TEST_DSN, namespace="e2e_test")
    await rag.connect()

    status = await rag.status()
    assert status["schema_version"] >= SCHEMA_VERSION
    assert status["embedding_dim"] == 384
    assert status["documents"] == 0
    assert status["entities"] == 0

    await rag.close()


async def test_e2e_sprint1_ingest():
    """Sprint 1: Ingest documents, verify chunks stored."""
    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace="e2e_ingest",
        llm_base_url="http://localhost:99999/v1",  # No LLM — tests chunk storage
    )
    await rag.connect()

    # Ingest fixture docs
    await rag.ingest([os.path.join(FIXTURES_DIR, "multi_doc")], namespace="e2e_ingest")

    status = await rag.status("e2e_ingest")
    assert status["documents"] == 3
    assert status["chunks"] >= 3  # At least one chunk per doc

    # Verify dedup: re-ingest same docs
    await rag.ingest([os.path.join(FIXTURES_DIR, "multi_doc")], namespace="e2e_ingest")
    status2 = await rag.status("e2e_ingest")
    assert status2["documents"] == 3  # No duplicates

    # Clean up
    await rag.delete("e2e_ingest")
    await rag.close()


async def test_e2e_sprint2_query():
    """Sprint 2: Query with pre-seeded data returns results."""
    rag = GraphRAG(dsn=TEST_DSN, namespace="e2e_query")
    await rag.connect()

    # Seed some test data directly (no LLM needed)
    from pg_raggraph.embedding import get_embedding_provider

    embedder = get_embedding_provider(rag.config)
    ns = "e2e_query"

    doc_id = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (ns, "e2e_query_hash", "e2e_test.md"),
    )

    texts = ["PostgreSQL supports vector search via pgvector extension."]
    embs = await embedder.embed(texts)
    chunk_id = await rag.db.insert_returning_id(
        "INSERT INTO chunks (document_id, content, embedding, token_count) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (doc_id, texts[0], embs[0], 8),
    )

    ent_emb = (await embedder.embed(["PostgreSQL database"]))[0]
    ent_id = await rag.db.insert_returning_id(
        "INSERT INTO entities (namespace, name, entity_type, description, embedding) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (ns, "PostgreSQL", "technology", "A database", ent_emb),
    )
    await rag.db.execute(
        "INSERT INTO entity_chunks (entity_id, chunk_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (ent_id, chunk_id),
    )

    # Query
    result = await rag.query("PostgreSQL vector search", mode="naive", namespace=ns)
    assert len(result.chunks) > 0
    assert result.latency_ms < 2000
    assert "pgvector" in result.chunks[0].content or "PostgreSQL" in result.chunks[0].content

    # Local mode query
    result2 = await rag.query("PostgreSQL", mode="local", namespace=ns)
    assert len(result2.chunks) > 0

    await rag.ingest_records(
        [
            {
                "text": "End to end metadata round trip probe document.",
                "source_id": "e2e:rt",
                "metadata": {"e2e_ref": "rt-1"},
                "skip_llm": True,
            }
        ],
        namespace=ns,
    )
    rt = await rag.query("metadata round trip probe", mode="naive", namespace=ns)
    assert rt.chunks, "expected the probe doc to be retrievable"
    assert any(c.metadata == {"e2e_ref": "rt-1"} for c in rt.chunks), (
        "PRG-1: caller metadata must round-trip through query()"
    )

    # Clean up
    await rag.delete(ns)
    await rag.close()


def _lede_model_available() -> bool:
    try:
        import lede  # noqa: F401
        import lede_spacy  # noqa: F401
        import spacy

        spacy.load("en_core_web_sm")
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _lede_model_available(),
    reason="lede / lede-spacy / en_core_web_sm not available",
)
async def test_e2e_sprint3_lede_spacy_no_llm():
    """fact_extractor='lede_spacy' builds a graph and is queryable, no LLM."""
    ns = "e2e_lede"
    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace=ns,
        fact_extractor="lede_spacy",
        llm_base_url="",  # explicitly no LLM
    )
    await rag.connect()
    try:
        await rag.ingest_records(
            [
                {
                    "text": (
                        "NASA launched the Saturn V rocket from Kennedy "
                        "Space Center. Congress funded NASA that decade."
                    ),
                    "source_id": "e2e-lede:1",
                }
            ],
            namespace=ns,
        )
        status = await rag.status(ns)
        assert status["entities"] > 0, (
            "lede_spacy must build a graph without an LLM (no degrade path)"
        )
        result = await rag.query("NASA", mode="naive", namespace=ns)
        assert result.chunks, "ingested lede_spacy doc must be retrievable"
    finally:
        await rag.delete(ns)
        await rag.close()
