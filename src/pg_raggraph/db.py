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


_METADATA_INDEXED_TABLES = ("chunks", "documents")


def _validate_metadata_table(table: str) -> str:
    """Whitelist the table name for metadata-index DDL composition.

    Belt-and-suspenders alongside ``sql.Identifier`` escaping — only
    ``chunks`` and ``documents`` are valid targets for metadata-index
    auto-create. Other tables (``entities``, ``relationships``, etc.)
    reject at config init.
    """
    if table not in _METADATA_INDEXED_TABLES:
        raise ValueError(
            f"metadata-index table must be one of {_METADATA_INDEXED_TABLES}, got {table!r}"
        )
    return table


def _metadata_index_name(key: str, table: str = "chunks") -> str:
    """Build the canonical btree-on-JSONB index name.

    Returns ``idx_chunks_metadata_<key>`` or ``idx_documents_metadata_<key>``.
    Stable across runs (idempotent CREATE INDEX IF NOT EXISTS) and
    discoverable in psql via the ``idx_<table>_metadata_`` prefix.

    ``table`` defaults to ``"chunks"`` for back-compat with pre-Option-A
    callers that didn't pass a table arg.
    """
    return f"idx_{table}_metadata_{key}"


def _metadata_gin_index_name(table: str = "chunks") -> str:
    """Fixed name for the GIN index on the whole JSONB column — one per table."""
    return f"idx_{table}_metadata_gin"


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


def _validate_metadata_generated_path(path: Any) -> tuple[str, ...]:
    """Validate a JSON text path used by a generated metadata column.

    ``metadata_generated_columns`` accepts either the legacy shorthand
    ``{"priority": "int"}`` or an explicit nested path spec:
    ``{"term": {"type": "text", "path": ["lede_report", "attributes", "term", "value"]}}``.
    Path segments are emitted with ``sql.Literal`` later, so this is mainly a
    config-quality check: reject empty / non-string / NUL-containing segments
    before DDL assembly.
    """
    if isinstance(path, str):
        parts = tuple(part for part in path.split(".") if part)
    elif isinstance(path, list | tuple):
        parts = tuple(path)
    else:
        raise ValueError(
            "metadata_generated_columns path must be a dotted string or list of strings"
        )
    if not parts:
        raise ValueError("metadata_generated_columns path must not be empty")
    for part in parts:
        if not isinstance(part, str) or not part:
            raise ValueError("metadata_generated_columns path entries must be non-empty strings")
        if "\x00" in part:
            raise ValueError("metadata_generated_columns path entries must not contain NUL bytes")
    return parts


def _normalize_metadata_generated_spec(
    raw_key: str, raw_spec: Any
) -> tuple[str, str, tuple[str, ...]]:
    """Return ``(column_key, sql_type, json_path)`` for generated-column config."""
    key = _validate_metadata_index_key(raw_key)
    if isinstance(raw_spec, str):
        return key, _validate_metadata_generated_type(raw_spec), (key,)
    if not isinstance(raw_spec, dict):
        raise ValueError(
            "metadata_generated_columns values must be strings or "
            f"mappings, got {type(raw_spec).__name__}: {raw_spec!r}"
        )
    raw_type = raw_spec.get("type") or raw_spec.get("sql_type")
    if raw_type is None:
        raise ValueError(f"metadata_generated_columns spec for {raw_key!r} must include type")
    raw_path = raw_spec.get("path", key)
    return (
        key,
        _validate_metadata_generated_type(raw_type),
        _validate_metadata_generated_path(raw_path),
    )


def _metadata_generated_json_text_expr(path: tuple[str, ...]) -> sql.Composed:
    """Build ``metadata#>>ARRAY['a','b']`` for a generated-column expression."""
    return sql.SQL("(metadata#>>ARRAY[{path}])").format(
        path=sql.SQL(",").join(sql.Literal(part) for part in path)
    )


def _metadata_generated_column_name(key: str) -> str:
    """Canonical generated-column name for a metadata key.

    Lands under ``meta_<key>``. Table-independent — the column lives on
    a specific table, so no cross-table name collision is possible.
    Index names (below) DO encode the table.
    """
    return f"meta_{key}"


def _metadata_generated_index_name(key: str, table: str = "chunks") -> str:
    """Btree index name on the generated column.

    Returns ``idx_chunks_meta_<key>`` or ``idx_documents_meta_<key>``.
    """
    return f"idx_{table}_meta_{key}"


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
            # is guaranteed present. Skips silently when the list/dict is
            # empty (the default), so callers who don't opt in see no
            # schema change. CREATE INDEX IF NOT EXISTS makes this
            # idempotent across reconnects.
            #
            # Two parallel sets of knobs — chunks.metadata (default for the
            # mechanical chunker-supplied fields like source_path) and
            # documents.metadata (caller-supplied per-record fields like
            # salesperson / product / date from a structured-source ingest).
            # See docs/cookbook/metadata-indexes.md → "Why two tables matter".
            if self.config.metadata_indexes:
                await self._apply_metadata_indexes(conn, table="chunks")
            if self.config.document_metadata_indexes:
                await self._apply_metadata_indexes(conn, table="documents")
            if self.config.metadata_indexes_gin:
                await self._apply_metadata_gin_index(conn, table="chunks")
            if self.config.document_metadata_indexes_gin:
                await self._apply_metadata_gin_index(conn, table="documents")
            if self.config.metadata_generated_columns:
                await self._apply_metadata_generated_columns(conn, table="chunks")
            if self.config.document_metadata_generated_columns:
                await self._apply_metadata_generated_columns(conn, table="documents")
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

    async def _apply_metadata_indexes(self, conn, *, table: str = "chunks") -> None:
        """Create btree indexes on ``<table>.metadata->>'<key>'`` per config.

        For each key in the matching config list (``metadata_indexes`` for
        ``table="chunks"``, ``document_metadata_indexes`` for
        ``table="documents"``): ``CREATE INDEX IF NOT EXISTS
        idx_<table>_metadata_<key> ON <table> ((metadata->>'<key>'))``.
        Followed by ``ANALYZE <table>`` so the planner picks up the new
        index immediately.

        Uses non-CONCURRENTLY because:

        - We're inside ``connect()`` which holds the bootstrap advisory
          lock; CONCURRENTLY would fail in that context (it can't run in a
          transaction).
        - For fresh deployments the table is empty or tiny — the
          ACCESS EXCLUSIVE lock is invisible.
        - Production retrofitters should create the index manually with
          CONCURRENTLY first (see docs/cookbook/metadata-indexes.md), then
          add the key to the matching config so this loop's
          ``IF NOT EXISTS`` is a no-op.

        Keys are validated against ``_METADATA_INDEX_KEY_RE`` first so a
        bad config raises a clear error at startup, not a SQL syntax
        error mid-CREATE.
        """
        table = _validate_metadata_table(table)
        keys = (
            self.config.metadata_indexes
            if table == "chunks"
            else self.config.document_metadata_indexes
        )
        for raw_key in keys:
            key = _validate_metadata_index_key(raw_key)
            index_name = _metadata_index_name(key, table=table)
            stmt = sql.SQL(
                "CREATE INDEX IF NOT EXISTS {idx} ON {tbl} ((metadata->>{key}))"
            ).format(
                idx=sql.Identifier(index_name),
                tbl=sql.Identifier(table),
                key=sql.Literal(key),
            )
            try:
                await conn.execute(stmt)
                logger.info(
                    "Ensured metadata index %s on %s.metadata->>%r", index_name, table, key
                )
            except Exception as e:
                # Don't crash connect() over an index failure — the rest of
                # pg-raggraph still works without the optimization. But log
                # loudly so the operator sees it.
                logger.warning(
                    "Failed to create metadata index %s on %s.metadata->>%r: %s. "
                    "Retrieval still works; pre_filter on this key will not benefit "
                    "from indexing until the cause is resolved.",
                    index_name,
                    table,
                    key,
                    e,
                )
        # Refresh planner stats so the new indexes are picked up without
        # waiting for autovacuum.
        try:
            await conn.execute(sql.SQL("ANALYZE {tbl}").format(tbl=sql.Identifier(table)))
        except Exception as e:  # noqa: BLE001 — diagnostic only
            logger.debug("ANALYZE %s after metadata-index apply failed: %s", table, e)

    async def _apply_metadata_gin_index(self, conn, *, table: str = "chunks") -> None:
        """Create a GIN index on the whole ``<table>.metadata`` JSONB column.

        Powers ad-hoc containment / key-existence / multi-key predicates
        that the per-key btree indexes can't serve
        (e.g., ``metadata @> '{"tag":"x"}'``, ``metadata ? 'k'``).

        Uses the default ``jsonb_ops`` operator class — supports all the
        common JSONB query operators. The alternative ``jsonb_path_ops``
        is smaller but only supports ``@>``; we err on the side of
        flexibility since the bool flag is one knob.

        Same non-CONCURRENTLY caveat as ``_apply_metadata_indexes``. For
        production retrofit, run ``CREATE INDEX CONCURRENTLY`` manually
        before flipping the matching bool config field.
        """
        table = _validate_metadata_table(table)
        index_name = _metadata_gin_index_name(table)
        stmt = sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {tbl} USING GIN (metadata)").format(
            idx=sql.Identifier(index_name),
            tbl=sql.Identifier(table),
        )
        try:
            await conn.execute(stmt)
            logger.info("Ensured GIN index %s on %s.metadata", index_name, table)
            await conn.execute(sql.SQL("ANALYZE {tbl}").format(tbl=sql.Identifier(table)))
        except Exception as e:
            logger.warning(
                "Failed to create GIN index %s on %s.metadata: %s. "
                "Retrieval still works; ad-hoc JSONB containment / key-exists "
                "predicates will not benefit from indexing until resolved.",
                index_name,
                table,
                e,
            )

    async def _apply_metadata_generated_columns(self, conn, *, table: str = "chunks") -> None:
        """Add STORED generated columns + btree indexes from JSONB metadata.

        For each ``{key: type_or_spec}`` in the matching config dict
        (``metadata_generated_columns`` for ``table="chunks"``,
        ``document_metadata_generated_columns`` for
        ``table="documents"``):

        1. ``ALTER TABLE <table> ADD COLUMN IF NOT EXISTS meta_<key>
           <type> GENERATED ALWAYS AS ((metadata#>>ARRAY[...])::<type>) STORED``
        2. ``CREATE INDEX IF NOT EXISTS idx_<table>_meta_<key>
           ON <table>(meta_<key>)``
        3. ``ANALYZE <table>``

        The STORED generated column means every existing AND future row
        gets the typed value automatically — no application-side backfill
        code. The cast is evaluated on insert/update; a row whose
        ``metadata->>'<key>'`` doesn't parse as the chosen type fails the
        write. Loud failure beats silent corruption.

        **Idempotent on key + type match.** If the column already exists
        with the configured type, ``ADD COLUMN IF NOT EXISTS`` is a no-op.
        If it exists with a DIFFERENT type, the no-op leaves the old type —
        operator must manually ``ALTER TABLE <table> DROP COLUMN
        meta_<key>`` before the new type takes effect.
        """
        table = _validate_metadata_table(table)
        items = (
            self.config.metadata_generated_columns
            if table == "chunks"
            else self.config.document_metadata_generated_columns
        )
        for raw_key, raw_spec in items.items():
            key, sql_type, json_path = _normalize_metadata_generated_spec(raw_key, raw_spec)
            col = _metadata_generated_column_name(key)
            idx = _metadata_generated_index_name(key, table=table)
            json_text_expr = _metadata_generated_json_text_expr(json_path)
            add_col = sql.SQL(
                "ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} {sqltype} "
                "GENERATED ALWAYS AS ({expr}::{sqltype}) STORED"
            ).format(
                tbl=sql.Identifier(table),
                col=sql.Identifier(col),
                sqltype=sql.SQL(sql_type),
                expr=json_text_expr,
            )
            create_idx = sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {tbl}({col})").format(
                idx=sql.Identifier(idx),
                tbl=sql.Identifier(table),
                col=sql.Identifier(col),
            )
            try:
                await conn.execute(add_col)
                await conn.execute(create_idx)
                logger.info(
                    "Ensured generated column %s.%s (%s) + index %s",
                    table,
                    col,
                    sql_type,
                    idx,
                )
            except Exception as e:
                # Same don't-crash pattern as other helpers. Most common
                # cause: column already exists with a different type, or
                # the cast rejected an existing row's metadata value.
                logger.warning(
                    "Failed to create generated column %s.%s (%s) for key %r: %s. "
                    "Retrieval still works on %s.metadata->>%r; range queries "
                    "fall back to lexical comparison until resolved.",
                    table,
                    col,
                    sql_type,
                    ".".join(json_path),
                    e,
                    table,
                    ".".join(json_path),
                )
        try:
            await conn.execute(sql.SQL("ANALYZE {tbl}").format(tbl=sql.Identifier(table)))
        except Exception as e:  # noqa: BLE001 — diagnostic only
            logger.debug("ANALYZE %s after metadata-generated-columns apply failed: %s", table, e)

    async def apply_metadata_indexes_concurrently(self) -> list[dict[str, Any]]:
        """Create the same set of metadata indexes as ``connect()`` does,
        but using ``CREATE INDEX CONCURRENTLY`` so the operation doesn't
        block writes.

        This is the **production retrofit** path. The default ``connect()``
        flow uses ``CREATE INDEX IF NOT EXISTS`` (non-concurrent, takes
        an ``ACCESS EXCLUSIVE`` lock for the duration of the build).
        That's fine for fresh deployments where the chunks/documents
        tables are empty or tiny, but on a live table with millions of
        rows the lock blocks all writes — often minutes.

        Use this method instead from a **separate maintenance script**
        (NOT during application startup). Typical flow:

        1. Deploy a new config that adds keys to ``metadata_indexes`` /
           ``document_metadata_indexes`` / etc. (but don't restart the
           app yet, or the non-concurrent path will fire).
        2. From a maintenance shell or one-off job, instantiate a
           ``GraphRAG`` and call this method.
        3. After it returns, restart the app — ``connect()``'s
           ``CREATE INDEX IF NOT EXISTS`` finds the existing index and
           the loop is a no-op.

        Generated columns (``ALTER TABLE ... ADD COLUMN ... STORED``)
        are NOT supported by this method — Postgres doesn't have a
        concurrent ADD COLUMN variant. Add those via the connect-time
        path during a maintenance window, or via a DBA-supervised
        migration.

        CONCURRENTLY caveats:

        - Runs **outside** any transaction. We acquire a fresh
          autocommit connection (not from the pool) per index because
          the pool's connections may be inside transactions.
        - A CONCURRENTLY index that fails leaves an INVALID index in
          ``pg_index``. Operators should monitor for invalid indexes
          and DROP + retry if needed.
        - Slower than the non-concurrent variant (two table scans
          instead of one) but doesn't block writes.

        Returns a list of dicts (one per attempted index) with
        ``{"ok": bool, "table": ..., "kind": ..., "key": ...,
        "object_name": ..., "error": ...}``. Mirrors the shape of
        ``rag.add_metadata_index()`` so callers can render results
        uniformly.
        """
        results: list[dict[str, Any]] = []
        # Walk the same six config slots that connect() applies, but
        # only the ones that have a CONCURRENTLY equivalent.
        for table_name, raw_keys in (
            ("chunks", self.config.metadata_indexes),
            ("documents", self.config.document_metadata_indexes),
        ):
            for raw_key in raw_keys:
                results.append(await self._create_btree_concurrently(table_name, raw_key))

        for table_name, want_gin in (
            ("chunks", self.config.metadata_indexes_gin),
            ("documents", self.config.document_metadata_indexes_gin),
        ):
            if want_gin:
                results.append(await self._create_gin_concurrently(table_name))

        # generated_columns: ADD COLUMN can't be CONCURRENTLY. Caller
        # must use the connect()-time path or do it manually with DBA
        # supervision. Report this in the results so the UI can show
        # the operator what was skipped.
        for table_name, gen_cols in (
            ("chunks", self.config.metadata_generated_columns),
            ("documents", self.config.document_metadata_generated_columns),
        ):
            for raw_key in gen_cols:
                results.append(
                    {
                        "ok": False,
                        "table": table_name,
                        "kind": "generated",
                        "key": raw_key,
                        "error": (
                            "Generated columns require ALTER TABLE ADD COLUMN "
                            "which Postgres does not support CONCURRENTLY. "
                            "Apply via connect() during a maintenance window."
                        ),
                    }
                )
        return results

    async def _create_btree_concurrently(self, table: str, raw_key: str) -> dict[str, Any]:
        try:
            table = _validate_metadata_table(table)
            key = _validate_metadata_index_key(raw_key)
        except ValueError as e:
            return {"ok": False, "table": table, "kind": "btree", "key": raw_key, "error": str(e)}
        index_name = _metadata_index_name(key, table=table)
        # CONCURRENTLY can't run in a transaction. Acquire an autocommit
        # connection outside the pool's transactional context.
        try:
            async with await self._connection_autocommit() as conn:
                stmt = sql.SQL(
                    "CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx} ON {tbl} ((metadata->>{key}))"
                ).format(
                    idx=sql.Identifier(index_name),
                    tbl=sql.Identifier(table),
                    key=sql.Literal(key),
                )
                await conn.execute(stmt)
            logger.info(
                "CONCURRENTLY created btree %s on %s.metadata->>%r",
                index_name,
                table,
                key,
            )
            return {
                "ok": True,
                "table": table,
                "kind": "btree",
                "key": key,
                "object_name": index_name,
            }
        except Exception as e:
            logger.warning(
                "CONCURRENTLY btree %s on %s.metadata->>%r failed: %s",
                index_name,
                table,
                key,
                e,
            )
            return {
                "ok": False,
                "table": table,
                "kind": "btree",
                "key": key,
                "error": str(e),
            }

    async def _create_gin_concurrently(self, table: str) -> dict[str, Any]:
        try:
            table = _validate_metadata_table(table)
        except ValueError as e:
            return {"ok": False, "table": table, "kind": "gin", "key": None, "error": str(e)}
        index_name = _metadata_gin_index_name(table)
        try:
            async with await self._connection_autocommit() as conn:
                stmt = sql.SQL(
                    "CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx} ON {tbl} USING GIN (metadata)"
                ).format(
                    idx=sql.Identifier(index_name),
                    tbl=sql.Identifier(table),
                )
                await conn.execute(stmt)
            logger.info("CONCURRENTLY created GIN %s on %s.metadata", index_name, table)
            return {
                "ok": True,
                "table": table,
                "kind": "gin",
                "key": None,
                "object_name": index_name,
            }
        except Exception as e:
            logger.warning("CONCURRENTLY GIN %s on %s.metadata failed: %s", index_name, table, e)
            return {
                "ok": False,
                "table": table,
                "kind": "gin",
                "key": None,
                "error": str(e),
            }

    async def _connection_autocommit(self):
        """Fresh autocommit connection for CONCURRENTLY DDL.

        Pool connections may be inside transactions; CONCURRENTLY DDL
        needs to run outside any transaction. Open a one-off
        connection with autocommit=True and let the caller's
        ``async with`` close it.
        """
        from psycopg import AsyncConnection

        return AsyncConnection.connect(self.config.dsn, autocommit=True)

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
