"""Runtime metadata-index management — recommend / add / remove / list.

Companion to the config-driven auto-create paths in db.py
(``metadata_indexes`` btree, ``metadata_indexes_gin``,
``metadata_generated_columns``). Those run at ``connect()`` and need a
restart to change. This module exposes the same DDL surface as
runtime-callable methods on ``GraphRAG`` so UIs and operators can
sample, recommend, add, and drop indexes without library config
changes.

**Two tables, three index kinds, runtime-callable.**

- Table: ``chunks`` (default — mechanical per-chunk fields), or
  ``documents`` (caller-supplied per-record fields like salesperson /
  product / date). The structured fields a typical GraphRAG ingest
  pulls from a SQL source land on ``documents.metadata`` — that's why
  this API takes a ``table`` parameter and why ``recommend()`` scans
  both tables by default.
- Kinds: ``btree`` (per-key on ``metadata->>'<key>'``), ``gin`` (one
  index covering the whole JSONB column), ``generated`` (typed STORED
  column ``meta_<key>`` + btree on it — the right answer for
  numeric/timestamp range queries).

Recommendation logic is intentionally heuristic — samples
``metadata`` to detect types and selectivity, then ranks candidates by
expected speedup. Output is structured (``IndexRecommendation``) so a
UI can render it as a list with "Apply" buttons.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from psycopg import sql

logger = logging.getLogger("pg_raggraph.index_management")

IndexKind = Literal["btree", "gin", "generated"]
IndexTable = Literal["chunks", "documents"]
_INDEX_KINDS: tuple[IndexKind, ...] = ("btree", "gin", "generated")
_INDEX_TABLES: tuple[IndexTable, ...] = ("chunks", "documents")


# Identifier whitelist mirrors db._METADATA_INDEX_KEY_RE. Duplicated as a
# constant here so this module doesn't pull the leading-underscore name
# from db (which would couple imports). Kept in sync by the validator
# tests.
_METADATA_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,49}$")


@dataclass
class IndexRecommendation:
    """One ranked index suggestion produced by ``recommend()``.

    A UI renders this as a row with: table, key, kind, type,
    rationale, an "Apply" button. The ``rationale`` field is
    human-readable; the structured fields (``selectivity``,
    ``cardinality_ratio``, ``sample_size``, ``confidence``) let the
    UI filter / sort without re-parsing prose.
    """

    table: IndexTable
    key: str
    kind: IndexKind
    sql_type: str | None = None  # populated when kind == "generated"
    rationale: str = ""
    selectivity: float = 0.0  # rows_with_key / total_rows (0.0–1.0)
    cardinality_ratio: float = 0.0  # distinct_values / rows_with_key
    sample_size: int = 0
    sample_values: list[str] = field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    already_exists: bool = False  # True if an index already covers this key


# --- table + name helpers ---


def _validate_table(table: str) -> IndexTable:
    """Whitelist-check the table name. Used everywhere a table value
    enters DDL composition — belt-and-suspenders alongside
    ``sql.Identifier`` escaping."""
    if table not in _INDEX_TABLES:
        raise ValueError(f"Invalid table {table!r}. Must be one of: {_INDEX_TABLES}")
    return table  # type: ignore[return-value]


def _btree_index_name(key: str, table: IndexTable) -> str:
    """``idx_chunks_metadata_<key>`` / ``idx_documents_metadata_<key>``."""
    return f"idx_{table}_metadata_{key}"


def _gin_index_name(table: IndexTable) -> str:
    """One GIN per table — fixed name."""
    return f"idx_{table}_metadata_gin"


def _generated_column_name(key: str) -> str:
    """``meta_<key>`` — the column lives on a specific table, so no
    collision between chunks-side and documents-side generated columns
    by name. Index names below DO encode the table."""
    return f"meta_{key}"


def _generated_index_name(key: str, table: IndexTable) -> str:
    """``idx_chunks_meta_<key>`` / ``idx_documents_meta_<key>``."""
    return f"idx_{table}_meta_{key}"


# --- type inference ---


def _try_parse_int(s: str) -> bool:
    try:
        int(s)
        return True
    except (ValueError, TypeError):
        return False


def _try_parse_float(s: str) -> bool:
    try:
        f = float(s)
        return f == f  # NaN check
    except (ValueError, TypeError):
        return False


_TIMESTAMPTZ_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def _try_parse_timestamptz(s: str) -> bool:
    return bool(_TIMESTAMPTZ_RE.match(s))


def infer_sql_type(values: list[str]) -> str:
    """Pick the narrowest SQL type that fits every sampled value.

    Returns one of the canonical type names that
    ``_validate_metadata_generated_type`` accepts (``text``,
    ``integer``, ``bigint``, ``numeric``, ``timestamptz``,
    ``boolean``). Defaults to ``text`` when nothing else fits.
    """
    if not values:
        return "text"
    non_null = [v for v in values if v is not None and v != ""]
    if not non_null:
        return "text"
    bool_tokens = {v.lower() for v in non_null}
    if bool_tokens.issubset({"true", "false", "t", "f", "yes", "no"}):
        return "boolean"
    if all(_try_parse_int(v) for v in non_null):
        if any(abs(int(v)) >= 2**31 for v in non_null):
            return "bigint"
        return "integer"
    if all(_try_parse_float(v) for v in non_null):
        return "numeric"
    if all(_try_parse_timestamptz(v) for v in non_null):
        return "timestamptz"
    return "text"


# --- recommendation scoring ---


def _score_recommendation(
    table: IndexTable,
    key: str,
    rows_with_key: int,
    total_rows: int,
    distinct_values: int,
    sample_values: list[str],
    already_btree: bool,
    already_generated: bool,
) -> IndexRecommendation | None:
    """Apply the heuristic. Returns None when no index is recommended."""
    if not _METADATA_KEY_RE.match(key):
        return None
    if rows_with_key < 100 or total_rows == 0:
        return None

    selectivity = rows_with_key / total_rows
    cardinality_ratio = distinct_values / rows_with_key if rows_with_key else 0.0
    sql_type = infer_sql_type(sample_values)

    if rows_with_key >= 1000 and 0.001 <= cardinality_ratio <= 0.5:
        confidence: Literal["high", "medium", "low"] = "high"
    elif rows_with_key >= 200:
        confidence = "medium"
    else:
        confidence = "low"

    if sql_type in ("integer", "bigint", "numeric", "timestamptz", "boolean"):
        rationale = (
            f"Typed predicate: {table}.metadata->>{key!r} sampled as {sql_type}. "
            f"Range/order queries against this key need a typed generated column "
            f"({cardinality_ratio:.0%} cardinality, {rows_with_key:,} rows). "
            f"Without it, '10' < '5' lexically."
        )
        return IndexRecommendation(
            table=table,
            key=key,
            kind="generated",
            sql_type=sql_type,
            rationale=rationale,
            selectivity=selectivity,
            cardinality_ratio=cardinality_ratio,
            sample_size=rows_with_key,
            sample_values=sample_values[:5],
            confidence=confidence,
            already_exists=already_generated,
        )

    if cardinality_ratio > 0.8:
        return None
    rationale = (
        f"Selective text predicate: {table}.metadata->>{key!r} has "
        f"{distinct_values:,} distinct values across {rows_with_key:,} rows "
        f"({cardinality_ratio:.1%} cardinality). Btree on the extracted "
        f"key serves equality lookups."
    )
    return IndexRecommendation(
        table=table,
        key=key,
        kind="btree",
        rationale=rationale,
        selectivity=selectivity,
        cardinality_ratio=cardinality_ratio,
        sample_size=rows_with_key,
        sample_values=sample_values[:5],
        confidence=confidence,
        already_exists=already_btree,
    )


# --- database introspection ---
#
# Queries are composed via psycopg.sql with the table name as an
# Identifier — both validated against the _INDEX_TABLES whitelist
# and escaped by psycopg.


def _top_keys_sql(table: IndexTable) -> sql.SQL:
    return sql.SQL(
        "SELECT key, COUNT(*) AS rows_with_key "
        "FROM {tbl} t, jsonb_object_keys(t.metadata) AS key "
        "WHERE jsonb_typeof(t.metadata) = 'object' "
        "GROUP BY key ORDER BY rows_with_key DESC LIMIT %(max_keys)s"
    ).format(tbl=sql.Identifier(table))


def _key_stats_sql(table: IndexTable) -> sql.SQL:
    return sql.SQL(
        "WITH samp AS ("
        "  SELECT t.metadata->>%(key)s AS v FROM {tbl} t "
        "  WHERE t.metadata ? %(key)s LIMIT %(sample_size)s) "
        "SELECT COUNT(*) AS rows_with_key, COUNT(DISTINCT v) AS distinct_values, "
        "       array_agg(v ORDER BY v) FILTER (WHERE v IS NOT NULL) AS sample_values "
        "FROM samp"
    ).format(tbl=sql.Identifier(table))


def _total_rows_sql(table: IndexTable) -> sql.SQL:
    return sql.SQL("SELECT COUNT(*) AS n FROM {tbl}").format(tbl=sql.Identifier(table))


_EXISTING_INDEXES_SQL = sql.SQL(
    "SELECT indexname, indexdef, tablename FROM pg_indexes "
    "WHERE tablename IN ('chunks', 'documents') "
    "  AND (indexname LIKE 'idx_chunks_metadata_%%' "
    "       OR indexname LIKE 'idx_chunks_meta_%%' "
    "       OR indexname LIKE 'idx_documents_metadata_%%' "
    "       OR indexname LIKE 'idx_documents_meta_%%') "
    "ORDER BY tablename, indexname"
)


async def list_existing_metadata_indexes(
    db: Any,
    table: IndexTable | None = None,
) -> list[dict[str, str]]:
    """Snapshot of currently-installed metadata indexes.

    Returns ``[{"name": ..., "definition": ..., "table": ...}, ...]``.
    Filters to one table when ``table`` is set; otherwise returns
    both. Used by ``recommend()`` to mark already-applied candidates
    and by the UI's "Applied" list.
    """
    rows = await db.fetch_all(_EXISTING_INDEXES_SQL)
    out = [
        {"name": r["indexname"], "definition": r["indexdef"], "table": r["tablename"]}
        for r in rows
    ]
    if table is not None:
        out = [r for r in out if r["table"] == table]
    return out


def _existing_keys_from_indexes(
    indexes: list[dict[str, str]],
) -> set[tuple[IndexTable, str, IndexKind]]:
    """Parse pg_indexes definitions back into ``(table, key, kind)``
    tuples. Used to filter the recommendation output so already-
    applied candidates surface with that flag instead of being
    suggested again."""
    btree_key_re = re.compile(r"metadata\s*->>\s*'([^']+)'")
    out: set[tuple[IndexTable, str, IndexKind]] = set()
    for idx in indexes:
        name = idx["name"]
        definition = idx["definition"]
        tbl: IndexTable | None = None
        if name.startswith("idx_chunks_"):
            tbl = "chunks"
        elif name.startswith("idx_documents_"):
            tbl = "documents"
        if tbl is None:
            continue
        if name == _gin_index_name(tbl):
            out.add((tbl, "__full_metadata__", "gin"))
            continue
        if name.startswith(f"idx_{tbl}_metadata_"):
            m = btree_key_re.search(definition)
            if m:
                out.add((tbl, m.group(1), "btree"))
            continue
        if name.startswith(f"idx_{tbl}_meta_"):
            key = name[len(f"idx_{tbl}_meta_") :]
            out.add((tbl, key, "generated"))
    return out


# --- recommend ---


async def _recommend_for_table(
    db: Any,
    table: IndexTable,
    existing: set[tuple[IndexTable, str, IndexKind]],
    *,
    sample_size: int,
    max_keys: int,
) -> list[IndexRecommendation]:
    total_row = await db.fetch_one(_total_rows_sql(table))
    total_rows = total_row["n"] if total_row else 0
    if total_rows == 0:
        return []

    existing_btree = {k for (t, k, kind) in existing if t == table and kind == "btree"}
    existing_generated = {k for (t, k, kind) in existing if t == table and kind == "generated"}

    top_keys = await db.fetch_all(_top_keys_sql(table), {"max_keys": max_keys})

    out: list[IndexRecommendation] = []
    for tk in top_keys:
        key = tk["key"]
        if not _METADATA_KEY_RE.match(key):
            continue
        stats = await db.fetch_one(_key_stats_sql(table), {"key": key, "sample_size": sample_size})
        if not stats or not stats["rows_with_key"]:
            continue
        sample_values = stats.get("sample_values") or []
        rec = _score_recommendation(
            table=table,
            key=key,
            rows_with_key=stats["rows_with_key"],
            total_rows=total_rows,
            distinct_values=stats["distinct_values"],
            sample_values=[v for v in sample_values if v is not None],
            already_btree=key in existing_btree,
            already_generated=key in existing_generated,
        )
        if rec is not None:
            out.append(rec)
    return out


async def recommend(
    db: Any,
    *,
    table: IndexTable | None = None,
    sample_size: int = 10_000,
    max_keys: int = 50,
    max_recommendations: int = 20,
) -> list[IndexRecommendation]:
    """Scan ``metadata`` on one or both tables; return ranked suggestions.

    ``table=None`` (default) scans BOTH ``chunks`` and ``documents`` —
    appropriate for the common GraphRAG case where structured fields
    (salesperson, product, date) live on ``documents.metadata`` and
    only mechanical fields live on ``chunks.metadata``. Set
    ``table="chunks"`` or ``table="documents"`` to scan one.

    Output is sorted: high-confidence first, then by selectivity ×
    low-cardinality, with already-applied recommendations at the
    bottom of their tier (UI shows new suggestions first).
    """
    existing = _existing_keys_from_indexes(await list_existing_metadata_indexes(db))
    tables = [table] if table is not None else list(_INDEX_TABLES)

    all_recs: list[IndexRecommendation] = []
    for t in tables:
        all_recs.extend(
            await _recommend_for_table(
                db,
                t,
                existing,
                sample_size=sample_size,
                max_keys=max_keys,
            )
        )

    def _rank_key(r: IndexRecommendation) -> tuple:
        conf_order = {"high": 0, "medium": 1, "low": 2}
        return (
            r.already_exists,
            conf_order[r.confidence],
            -r.selectivity,
            r.cardinality_ratio,
        )

    all_recs.sort(key=_rank_key)
    return all_recs[:max_recommendations]


# --- DDL execution ---


async def add(
    db: Any,
    key: str,
    *,
    kind: IndexKind = "btree",
    sql_type: str | None = None,
    table: IndexTable = "chunks",
) -> dict[str, Any]:
    """Create one metadata index at runtime, on chunks or documents.

    Same DDL shapes as the config-driven paths in ``db.py``, but
    callable without restart. Returns a dict for UI consumption:
    ``{"ok": bool, "table": ..., "kind": ..., "key": ...,
       "object_name": ..., "error": ...}``.

    For ``kind="gin"`` the ``key`` argument is ignored — GIN covers
    the whole JSONB column (there's only one such index per table).
    """
    # Lazy import to avoid db <-> index_management cycle at module load.
    from pg_raggraph.db import (
        _validate_metadata_generated_type,
        _validate_metadata_index_key,
    )

    try:
        table = _validate_table(table)
    except ValueError as e:
        return {"ok": False, "table": table, "kind": kind, "key": key, "error": str(e)}

    if kind not in _INDEX_KINDS:
        return {
            "ok": False,
            "table": table,
            "kind": kind,
            "key": key,
            "error": f"Invalid kind {kind!r}. Must be one of: {_INDEX_KINDS}",
        }

    if kind == "gin":
        index_name = _gin_index_name(table)
        stmt = sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {tbl} USING GIN (metadata)").format(
            idx=sql.Identifier(index_name),
            tbl=sql.Identifier(table),
        )
        try:
            await db.execute(stmt)
            await db.execute(sql.SQL("ANALYZE {tbl}").format(tbl=sql.Identifier(table)))
            logger.info("Added GIN index %s on %s.metadata", index_name, table)
            return {
                "ok": True,
                "table": table,
                "kind": kind,
                "key": None,
                "object_name": index_name,
            }
        except Exception as e:
            logger.warning("add_metadata_index(GIN, table=%s) failed: %s", table, e)
            return {"ok": False, "table": table, "kind": kind, "key": None, "error": str(e)}

    try:
        key = _validate_metadata_index_key(key)
    except ValueError as e:
        return {"ok": False, "table": table, "kind": kind, "key": key, "error": str(e)}

    if kind == "btree":
        index_name = _btree_index_name(key, table)
        stmt = sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {tbl} ((metadata->>{key}))").format(
            idx=sql.Identifier(index_name),
            tbl=sql.Identifier(table),
            key=sql.Literal(key),
        )
        try:
            await db.execute(stmt)
            await db.execute(sql.SQL("ANALYZE {tbl}").format(tbl=sql.Identifier(table)))
            logger.info("Added btree index %s on %s.metadata->>%r", index_name, table, key)
            return {
                "ok": True,
                "table": table,
                "kind": kind,
                "key": key,
                "object_name": index_name,
            }
        except Exception as e:
            logger.warning("add_metadata_index(btree, table=%s, key=%r) failed: %s", table, key, e)
            return {
                "ok": False,
                "table": table,
                "kind": kind,
                "key": key,
                "error": str(e),
            }

    # kind == "generated"
    if sql_type is None:
        return {
            "ok": False,
            "table": table,
            "kind": kind,
            "key": key,
            "error": "sql_type is required for kind='generated'",
        }
    try:
        canon = _validate_metadata_generated_type(sql_type)
    except ValueError as e:
        return {"ok": False, "table": table, "kind": kind, "key": key, "error": str(e)}
    col = _generated_column_name(key)
    idx = _generated_index_name(key, table)
    add_col = sql.SQL(
        "ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} {sqltype} "
        "GENERATED ALWAYS AS ((metadata->>{key})::{sqltype}) STORED"
    ).format(
        tbl=sql.Identifier(table),
        col=sql.Identifier(col),
        sqltype=sql.SQL(canon),
        key=sql.Literal(key),
    )
    create_idx = sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {tbl}({col})").format(
        idx=sql.Identifier(idx),
        tbl=sql.Identifier(table),
        col=sql.Identifier(col),
    )
    try:
        await db.execute(add_col)
        await db.execute(create_idx)
        await db.execute(sql.SQL("ANALYZE {tbl}").format(tbl=sql.Identifier(table)))
        logger.info("Added generated column %s.%s (%s) + index %s", table, col, canon, idx)
        return {
            "ok": True,
            "table": table,
            "kind": kind,
            "key": key,
            "object_name": col,
            "index_name": idx,
            "sql_type": canon,
        }
    except Exception as e:
        logger.warning(
            "add_metadata_index(generated, table=%s, key=%r, type=%s) failed: %s",
            table,
            key,
            canon,
            e,
        )
        return {"ok": False, "table": table, "kind": kind, "key": key, "error": str(e)}


async def remove(
    db: Any,
    key: str,
    *,
    kind: IndexKind = "btree",
    table: IndexTable = "chunks",
) -> dict[str, Any]:
    """Drop a metadata index. For ``kind="generated"`` also drops the
    column (cascades to the index).

    Same return shape as ``add()``. Idempotent: dropping a
    non-existent index returns ``ok=True`` (use ``IF EXISTS``).
    """
    from pg_raggraph.db import _validate_metadata_index_key

    try:
        table = _validate_table(table)
    except ValueError as e:
        return {"ok": False, "table": table, "kind": kind, "key": key, "error": str(e)}

    if kind not in _INDEX_KINDS:
        return {
            "ok": False,
            "table": table,
            "kind": kind,
            "key": key,
            "error": f"Invalid kind {kind!r}. Must be one of: {_INDEX_KINDS}",
        }

    if kind == "gin":
        idx_name = _gin_index_name(table)
        stmt = sql.SQL("DROP INDEX IF EXISTS {idx}").format(idx=sql.Identifier(idx_name))
        try:
            await db.execute(stmt)
            logger.info("Removed GIN index %s", idx_name)
            return {
                "ok": True,
                "table": table,
                "kind": kind,
                "key": None,
                "object_name": idx_name,
            }
        except Exception as e:
            return {"ok": False, "table": table, "kind": kind, "key": None, "error": str(e)}

    try:
        key = _validate_metadata_index_key(key)
    except ValueError as e:
        return {"ok": False, "table": table, "kind": kind, "key": key, "error": str(e)}

    if kind == "btree":
        idx = _btree_index_name(key, table)
        stmt = sql.SQL("DROP INDEX IF EXISTS {idx}").format(idx=sql.Identifier(idx))
        try:
            await db.execute(stmt)
            logger.info("Removed btree index %s", idx)
            return {
                "ok": True,
                "table": table,
                "kind": kind,
                "key": key,
                "object_name": idx,
            }
        except Exception as e:
            return {"ok": False, "table": table, "kind": kind, "key": key, "error": str(e)}

    # kind == "generated" — drop column (the index goes with it).
    col = _generated_column_name(key)
    stmt = sql.SQL("ALTER TABLE {tbl} DROP COLUMN IF EXISTS {col}").format(
        tbl=sql.Identifier(table),
        col=sql.Identifier(col),
    )
    try:
        await db.execute(stmt)
        logger.info("Removed generated column %s.%s (and its index)", table, col)
        return {
            "ok": True,
            "table": table,
            "kind": kind,
            "key": key,
            "object_name": col,
        }
    except Exception as e:
        return {"ok": False, "table": table, "kind": kind, "key": key, "error": str(e)}


__all__ = [
    "IndexKind",
    "IndexRecommendation",
    "IndexTable",
    "_existing_keys_from_indexes",
    "_score_recommendation",
    "add",
    "infer_sql_type",
    "list_existing_metadata_indexes",
    "recommend",
    "remove",
]
