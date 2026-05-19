"""Database layer for pg-raggraph — connection pool, schema management, bulk ops."""

from __future__ import annotations

import logging
from importlib.resources import files
from typing import Any

from pgvector.psycopg import register_vector_async
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from pg_raggraph.config import PGRGConfig

SCHEMA_VERSION = 1

logger = logging.getLogger("pg_raggraph.db")

# Whitelist of tables for safe SQL composition
_ALLOWED_TABLES = frozenset(
    {
        "documents",
        "chunks",
        "entities",
        "relationships",
        "entity_chunks",
        "relationship_chunks",
        "pgrg_llm_cache",
        "pgrg_meta",
    }
)


class Database:
    """Async PostgreSQL connection pool with auto-migration and bulk operations."""

    def __init__(self, config: PGRGConfig):
        self.config = config
        self._pool: AsyncConnectionPool | None = None

    async def connect(self) -> None:
        self._pool = AsyncConnectionPool(
            self.config.dsn,
            min_size=self.config.pool_min,
            max_size=self.config.pool_max,
            open=False,
            timeout=5,
            num_workers=1,
        )
        await self._pool.open()
        await self._pool.wait(timeout=5.0)
        async with self._pool.connection() as conn:
            await register_vector_async(conn)
            await self._ensure_schema(conn)
        logger.debug("Database connected and schema verified.")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def __aenter__(self) -> Database:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    @property
    def pool(self) -> AsyncConnectionPool:
        if self._pool is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._pool

    async def health_check(self) -> bool:
        """Check if the database connection is healthy."""
        try:
            async with self.pool.connection() as conn:
                await self._prepare_connection(conn)
                await conn.execute("SELECT 1")
            return True
        except Exception as e:
            logger.debug("health_check failed: %s", e)
            return False

    async def _prepare_connection(self, conn) -> None:
        await register_vector_async(conn)
        if self.config.statement_timeout_ms > 0:
            await conn.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                (str(self.config.statement_timeout_ms),),
            )

    async def _ensure_schema(self, conn) -> None:
        """Create or migrate schema to current version.

        Acquires a session-level advisory lock for the duration of bootstrap
        so multiple workers starting at once don't race to create the schema
        or apply the same migration twice. Lock key is an arbitrary constant
        specific to pg-raggraph.
        """
        # 0x70677267 = 'pgrg' — avoids collisions with other advisory locks.
        await conn.execute("SELECT pg_advisory_lock(%s)", (0x70677267,))
        try:
            result = await conn.execute(
                "SELECT EXISTS (SELECT FROM pg_tables WHERE tablename = 'pgrg_meta')"
            )
            row = await result.fetchone()
            exists = row[0] if row else False

            if not exists:
                sql_text = files("pg_raggraph.sql").joinpath("schema.sql").read_text()
                sql_text = sql_text.replace("{dim}", str(self.config.embedding_dim))
                await conn.execute(sql_text)
                await conn.execute(
                    "INSERT INTO pgrg_meta (key, value) VALUES ('schema_version', %s) "
                    "ON CONFLICT (key) DO UPDATE "
                    "SET value = EXCLUDED.value, updated_at = now()",
                    (str(SCHEMA_VERSION),),
                )
                await conn.execute(
                    "INSERT INTO pgrg_meta (key, value) VALUES ('embedding_dim', %s) "
                    "ON CONFLICT (key) DO UPDATE "
                    "SET value = EXCLUDED.value, updated_at = now()",
                    (str(self.config.embedding_dim),),
                )
                await conn.commit()
                logger.info(f"Schema v{SCHEMA_VERSION} created.")

            # Ensure the migration-tracking table exists on pre-0.3 installs
            # that were bootstrapped before the table was added to schema.sql.
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS pgrg_applied_migrations ("
                "    filename TEXT PRIMARY KEY,"
                "    version  INTEGER NOT NULL,"
                "    applied_at TIMESTAMPTZ DEFAULT now()"
                ")"
            )
            await conn.commit()

            # Always check for pending migrations, even when the base schema
            # is already current. New NNN_*.sql files ship in later releases.
            await self._apply_migrations(conn)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (0x70677267,))

    async def _apply_migrations(self, conn) -> None:
        """Apply numbered migration files from sql/migrations/.

        File naming: NNN_description.sql (e.g., 002_add_tags.sql). Applied in
        numeric order. Each file runs in its own transaction and is recorded in
        pgrg_applied_migrations by filename — not just version number — so two
        files with the same prefix both apply correctly and neither is silently
        skipped. Never edit a released migration file; add a new numbered one.
        """
        import re

        try:
            mig_dir = files("pg_raggraph.sql").joinpath("migrations")
            entries = [f.name for f in mig_dir.iterdir() if f.name.endswith(".sql")]
        except (FileNotFoundError, AttributeError):
            return

        # Which filenames have already been applied?
        applied_result = await conn.execute("SELECT filename FROM pgrg_applied_migrations")
        applied_files = {row[0] async for row in applied_result}

        pat = re.compile(r"^(\d+)_")
        pending = []
        for name in entries:
            if name in applied_files:
                continue
            m = pat.match(name)
            if not m:
                continue
            version = int(m.group(1))
            pending.append((version, name))
        pending.sort()

        for version, name in pending:
            logger.info(f"Applying migration {name}")
            sql_text = files("pg_raggraph.sql.migrations").joinpath(name).read_text()
            try:
                await conn.execute(sql_text)
                await conn.execute(
                    "INSERT INTO pgrg_applied_migrations (filename, version) VALUES (%s, %s) "
                    "ON CONFLICT (filename) DO NOTHING",
                    (name, version),
                )
                # Update the high-water mark for backwards compatibility.
                await conn.execute(
                    "UPDATE pgrg_meta SET value = GREATEST(value::int, %s)::text, "
                    "updated_at = now() WHERE key = 'schema_version'",
                    (str(version),),
                )
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                raise RuntimeError(f"Migration {name} failed: {e}") from e

    def transaction(self) -> Transaction:
        """Create a transaction scope — all operations share one connection.

        Usage:
            async with db.transaction() as tx:
                doc_id = await tx.insert_returning_id(...)
                chunk_id = await tx.insert_returning_id(...)
                await tx.execute(...)
            # Commits on exit, rolls back on exception

        Essential for ingestion where you need chunk_id from INSERT #1 to be
        visible to INSERT #2 on the SAME connection, without depending on
        another pool connection to see the uncommitted row.
        """
        return Transaction(self)

    async def execute(self, query_str: str, params: tuple | dict | None = None) -> Any:
        async with self.pool.connection() as conn:
            await self._prepare_connection(conn)
            result = await conn.execute(query_str, params)
            await conn.commit()
            return result

    async def fetch_all(self, query_str: str, params: tuple | dict | None = None) -> list[dict]:
        async with self.pool.connection() as conn:
            await self._prepare_connection(conn)
            cur = await conn.execute(query_str, params, prepare=False)
            if cur.description is None:
                return []
            columns = [desc.name for desc in cur.description]
            rows = await cur.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    async def fetch_one(self, query_str: str, params: tuple | dict | None = None) -> dict | None:
        rows = await self.fetch_all(query_str, params)
        return rows[0] if rows else None

    async def insert_returning_id(self, query_str: str, params: tuple | dict | None = None) -> int:
        async with self.pool.connection() as conn:
            await self._prepare_connection(conn)
            result = await conn.execute(query_str, params)
            row = await result.fetchone()
            await conn.commit()
            return row[0]

    async def bulk_insert(
        self,
        table: str,
        columns: list[str],
        rows: list[tuple],
    ) -> None:
        """Bulk insert using executemany. Table must be in whitelist."""
        if not rows:
            return
        if table not in _ALLOWED_TABLES:
            raise ValueError(f"Table '{table}' not in allowed list: {_ALLOWED_TABLES}")

        query_obj = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(sql.Identifier(c) for c in columns),
            sql.SQL(", ").join(sql.Placeholder() * len(columns)),
        )
        async with self.pool.connection() as conn:
            await self._prepare_connection(conn)
            cur = conn.cursor()
            await cur.executemany(query_obj, rows)
            await conn.commit()

    async def get_meta(self, key: str) -> str | None:
        row = await self.fetch_one("SELECT value FROM pgrg_meta WHERE key = %s", (key,))
        return row["value"] if row else None

    async def count(self, table: str, namespace: str | None = None) -> int:
        """Count rows, optionally filtered by namespace."""
        if table not in _ALLOWED_TABLES:
            raise ValueError(f"Table '{table}' not in allowed list: {_ALLOWED_TABLES}")

        if namespace:
            q = sql.SQL("SELECT count(*) as cnt FROM {} WHERE namespace = %s").format(
                sql.Identifier(table)
            )
            row = await self.fetch_one(q.as_string(None), (namespace,))
        else:
            q = sql.SQL("SELECT count(*) as cnt FROM {}").format(sql.Identifier(table))
            row = await self.fetch_one(q.as_string(None))
        return row["cnt"] if row else 0


class Transaction:
    """Single-connection transaction scope.

    Holds one connection from the pool for the duration of the context.
    All reads and writes use the same connection, so inserts are immediately
    visible to subsequent queries without waiting for pool commit propagation.
    """

    def __init__(self, db: Database):
        self._db = db
        self._conn = None
        self._cm = None

    async def __aenter__(self) -> Transaction:
        self._cm = self._db.pool.connection()
        self._conn = await self._cm.__aenter__()
        await self._db._prepare_connection(self._conn)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                await self._conn.commit()
            else:
                await self._conn.rollback()
        finally:
            await self._cm.__aexit__(exc_type, exc, tb)
            self._conn = None
            self._cm = None

    async def execute(self, query_str: str, params: tuple | dict | None = None) -> Any:
        return await self._conn.execute(query_str, params)

    async def fetch_one(self, query_str: str, params: tuple | dict | None = None) -> dict | None:
        cur = await self._conn.execute(query_str, params, prepare=False)
        if cur.description is None:
            return None
        row = await cur.fetchone()
        if row is None:
            return None
        columns = [desc.name for desc in cur.description]
        return dict(zip(columns, row))

    async def fetch_all(self, query_str: str, params: tuple | dict | None = None) -> list[dict]:
        cur = await self._conn.execute(query_str, params, prepare=False)
        if cur.description is None:
            return []
        columns = [desc.name for desc in cur.description]
        rows = await cur.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def insert_returning_id(self, query_str: str, params: tuple | dict | None = None) -> int:
        result = await self._conn.execute(query_str, params)
        row = await result.fetchone()
        return row[0]

    async def executemany(self, query_str: str, rows: list[tuple]) -> None:
        """Batched insert/update on the transaction's single connection.

        Unlike `Database.bulk_insert` (which opens its own pool connection
        and commits), this stays inside the active transaction and does
        not commit — `__aexit__` does that once for everything.
        """
        if not rows:
            return
        cur = self._conn.cursor()
        await cur.executemany(query_str, rows)
