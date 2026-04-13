"""Test fixtures for pg-raggraph."""

import os

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.db import Database

TEST_DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def config():
    return PGRGConfig(dsn=TEST_DSN, namespace="test")


@pytest.fixture
async def db(config):
    """Provide a database connection, clean up test data after.

    Only deletes rows in test-prefixed namespaces to avoid wiping benchmark
    data or any user namespaces that happen to share the same DB.
    """
    database = Database(config)
    await database.connect()
    yield database
    # Cleanup ONLY test namespace data
    test_namespaces = (
        "test",
        "test_%",
        "e2e_%",
        "openai_test",
        "edge_test",
        "edge_fix",
        "speed_test%",
        "verbose_test",
        "debug%",
        "cli_test",
        "empty_ns",
    )
    try:
        for ns_pattern in test_namespaces:
            await database.execute("DELETE FROM entities WHERE namespace LIKE %s", (ns_pattern,))
            await database.execute(
                "DELETE FROM relationships WHERE namespace LIKE %s", (ns_pattern,)
            )
            await database.execute("DELETE FROM documents WHERE namespace LIKE %s", (ns_pattern,))
    except Exception:
        pass
    await database.close()


@pytest.fixture
def sample_md_path():
    return os.path.join(FIXTURES_DIR, "sample.md")


@pytest.fixture
def multi_doc_path():
    return os.path.join(FIXTURES_DIR, "multi_doc")
