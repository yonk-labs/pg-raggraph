"""Multi-version migration upgrade path: base schema + all migrations must
equal a fresh schema.sql bootstrap.

Catches the schema.sql-vs-migrations drift class (AAT F-23): schema.sql is
edited in place for new installs, while existing installs only ever receive
NNN_*.sql migrations. If a schema change lands in one but not the other,
upgraded databases silently diverge from fresh ones — sixteen alphas of
forward-only migrations with no multi-version-jump test meant the first
detection would be a user's broken upgrade.

Two throwaway databases on the same server:

- fresh:    normal ``Database.connect()`` bootstrap (current schema.sql,
            then all migrations — the path every new install takes).
- upgraded: the frozen pre-001 base schema (tests/fixtures/schema_base_v1.sql,
            the oldest supported starting point), then ``Database.connect()``,
            which routes through the production migration runner and applies
            001..head — the path every existing install takes.

Then table / column / index parity is asserted via information_schema and
pg_indexes. A non-empty diff means someone changed schema.sql without a
matching migration (or vice versa) — fix by adding the missing migration,
not by relaxing this test.
"""

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

_BASE_SCHEMA = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "fixtures", "schema_base_v1.sql"
)

_FRESH_DB = "pgrg_parity_fresh"
_UPGRADED_DB = "pgrg_parity_upgraded"


def _swap_dbname(dsn: str, dbname: str) -> str:
    info = psycopg.conninfo.conninfo_to_dict(dsn)
    info["dbname"] = dbname
    return psycopg.conninfo.make_conninfo(**info)


async def _recreate_db(name: str) -> str:
    """Drop + create a throwaway DB with the required extensions."""
    admin_dsn = _swap_dbname(TEST_DSN, "postgres")
    async with await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True) as admin:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{name}"')
    dsn = _swap_dbname(TEST_DSN, name)
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    return dsn


async def _drop_db(name: str) -> None:
    admin_dsn = _swap_dbname(TEST_DSN, "postgres")
    async with await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True) as admin:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


async def _snapshot(dsn: str):
    """(tables, columns, indexes) for the public schema.

    columns: {(table, column): (data_type, is_nullable, default)}.
    indexes: {index_name: normalized indexdef}.
    """
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1"
        )
        tables = {r[0] for r in await cur.fetchall()}
        cur = await conn.execute(
            "SELECT table_name, column_name, data_type, is_nullable, "
            "coalesce(column_default, '') "
            "FROM information_schema.columns WHERE table_schema='public'"
        )
        columns = {(r[0], r[1]): (r[2], r[3], r[4]) for r in await cur.fetchall()}
        cur = await conn.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public'"
        )
        indexes = {r[0]: " ".join(r[1].split()) for r in await cur.fetchall()}
    return tables, columns, indexes


async def test_migrations_from_base_match_fresh_bootstrap():
    fresh_dsn = await _recreate_db(_FRESH_DB)
    upgraded_dsn = await _recreate_db(_UPGRADED_DB)
    try:
        # Fresh install path: current schema.sql + migrations.
        db = Database(PGRGConfig(dsn=fresh_dsn, namespace="parity"))
        await db.connect()
        await db.close()

        # Upgrade path: frozen pre-001 base schema, then connect() — the
        # bootstrap sees pgrg_meta already exists, skips schema.sql, and the
        # production migration runner applies 001..head.
        cfg = PGRGConfig(dsn=upgraded_dsn, namespace="parity")
        base_sql = (
            open(_BASE_SCHEMA)
            .read()
            .replace("{dim}", str(cfg.embedding_dim))
            .replace("{hnsw_m}", str(cfg.hnsw_m))
            .replace("{hnsw_ef_construction}", str(cfg.hnsw_ef_construction))
        )
        async with await psycopg.AsyncConnection.connect(upgraded_dsn) as conn:
            await conn.execute(base_sql)
            await conn.commit()
        db = Database(cfg)
        await db.connect()
        try:
            row = await db.fetch_one("SELECT COUNT(*) AS n FROM pgrg_applied_migrations")
            # Guard against a silently short run: every shipped migration
            # file must have been applied on the upgrade path.
            from importlib.resources import files

            shipped = len(
                [
                    f.name
                    for f in files("pg_raggraph.sql").joinpath("migrations").iterdir()
                    if f.name.endswith(".sql")
                ]
            )
            assert row["n"] == shipped, (
                f"upgrade path applied {row['n']} migrations, {shipped} shipped"
            )
        finally:
            await db.close()

        f_tables, f_columns, f_indexes = await _snapshot(fresh_dsn)
        u_tables, u_columns, u_indexes = await _snapshot(upgraded_dsn)

        problems: list[str] = []
        if f_tables != u_tables:
            problems.append(
                f"tables only in fresh: {sorted(f_tables - u_tables)}; "
                f"only in upgraded: {sorted(u_tables - f_tables)}"
            )
        if f_columns != u_columns:
            only_f = sorted(set(f_columns) - set(u_columns))
            only_u = sorted(set(u_columns) - set(f_columns))
            changed = sorted(
                k for k in set(f_columns) & set(u_columns) if f_columns[k] != u_columns[k]
            )
            problems.append(
                f"columns only in fresh: {only_f}; only in upgraded: {only_u}; "
                f"type/nullability mismatch: {changed}"
            )
        if f_indexes != u_indexes:
            only_f = sorted(set(f_indexes) - set(u_indexes))
            only_u = sorted(set(u_indexes) - set(f_indexes))
            changed = sorted(
                k for k in set(f_indexes) & set(u_indexes) if f_indexes[k] != u_indexes[k]
            )
            problems.append(
                f"indexes only in fresh: {only_f}; only in upgraded: {only_u}; "
                f"definition mismatch: {changed}"
            )
        assert not problems, (
            "schema.sql and the migration chain have drifted apart — a fresh "
            "bootstrap and an upgraded install no longer produce the same "
            "schema:\n" + "\n".join(problems)
        )
    finally:
        await _drop_db(_FRESH_DB)
        await _drop_db(_UPGRADED_DB)
