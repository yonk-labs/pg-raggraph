"""Tests for configurable PostgreSQL statement timeout."""

import os

import psycopg
import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.db import Database

pytestmark = pytest.mark.integration

TEST_DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)


@pytest.mark.asyncio
async def test_statement_timeout_applied_to_acquired_connections():
    db = Database(
        PGRGConfig(
            dsn=TEST_DSN,
            statement_timeout_ms=50,
            pool_min=1,
            pool_max=1,
        )
    )
    await db.connect()
    try:
        with pytest.raises(psycopg.errors.QueryCanceled):
            await db.execute("SELECT pg_sleep(1)")
    finally:
        await db.close()
