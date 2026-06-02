"""Regression test for #45: schema bootstrap deadlock under concurrent connect.

On a fresh database, two workers racing through ``Database._ensure_schema`` used
to deadlock: a session-scoped ``pg_advisory_lock`` was held across the
``CREATE INDEX CONCURRENTLY`` in migration 004, which then waited on the losing
worker's open virtual transaction while that worker waited on the advisory lock.
"""

import asyncio
import os

import psycopg
import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.db import Database

TEST_DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)

FRESH_DB = "pgrg_bootstrap_race"


def _swap_dbname(dsn: str, dbname: str) -> str:
    info = psycopg.conninfo.conninfo_to_dict(dsn)
    info["dbname"] = dbname
    return psycopg.conninfo.make_conninfo(**info)


@pytest.fixture
async def fresh_db_dsn():
    """Create a throwaway database with the required extensions, drop it after."""
    admin_dsn = _swap_dbname(TEST_DSN, "postgres")
    async with await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True) as admin:
        await admin.execute(f'DROP DATABASE IF EXISTS "{FRESH_DB}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{FRESH_DB}"')

    fresh_dsn = _swap_dbname(TEST_DSN, FRESH_DB)
    async with await psycopg.AsyncConnection.connect(fresh_dsn, autocommit=True) as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    yield fresh_dsn

    async with await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True) as admin:
        await admin.execute(f'DROP DATABASE IF EXISTS "{FRESH_DB}" WITH (FORCE)')


@pytest.mark.asyncio
async def test_concurrent_connect_no_deadlock(fresh_db_dsn):
    """Two Database.connect() calls racing on a fresh DB must not deadlock."""
    db_a = Database(PGRGConfig(dsn=fresh_db_dsn, namespace="race_a"))
    db_b = Database(PGRGConfig(dsn=fresh_db_dsn, namespace="race_b"))

    try:
        # If the bootstrap deadlocks, Postgres aborts one side with
        # "deadlock detected", which surfaces here as a raised exception.
        await asyncio.gather(db_a.connect(), db_b.connect())

        # Schema must exist exactly once and be usable from both handles.
        for db in (db_a, db_b):
            row = await db.fetch_one("SELECT value FROM pgrg_meta WHERE key = 'schema_version'")
            assert row is not None
    finally:
        await db_a.close()
        await db_b.close()
