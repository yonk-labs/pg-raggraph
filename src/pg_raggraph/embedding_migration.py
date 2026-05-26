"""Online embedding-model migration via expand/contract column swap.

Operator-driven phases run over a ``Database`` pool. The live column is always
named ``embedding``; a second ``embedding_tmp`` column is added, backfilled,
indexed, then renamed into place. See
docs/superpowers/specs/2026-05-26-online-embedding-migration-design.md.
"""

from __future__ import annotations

import re
from typing import Any

# Tables carrying a vector(dim) ``embedding`` column that must migrate together.
TABLES = ("chunks", "entities")

# Text source per table for re-embedding into embedding_tmp.
_TEXT_SOURCE = {
    "chunks": "COALESCE(embedded_content, content)",
    "entities": "name || ' ' || COALESCE(description, '')",
}

_LIVE_INDEX = {"chunks": "idx_chunk_embed", "entities": "idx_entity_embed"}
_TMP_INDEX = {"chunks": "idx_chunk_embed_tmp", "entities": "idx_entity_embed_tmp"}

_DIM_RE = re.compile(r"vector\((\d+)\)")


async def get_state(db) -> dict[str, Any] | None:
    """Return the active migration row, or None when no migration is active."""
    return await db.fetch_one("SELECT * FROM embedding_migration WHERE id IS TRUE")


async def column_dim(db, table: str, column: str = "embedding") -> int | None:
    """Return the declared pgvector dimension of ``table.column`` (None if absent)."""
    row = await db.fetch_one(
        "SELECT format_type(a.atttypid, a.atttypmod) AS t "
        "FROM pg_attribute a "
        "WHERE a.attrelid = %s::regclass AND a.attname = %s AND a.attnum > 0 "
        "  AND NOT a.attisdropped",
        (table, column),
    )
    if not row or not row["t"]:
        return None
    m = _DIM_RE.search(row["t"])
    return int(m.group(1)) if m else None


async def prepare(
    db,
    *,
    target_model: str,
    target_dim: int,
    backfill_source: str = "reembed",
) -> None:
    """Add embedding_tmp(target_dim) to all TABLES and record migration state."""
    if backfill_source not in ("reembed", "chunkshop_sink"):
        raise ValueError(f"unknown backfill_source: {backfill_source!r}")
    if await get_state(db) is not None:
        raise RuntimeError("a migration is already active; finalize it first")
    for table in TABLES:
        await db.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
            f"embedding_tmp vector({int(target_dim)})"
        )
    await db.execute(
        "INSERT INTO embedding_migration "
        "(id, target_model, target_dim, phase, backfill_source) "
        "VALUES (TRUE, %s, %s, 'prepared', %s)",
        (target_model, int(target_dim), backfill_source),
    )


async def _index_exists(db, name: str) -> bool:
    row = await db.fetch_one("SELECT to_regclass(%s) AS t", (name,))
    return bool(row and row["t"])


async def _remaining_null(db, table: str) -> int:
    row = await db.fetch_one(
        f"SELECT count(*) AS n FROM {table} WHERE embedding_tmp IS NULL"
    )
    return int(row["n"])


async def status(db) -> dict[str, Any]:
    state = await get_state(db)
    if state is None:
        return {"active": False}
    remaining = {t: await _remaining_null(db, t) for t in TABLES}
    indexed = {t: await _index_exists(db, _TMP_INDEX[t]) for t in TABLES}
    return {
        "active": True,
        "phase": state["phase"],
        "target_model": state["target_model"],
        "target_dim": state["target_dim"],
        "backfill_source": state["backfill_source"],
        "remaining": remaining,
        "indexed": indexed,
    }


async def _backfill_table(db, embedder, table: str, batch_size: int) -> int:
    text_expr = _TEXT_SOURCE[table]
    total = 0
    while True:
        rows = await db.fetch_all(
            f"SELECT id, {text_expr} AS text FROM {table} "
            f"WHERE embedding_tmp IS NULL ORDER BY id LIMIT %s",
            (batch_size,),
        )
        if not rows:
            break
        texts = [r["text"] or "" for r in rows]
        vecs = await embedder.embed(texts)
        async with db.pool.connection() as conn:
            for r, v in zip(rows, vecs):
                await conn.execute(
                    f"UPDATE {table} SET embedding_tmp = %s WHERE id = %s",
                    (v, r["id"]),
                )
        total += len(rows)
    return total


async def backfill(db, embedder, *, batch_size: int = 256) -> int:
    """Re-embed every TABLE's text into embedding_tmp with the new model.

    Resumable and idempotent: only rows with NULL embedding_tmp are processed.
    Bypasses embedding_cache by design (cache is bound to the old dimension).
    """
    state = await get_state(db)
    if state is None:
        raise RuntimeError("no active migration; run prepare first")
    total = 0
    for table in TABLES:
        total += await _backfill_table(db, embedder, table, batch_size)
    await db.execute(
        "UPDATE embedding_migration SET phase='backfilled', updated_at=now() "
        "WHERE id IS TRUE"
    )
    return total
