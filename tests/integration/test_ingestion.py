"""Integration tests for the full ingestion pipeline."""

import os

import pytest

from pg_raggraph import GraphRAG

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")

pytestmark = pytest.mark.integration


async def test_ingest_skips_without_llm():
    """Ingestion without LLM still stores documents and chunks."""
    # Use a bad LLM URL so extraction fails gracefully
    rag = GraphRAG(
        dsn="postgresql://postgres:postgres@localhost:5434/pg_raggraph",
        namespace="test_ingest",
        llm_base_url="http://localhost:99999/v1",  # No LLM running
    )
    await rag.connect()

    sample_path = os.path.join(FIXTURES_DIR, "sample.md")
    await rag.ingest([sample_path], namespace="test_ingest")

    status = await rag.status("test_ingest")
    assert status["documents"] >= 1
    # Chunks should be stored even if LLM extraction fails
    assert status["chunks"] >= 1

    # Clean up
    await rag.delete("test_ingest")
    await rag.close()


async def test_ingest_dedup():
    """Ingesting the same file twice should not duplicate documents."""
    rag = GraphRAG(
        dsn="postgresql://postgres:postgres@localhost:5434/pg_raggraph",
        namespace="test_dedup",
        llm_base_url="http://localhost:99999/v1",
    )
    await rag.connect()

    sample_path = os.path.join(FIXTURES_DIR, "sample.md")
    await rag.ingest([sample_path], namespace="test_dedup")
    s1 = await rag.status("test_dedup")

    # Ingest same file again
    await rag.ingest([sample_path], namespace="test_dedup")
    s2 = await rag.status("test_dedup")

    # Should not have duplicated
    assert s2["documents"] == s1["documents"]

    await rag.delete("test_dedup")
    await rag.close()


async def test_ingest_directory():
    """Ingesting a directory processes all supported files."""
    rag = GraphRAG(
        dsn="postgresql://postgres:postgres@localhost:5434/pg_raggraph",
        namespace="test_dir",
        llm_base_url="http://localhost:99999/v1",
    )
    await rag.connect()

    multi_doc_path = os.path.join(FIXTURES_DIR, "multi_doc")
    await rag.ingest([multi_doc_path], namespace="test_dir")

    status = await rag.status("test_dir")
    assert status["documents"] == 3  # 3 markdown files in multi_doc/

    await rag.delete("test_dir")
    await rag.close()
