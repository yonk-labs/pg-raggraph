"""Integration tests for the full ingestion pipeline."""

import os
import tempfile

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


async def test_ingest_with_chunk_strategy_hierarchy_heading_path():
    """chunk_strategy=hierarchy produces heading-prefixed chunks through the full ingest pipeline."""
    rag = GraphRAG(
        dsn="postgresql://postgres:postgres@localhost:5434/pg_raggraph",
        namespace="test_hier_headings",
        llm_base_url="http://localhost:99999/v1",
        chunk_strategy="hierarchy",
    )
    await rag.connect()

    sample_path = os.path.join(FIXTURES_DIR, "sample.md")
    await rag.ingest([sample_path], namespace="test_hier_headings")

    # Fetch chunks that landed. Every hierarchy chunk either starts with the
    # H1 title prefix (pre-heading section) or a section-heading prefix.
    rows = await rag.db.fetch_all(
        "SELECT content FROM chunks c JOIN documents d ON c.document_id = d.id "
        "WHERE d.namespace = %s ORDER BY c.id",
        ("test_hier_headings",),
    )
    assert len(rows) >= 2
    contents = [r["content"] for r in rows]
    # sample.md starts with "# GraphRAG Overview" — hierarchy chunker strips
    # the leading hashes and uses the heading text as the prefix for each
    # chunk. The pre-first-heading section (H1 body) lands somewhere in the
    # chunk set with the H1 text as prefix.
    assert any(c.startswith("GraphRAG Overview\n\n") for c in contents), (
        f"Expected an H1-prefixed chunk; got: {[c[:60] for c in contents]}"
    )
    # At least one other chunk should start with an H2/H3 heading
    # (hashes stripped, body follows after a blank line).
    assert any(
        len(c) > 20 and "\n\n" in c[:80] and not c.startswith("#") and not c.startswith("GraphRAG Overview")
        for c in contents
    ), f"Expected heading-prefixed inner chunks; got: {[c[:60] for c in contents]}"

    await rag.delete("test_hier_headings")
    await rag.close()


async def test_ingest_with_chunk_strategy_hierarchy_title_fallback():
    """chunk_strategy=hierarchy falls back to filename-as-title prefix when no headings exist."""
    rag = GraphRAG(
        dsn="postgresql://postgres:postgres@localhost:5434/pg_raggraph",
        namespace="test_hier_fallback",
        llm_base_url="http://localhost:99999/v1",
        chunk_strategy="hierarchy",
    )
    await rag.connect()

    # Heading-less body; basename becomes the title prefix
    body = (
        "This project update summarizes Q2 deliverables across the platform team. "
        "The indexing pipeline shipped behind a feature flag. The retrieval layer "
        "moved to hybrid mode by default. Latency regressed 12ms in the smart path. "
    ) * 3
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="weekly-update-", delete=False, encoding="utf-8"
    ) as f:
        f.write(body)
        temp_path = f.name

    try:
        await rag.ingest([temp_path], namespace="test_hier_fallback")

        rows = await rag.db.fetch_all(
            "SELECT content FROM chunks c JOIN documents d ON c.document_id = d.id "
            "WHERE d.namespace = %s",
            ("test_hier_fallback",),
        )
        assert len(rows) == 1  # single heading-less chunk
        expected_title = os.path.splitext(os.path.basename(temp_path))[0]
        assert rows[0]["content"].startswith(f"{expected_title}\n\n"), (
            f"Expected title-prefix fallback; got: {rows[0]['content'][:80]!r}"
        )
    finally:
        os.unlink(temp_path)
        await rag.delete("test_hier_fallback")
        await rag.close()
