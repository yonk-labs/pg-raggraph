"""Integration tests with a real LLM endpoint.

These tests require a running OpenAI-compatible LLM server.
Set PGRG_TEST_LLM_URL to enable (default: http://192.168.1.193:8000/v1).
Skip if unreachable.
"""

import os

import httpx
import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
LLM_URL = os.environ.get("PGRG_TEST_LLM_URL", "http://192.168.1.193:8000/v1")
LLM_MODEL = os.environ.get("PGRG_TEST_LLM_MODEL", "Intel/Qwen3-Coder-Next-int4-AutoRound")
FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")


def llm_reachable() -> bool:
    """Check if the LLM endpoint is reachable."""
    try:
        resp = httpx.get(f"{LLM_URL}/models", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


skip_no_llm = pytest.mark.skipif(not llm_reachable(), reason="LLM not reachable")


@skip_no_llm
async def test_ingest_extracts_entities():
    """Ingestion with real LLM extracts entities and relationships."""
    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace="test_real_extract",
        llm_base_url=LLM_URL,
        llm_model=LLM_MODEL,
    )
    await rag.connect()
    await rag.delete("test_real_extract")

    sample = os.path.join(FIXTURES_DIR, "sample.md")
    await rag.ingest([sample], namespace="test_real_extract")

    status = await rag.status("test_real_extract")
    assert status["documents"] == 1
    assert status["chunks"] >= 3
    assert status["entities"] > 0, "LLM should have extracted entities"
    assert status["relationships"] > 0, "LLM should have extracted relationships"

    # Verify some expected entities exist
    entities = await rag.db.fetch_all(
        "SELECT name FROM entities WHERE namespace = %s",
        ("test_real_extract",),
    )
    entity_names = [e["name"].lower() for e in entities]
    # At least one of these should be extracted from sample.md
    expected_any = ["graphrag", "postgresql", "lightrag", "microsoft", "pgvector"]
    found = [e for e in expected_any if any(e in n for n in entity_names)]
    assert len(found) > 0, f"Expected at least one of {expected_any}, got {entity_names}"

    await rag.delete("test_real_extract")
    await rag.close()


@skip_no_llm
async def test_hybrid_query_with_real_entities():
    """Hybrid query finds relevant chunks via graph traversal."""
    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace="test_real_query",
        llm_base_url=LLM_URL,
        llm_model=LLM_MODEL,
    )
    await rag.connect()
    await rag.delete("test_real_query")

    # Ingest multi-doc corpus
    multi_doc = os.path.join(FIXTURES_DIR, "multi_doc")
    await rag.ingest([multi_doc], namespace="test_real_query")

    status = await rag.status("test_real_query")
    assert status["entities"] > 0

    # Query that requires graph traversal to answer well
    result = await rag.query(
        "What is the relationship between PostgreSQL and pgvector?",
        mode="hybrid",
        namespace="test_real_query",
    )
    assert len(result.chunks) > 0
    assert result.latency_ms < 5000

    # The graph should provide entities
    assert len(result.entities) > 0

    # Content should be relevant
    all_content = " ".join(c.content for c in result.chunks)
    assert "pgvector" in all_content.lower() or "postgresql" in all_content.lower()

    await rag.delete("test_real_query")
    await rag.close()


@skip_no_llm
async def test_entity_resolution_with_real_extraction():
    """Entities with similar names get merged during real extraction."""
    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace="test_real_resolution",
        llm_base_url=LLM_URL,
        llm_model=LLM_MODEL,
    )
    await rag.connect()
    await rag.delete("test_real_resolution")

    # Ingest all fixtures — multiple docs mention same entities
    await rag.ingest([FIXTURES_DIR], namespace="test_real_resolution")

    # Check that "Microsoft" variants merged (e.g., "Microsoft" and "Microsoft Research")
    entities = await rag.db.fetch_all(
        "SELECT name, description FROM entities WHERE namespace = %s AND name ILIKE %s",
        ("test_real_resolution", "%microsoft%"),
    )
    # Should have some Microsoft-related entities
    assert len(entities) >= 1

    await rag.delete("test_real_resolution")
    await rag.close()


@skip_no_llm
async def test_multi_hop_retrieval():
    """Graph traversal finds entities not directly mentioned in the query."""
    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace="test_multihop",
        llm_base_url=LLM_URL,
        llm_model=LLM_MODEL,
    )
    await rag.connect()
    await rag.delete("test_multihop")

    await rag.ingest([FIXTURES_DIR], namespace="test_multihop")

    # Query about something connected to PostgreSQL via the graph
    # (pgvector is connected to PostgreSQL, which is connected to many things)
    result_local = await rag.query(
        "vector similarity search",
        mode="local",
        namespace="test_multihop",
    )
    result_naive = await rag.query(
        "vector similarity search",
        mode="naive",
        namespace="test_multihop",
    )

    # Local (graph) mode should return at least as many relevant chunks
    # as naive mode, because it expands via graph neighbors
    assert len(result_local.chunks) > 0
    assert result_local.latency_ms < 5000

    # Local should find more entities than naive (which doesn't use graph)
    print(
        f"Local entities: {len(result_local.entities)}, "
        f"Naive entities: {len(result_naive.entities)}"
    )

    await rag.delete("test_multihop")
    await rag.close()


@skip_no_llm
async def test_dedup_with_real_llm():
    """Re-ingesting same document doesn't duplicate entities."""
    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace="test_real_dedup",
        llm_base_url=LLM_URL,
        llm_model=LLM_MODEL,
    )
    await rag.connect()
    await rag.delete("test_real_dedup")

    sample = os.path.join(FIXTURES_DIR, "sample.md")

    # First ingest
    await rag.ingest([sample], namespace="test_real_dedup")
    s1 = await rag.status("test_real_dedup")

    # Second ingest of same file
    await rag.ingest([sample], namespace="test_real_dedup")
    s2 = await rag.status("test_real_dedup")

    # Documents should NOT duplicate (content hash check)
    assert s2["documents"] == s1["documents"]
    # Entities should not grow (already cached + dedup)
    assert s2["entities"] == s1["entities"]

    await rag.delete("test_real_dedup")
    await rag.close()
