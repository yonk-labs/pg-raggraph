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
