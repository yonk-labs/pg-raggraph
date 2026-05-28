"""Integration tests for CLI commands."""

import os
import re

import pytest
from click.testing import CliRunner

from pg_raggraph.cli import main

pytestmark = pytest.mark.integration

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")
TEST_DB = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


@pytest.fixture
def runner():
    return CliRunner()


def test_init(runner):
    """pgrg init creates schema and reports version."""
    result = runner.invoke(main, ["--db", TEST_DB, "init"])
    assert result.exit_code == 0
    assert re.search(r"Schema v\d+ ready", result.output)


def test_status_empty(runner):
    """pgrg status shows zero counts for fresh namespace."""
    result = runner.invoke(main, ["--db", TEST_DB, "status"])
    assert result.exit_code == 0
    assert "Documents:" in result.output
    assert "Entities:" in result.output


def test_ingest_and_status(runner):
    """pgrg ingest processes files, status reflects counts."""
    sample = os.path.join(FIXTURES_DIR, "sample.md")
    result = runner.invoke(main, ["--db", TEST_DB, "ingest", sample, "-n", "cli_test"])
    assert result.exit_code == 0

    # Check status
    result = runner.invoke(main, ["--db", TEST_DB, "status"])
    assert result.exit_code == 0

    # Clean up
    result = runner.invoke(main, ["--db", TEST_DB, "delete", "-n", "cli_test", "--yes"])
    assert result.exit_code == 0
    assert "deleted" in result.output


def test_query_without_data(runner):
    """pgrg query on empty namespace returns gracefully."""
    result = runner.invoke(main, ["--db", TEST_DB, "query", "test question", "-n", "empty_ns"])
    # Should not crash even with no data
    assert result.exit_code == 0
    assert "0 chunks retrieved" in result.output


def test_extract_empty_queue_exits_zero(runner):
    """pgrg extract with no pending docs drains immediately and exits 0."""
    result = runner.invoke(
        main, ["--db", TEST_DB, "extract", "-n", "cli_test_no_pending", "--batch-size", "2"]
    )
    assert result.exit_code == 0, f"stderr: {result.output}"
    assert "Done:" in result.output


def test_extract_drains_pending_once(runner):
    """pgrg extract --once processes one batch of pending docs."""
    import asyncio

    from pg_raggraph import GraphRAG

    async def _seed():
        rag = GraphRAG(dsn=TEST_DB, namespace="cli_test_extract")
        await rag.connect()
        try:
            await rag.ingest_records(
                [
                    {"text": "alpha doc for cli extract test", "source_id": "cli:ext:1"},
                    {"text": "beta doc for cli extract test", "source_id": "cli:ext:2"},
                ],
                namespace="cli_test_extract",
                defer_extraction=True,
            )
        finally:
            await rag.close()

    asyncio.run(_seed())

    try:
        result = runner.invoke(
            main,
            [
                "--db",
                TEST_DB,
                "extract",
                "-n",
                "cli_test_extract",
                "--batch-size",
                "8",
                "--once",
            ],
        )
        assert result.exit_code == 0, f"stderr: {result.output}"
        # 2 docs claimed in one iter (batch=8 >= 2), then --once exits.
        assert "[iter 1]" in result.output
        assert "claimed=2" in result.output

        # Verify both rows are now 'ready'. No LLM/lede configured here → the
        # graph stays empty, but the status flag still flips since the
        # backfill primitive treats "no extractor" as a terminal state.
        async def _check():
            rag = GraphRAG(dsn=TEST_DB, namespace="cli_test_extract")
            await rag.connect()
            try:
                rows = await rag.db.fetch_all(
                    "SELECT graph_status FROM documents WHERE namespace = %s",
                    ("cli_test_extract",),
                )
                return [r["graph_status"] for r in rows]
            finally:
                await rag.close()

        statuses = asyncio.run(_check())
        assert statuses == ["ready", "ready"]
    finally:
        runner.invoke(main, ["--db", TEST_DB, "delete", "-n", "cli_test_extract", "--yes"])
