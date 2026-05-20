"""Database layer for pg-raggraph — connection pool, schema management, bulk ops."""

from __future__ import annotations

import contextvars
import logging
import re
from contextlib import contextmanager
from importlib.resources import files
from typing import Any

from pgvector.psycopg import register_vector_async
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from pg_raggraph.config import PGRGConfig

SCHEMA_VERSION = 1

logger = logging.getLogger("pg_raggraph.db")

# Postgres identifier shape — letters/digits/underscores, must start with
# letter/underscore. We cap at 50 chars (well under Postgres's 63-byte limit)
# to leave room for the `idx_chunks_metadata_` prefix in the generated index
# name. Belt-and-suspenders alongside psycopg's sql.Identifier escaping —
# the regex also blocks valid-but-suspicious shapes (Unicode identifiers,
# quoted identifiers) so the failure mode is "reject at config init" rather
# than "create a strangely-named index in production."
_METADATA_INDEX_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,49}$")


def _validate_metadata_index_key(key: str) -> str:
    """Reject metadata_indexes keys that aren't safe Postgres identifiers.

    Raises ValueError with a precise message; called eagerly during
    ``connect()`` so the failure surfaces at startup, not on the first
    query. Even though we use ``psycopg.sql.Identifier`` for DDL
    composition (which handles escaping correctly), narrowing the
    allowed shape here keeps generated index names predictable and
    rejects accidental injections / typos.
    """
    if not isinstance(key, str):
        raise ValueError(
            f"metadata_indexes entries must be strings, got {type(key).__name__}: {key!r}"
        )
    if not _METADATA_INDEX_KEY_RE.match(key):
        raise ValueError(
            f"metadata_indexes key {key!r} is not a valid identifier. "
            f"Must match {_METADATA_INDEX_KEY_RE.pattern} (letters, digits, "
            "underscores; start with letter or underscore; max 50 chars)."
        )
    return key


def _metadata_index_name(key: str) -> str:
    """Build the canonical index name for a metadata key.

    The name is stable across runs (idempotent CREATE INDEX IF NOT EXISTS)
    and discoverable in psql via the ``idx_chunks_metadata_`` prefix.
    """
    return f"idx_chunks_metadata_{key}"


# Whitelist of SQL types allowed for generated-column scaffolding.
# Limited to the common typed-metadata cases — numeric (int/bigint/numeric),
# temporal (timestamptz), boolean, and text. Adding more types (e.g. uuid,
# json) is straightforward; the constraint is intentional so users can't
# trigger surprising casts (date vs timestamptz, real vs double precision).
# Maps from the user-facing name to the canonical SQL keyword we emit.
_ALLOWED_METADATA_GENERATED_TYPES = {
    "text": "text",
    "int": "integer",
    "integer": "integer",
    "bigint": "bigint",
    "numeric": "numeric",
    "timestamptz": "timestamptz",
    "boolean": "boolean",
    "bool": "boolean",
}


def _validate_metadata_generated_type(type_name: str) -> str:
    """Whitelist-check + canonicalize a generated-column type name.

    Same boundary-rejection pattern as ``_validate_metadata_index_key`` —
    typos / unsupported types fail at connect() time, not at SQL parse.
    """
    if not isinstance(type_name, str):
        raise ValueError(
            f"metadata_generated_columns types must be strings, "
            f"got {type(type_name).__name__}: {type_name!r}"
        )
    canon = _ALLOWED_METADATA_GENERATED_TYPES.get(type_name.lower())
    if canon is None:
        raise ValueError(
            f"metadata_generated_columns type {type_name!r} is not supported. "
            f"Allowed: {sorted(set(_ALLOWED_METADATA_GENERATED_TYPES))}"
        )
    return canon


def _metadata_generated_column_name(key: str) -> str:
    """Canonical generated-column name for a metadata key.

    Lands under ``meta_<key>`` on ``chunks``. Distinct namespace from the
    btree ``idx_chunks_metadata_`` prefix so a key can have BOTH a
    generated column AND a btree index without name collision.
    """
    return f"meta_{key}"


def _metadata_generated_index_name(key: str) -> str:
    """Btree index name on the generated column."""
    return f"idx_chunks_meta_{key}"


# Whitelist of tables for safe SQL composition
_ALLOWED_TABLES = frozenset(
    {
        "documents",
        "chunks",
        "entities",
        "relationships",
        "entity_chunks",
        "relationship_chunks",
        "embedding_cache",
        "pgrg_llm_cache",
        "pgrg_meta",
    }
)


class Database:
    """Async PostgreSQL connection pool with auto-migration and bulk operations."""

    def __init__(self, config: PGRGConfig):
        self.config = config
        self._pool: AsyncConnectionPool | None = None
        self._read_pool: AsyncConnectionPool | None = None
        self._tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            "pg_raggraph_tenant",
            default=None,
        )
        self._read_only: contextvars.ContextVar[bool] = contextvars.ContextVar(
            "pg_raggraph_read_only",
            default=False,
        )

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
            if await self._should_skip_schema_bootstrap(conn):
                await self._verify_schema_ready(conn)
            else:
                await self._ensure_schema(conn)
            # Apply user-configured metadata indexes after the base schema
            # is guaranteed present. Skips silently when the list is empty
            # (the default), so callers who don't opt in see no schema
            # change. CREATE INDEX IF NOT EXISTS makes this idempotent
            # across reconnects.
            if self.config.metadata_indexes:
                await self._apply_metadata_indexes(conn)
            if self.config.metadata_indexes_gin:
                await self._apply_metadata_gin_index(conn)
            if self.config.metadata_generated_columns:
                await self._apply_metadata_generated_columns(conn)
        if self.config.read_dsn:
            self._read_pool = AsyncConnectionPool(
                self.config.read_dsn,
                min_size=self.config.pool_min,
                max_size=self.config.pool_max,
                open=False,
                timeout=5,
                num_workers=1,
            )
            await self._read_pool.open()
            await self._read_pool.wait(timeout=5.0)
            async with self._read_pool.connection() as conn:
                await register_vector_async(conn)
                await self._verify_schema_ready(conn)
        logger.debug("Database connected and schema verified.")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
        if self._read_pool:
            await self._read_pool.close()
            self._read_pool = None

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

    @property
    def read_pool(self) -> AsyncConnectionPool:
        if self._read_pool is None:
            return self.pool
        return self._read_pool

    def _pool_for_read(self) -> AsyncConnectionPool:
        if self._read_only.get() and self._read_pool is not None:
            return self._read_pool
        return self.pool

    def set_tenant(self, namespace: str | None) -> contextvars.Token:
        return self._tenant.set(namespace)

    def reset_tenant(self, token: contextvars.Token) -> None:
        self._tenant.reset(token)

    @contextmanager
    def tenant(self, namespace: str | None):
        token = self._tenant.set(namespace)
        try:
            yield
        finally:
            self._tenant.reset(token)

    @contextmanager
    def readonly(self):
        token = self._read_only.set(True)
        try:
            yield
        finally:
            self._read_only.reset(token)

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
        if self.config.hnsw_ef_search > 0:
            await conn.execute(
                "SELECT set_config('hnsw.ef_search', %s, false)",
                (str(self.config.hnsw_ef_search),),
            )
        if self.config.rls_enabled:
            tenant = self._tenant.get() or self.config.namespace
            current = await conn.execute("SELECT current_user")
            row = await current.fetchone()
            if row and row[0] != "pgrg_app":
                await conn.execute("SET LOCAL ROLE pgrg_app")
            await conn.execute("SELECT set_config('app.tenant', %s, true)", (tenant,))

    async def _should_skip_schema_bootstrap(self, conn) -> bool:
        if not self.config.rls_enabled:
            return False
        result = await conn.execute("SELECT current_user = 'pgrg_app'")
        row = await result.fetchone()
        return bool(row and row[0])

    async def _verify_schema_ready(self, conn) -> None:
        result = await conn.execute(
            "SELECT EXISTS (SELECT FROM pg_tables WHERE tablename = 'pgrg_meta') "
            "AND EXISTS (SELECT FROM pg_tables WHERE tablename = 'pgrg_applied_migrations')"
        )
        row = await result.fetchone()
        if not row or not row[0]:
            raise RuntimeError(
                "Database schema is not initialized. Run `pgrg migrate` with a "
                "migration-capable role before using rls_enabled=True with an app role."
            )

    def _render_sql_template(self, sql_text: str) -> str:
        return (
            sql_text.replace("{dim}", str(self.config.embedding_dim))
            .replace("{hnsw_m}", str(self.config.hnsw_m))
            .replace("{hnsw_ef_construction}", str(self.config.hnsw_ef_construction))
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
                sql_text = self._render_sql_template(sql_text)
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

    async def _apply_metadata_indexes(self, conn) -> None:
        """Create btree indexes on ``chunks.metadata->>'<key>'`` per config.

        For each key in ``config.metadata_indexes``: ``CREATE INDEX IF NOT
        EXISTS idx_chunks_metadata_<key> ON chunks ((metadata->>'<key>'))``.
        Followed by ``ANALYZE chunks`` so the planner picks up the new
        index immediately.

        Uses non-CONCURRENTLY because:

        - We're inside ``connect()`` which holds the bootstrap advisory
          lock; CONCURRENTLY would fail in that context (it can't run in a
          transaction).
        - For fresh deployments the chunks table is empty or tiny — the
          ACCESS EXCLUSIVE lock is invisible.
        - Production retrofitters should create the index manually with
          CONCURRENTLY first (see docs/cookbook/metadata-indexes.md), then
          add the key to ``metadata_indexes`` so this loop's
          ``IF NOT EXISTS`` is a no-op.

        Keys are validated against ``_METADATA_INDEX_KEY_RE`` first so a
        bad config raises a clear error at startup, not a SQL syntax
        error mid-CREATE.
        """
        for raw_key in self.config.metadata_indexes:
            key = _validate_metadata_index_key(raw_key)
            index_name = _metadata_index_name(key)
            # sql.Identifier handles escaping for both the index name and
            # the JSONB key string. We don't need to interpolate the key
            # into a string literal directly — psycopg renders it safely.
            stmt = sql.SQL(
                "CREATE INDEX IF NOT EXISTS {idx} ON chunks ((metadata->>{key}))"
            ).format(
                idx=sql.Identifier(index_name),
                key=sql.Literal(key),
            )
            try:
                await conn.execute(stmt)
                logger.info("Ensured metadata index %s on chunks.metadata->>%r", index_name, key)
            except Exception as e:
                # Don't crash connect() over an index failure — the rest of
                # pg-raggraph still works without the optimization. But log
                # loudly so the operator sees it.
                logger.warning(
                    "Failed to create metadata index %s on chunks.metadata->>%r: %s. "
                    "Retrieval still works; pre_filter on this key will not benefit "
                    "from indexing until the cause is resolved.",
                    index_name,
                    key,
                    e,
                )
        # Refresh planner stats so the new indexes are picked up without
        # waiting for autovacuum.
        try:
            await conn.execute("ANALYZE chunks")
        except Exception as e:  # noqa: BLE001 — diagnostic only
            logger.debug("ANALYZE chunks after metadata-index apply failed: %s", e)

    async def _apply_metadata_gin_index(self, conn) -> None:
        """Create a GIN index on the whole ``chunks.metadata`` JSONB column.

        Powers ad-hoc containment / key-existence / multi-key predicates
        that the per-key btree indexes from ``metadata_indexes`` can't
        serve (e.g., ``metadata @> '{"tag":"x"}'``, ``metadata ? 'k'``).

        Uses the default ``jsonb_ops`` operator class — supports all the
        common JSONB query operators. The alternative ``jsonb_path_ops``
        is smaller but only supports ``@>``; we err on the side of
        flexibility since the bool flag is one knob.

        Same non-CONCURRENTLY caveat as ``_apply_metadata_indexes``. For
        production retrofit, run ``CREATE INDEX CONCURRENTLY`` manually
        before flipping ``metadata_indexes_gin=True``.
        """
        # Fixed name — there's only one GIN index per chunks table by design.
        index_name = "idx_chunks_metadata_gin"
        stmt = sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON chunks USING GIN (metadata)").format(
            idx=sql.Identifier(index_name)
        )
        try:
            await conn.execute(stmt)
            logger.info("Ensured GIN index %s on chunks.metadata", index_name)
            await conn.execute("ANALYZE chunks")
        except Exception as e:
            # Same don't-crash-connect pattern as btree path — the rest of
            # pg-raggraph works without the GIN; operator sees the warning.
            logger.warning(
                "Failed to create GIN index %s on chunks.metadata: %s. "
                "Retrieval still works; ad-hoc JSONB containment / key-exists "
                "predicates will not benefit from indexing until resolved.",
                index_name,
                e,
            )

    async def _apply_metadata_generated_columns(self, conn) -> None:
        """Add STORED generated columns + btree indexes from JSONB metadata.

        For each ``{key: type}`` in ``config.metadata_generated_columns``:

        1. ``ALTER TABLE chunks ADD COLUMN IF NOT EXISTS meta_<key> <type>
           GENERATED ALWAYS AS ((metadata->>'<key>')::<type>) STORED``
        2. ``CREATE INDEX IF NOT EXISTS idx_chunks_meta_<key>
           ON chunks(meta_<key>)``
        3. ``ANALYZE chunks``

        The STORED generated column means every existing AND future row
        gets the typed value automatically — no application-side backfill
        code. The cast is evaluated on insert/update; a row whose
        ``metadata->>'<key>'`` doesn't parse as the chosen type fails the
        write. Loud failure beats silent corruption.

        **Idempotent on key + type match.** If the column already exists
        with the configured type, ``ADD COLUMN IF NOT EXISTS`` is a no-op.
        If it exists with a DIFFERENT type, the no-op leaves the old type —
        operator must manually ``ALTER TABLE chunks DROP COLUMN meta_<key>``
        before the new type takes effect (documented in the cookbook).

        Same non-CONCURRENTLY caveat as the btree path — ``ADD COLUMN``
        STORED rewrites every row on Postgres < 12 and locks the table on
        all versions. For production retrofit, use the manual recipe
        in ``docs/cookbook/metadata-indexes.md``.
        """
        for raw_key, raw_type in self.config.metadata_generated_columns.items():
            key = _validate_metadata_index_key(raw_key)
            sql_type = _validate_metadata_generated_type(raw_type)
            col = _metadata_generated_column_name(key)
            idx = _metadata_generated_index_name(key)
            # We can't parameterize column names or types via bind params;
            # both have been validated against whitelists. sql.Identifier
            # escapes the identifier; sql.SQL embeds the type keyword
            # (one of a fixed safe-string set), sql.Literal handles the
            # JSONB key string.
            add_col = sql.SQL(
                "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS {col} {sqltype} "
                "GENERATED ALWAYS AS ((metadata->>{key})::{sqltype}) STORED"
            ).format(
                col=sql.Identifier(col),
                sqltype=sql.SQL(sql_type),
                key=sql.Literal(key),
            )
            create_idx = sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON chunks({col})").format(
                idx=sql.Identifier(idx),
                col=sql.Identifier(col),
            )
            try:
                await conn.execute(add_col)
                await conn.execute(create_idx)
                logger.info(
                    "Ensured generated column %s (%s) + index %s",
                    col,
                    sql_type,
                    idx,
                )
            except Exception as e:
                # Same don't-crash pattern as other helpers. Most common
                # cause: column already exists with a different type, or
                # the cast rejected an existing row's metadata value.
                logger.warning(
                    "Failed to create generated column %s (%s) for key %r: %s. "
                    "Retrieval still works on metadata->>%r; range queries "
                    "fall back to lexical comparison until resolved.",
                    col,
                    sql_type,
                    key,
                    e,
                    key,
                )
        try:
            await conn.execute("ANALYZE chunks")
        except Exception as e:  # noqa: BLE001 — diagnostic only
            logger.debug("ANALYZE chunks after metadata-generated-columns apply failed: %s", e)

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
            sql_text = self._render_sql_template(sql_text)
            try:
                if "CONCURRENTLY" in sql_text.upper():
                    await conn.commit()
                    original_autocommit = conn.autocommit
                    await conn.set_autocommit(True)
                    try:
                        executable_sql = "\n".join(
                            line
                            for line in sql_text.splitlines()
                            if not line.lstrip().startswith("--")
                        )
                        for statement in executable_sql.split(";"):
                            statement = statement.strip()
                            if statement:
                                await conn.execute(statement)
                    finally:
                        await conn.set_autocommit(original_autocommit)
                else:
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
        async with self._pool_for_read().connection() as conn:
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
