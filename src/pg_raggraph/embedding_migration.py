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
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS embedding_tmp vector({int(target_dim)})"
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
    row = await db.fetch_one(f"SELECT count(*) AS n FROM {table} WHERE embedding_tmp IS NULL")
    return int(row["n"])


async def status(db) -> dict[str, Any]:
    state = await get_state(db)
    if state is None:
        return {"active": False}
    phase = state["phase"]
    # After cutover/finalize, embedding_tmp no longer exists; skip those queries.
    if phase in ("cutover", "finalized"):
        remaining = {t: 0 for t in TABLES}
        indexed = {t: await _index_exists(db, _LIVE_INDEX[t]) for t in TABLES}
    else:
        remaining = {t: await _remaining_null(db, t) for t in TABLES}
        indexed = {t: await _index_exists(db, _TMP_INDEX[t]) for t in TABLES}
    return {
        "active": True,
        "phase": phase,
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
        "UPDATE embedding_migration SET phase='backfilled', updated_at=now() WHERE id IS TRUE"
    )
    return total


async def build_index(db, *, hnsw_m: int = 16, hnsw_ef_construction: int = 64) -> None:
    """Build HNSW indexes on embedding_tmp. Uses CONCURRENTLY (no table lock).

    CREATE INDEX CONCURRENTLY cannot run inside a transaction block, so each
    statement runs on an autocommit connection.
    """
    state = await get_state(db)
    if state is None:
        raise RuntimeError("no active migration; run prepare first")
    for table in TABLES:
        idx = _TMP_INDEX[table]
        async with db.pool.connection() as conn:
            await conn.set_autocommit(True)
            await conn.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx} "
                f"ON {table} USING hnsw (embedding_tmp vector_cosine_ops) "
                f"WITH (m = {int(hnsw_m)}, ef_construction = {int(hnsw_ef_construction)})"
            )
    await db.execute(
        "UPDATE embedding_migration SET phase='indexed', updated_at=now() WHERE id IS TRUE"
    )


async def cutover(db) -> None:
    """Swap embedding_tmp into place as the live embedding column (brief lock).

    Refuses unless every table is fully backfilled and indexed. All DDL runs in
    one transaction; renames are catalog-only so the ACCESS EXCLUSIVE window is
    sub-second. embedding_old is preserved for rollback until finalize.
    """
    state = await get_state(db)
    if state is None:
        raise RuntimeError("no active migration; run prepare first")
    target_dim = int(state["target_dim"])
    for table in TABLES:
        if await _remaining_null(db, table) != 0:
            raise RuntimeError(f"cutover not ready: {table} has un-backfilled rows")
        if not await _index_exists(db, _TMP_INDEX[table]):
            raise RuntimeError(f"cutover not ready: {table} embedding_tmp not indexed")

    async with db.pool.connection() as conn:
        for table in TABLES:
            await conn.execute(f"DROP INDEX IF EXISTS {_LIVE_INDEX[table]}")
            await conn.execute(f"ALTER TABLE {table} RENAME COLUMN embedding TO embedding_old")
            await conn.execute(f"ALTER TABLE {table} RENAME COLUMN embedding_tmp TO embedding")
            await conn.execute(f"ALTER INDEX {_TMP_INDEX[table]} RENAME TO {_LIVE_INDEX[table]}")
        await conn.execute("TRUNCATE embedding_cache")
        await conn.execute(
            f"ALTER TABLE embedding_cache ALTER COLUMN embedding TYPE vector({target_dim})"
        )
        await conn.execute(
            "UPDATE pgrg_meta SET value = %s WHERE key = 'embedding_dim'",
            (str(target_dim),),
        )
        await conn.execute(
            "UPDATE embedding_migration SET phase='cutover', updated_at=now() WHERE id IS TRUE"
        )


async def finalize(db) -> None:
    """Drop the preserved embedding_old columns and clear migration state."""
    state = await get_state(db)
    if state is None:
        raise RuntimeError("no active migration to finalize")
    if state["phase"] != "cutover":
        raise RuntimeError("can only finalize after cutover")
    for table in TABLES:
        await db.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS embedding_old")
    await db.execute("DELETE FROM embedding_migration WHERE id IS TRUE")


async def backfill_from_sink(db, sink_rows, *, entity_embedder, batch_size: int = 256) -> int:
    """Backfill chunks from precomputed chunkshop sink vectors; entities re-embed.

    Each sink row needs ``chunkshop_doc_id``, ``chunkshop_seq_num``, ``embedding``.
    Chunk rows are matched on the metadata pg-raggraph stored at ingest time
    (chunks.metadata->>'chunkshop_doc_id' / 'chunkshop_seq_num').
    """
    state = await get_state(db)
    if state is None:
        raise RuntimeError("no active migration; run prepare first")

    total = 0
    async with db.pool.connection() as conn:
        for row in sink_rows:
            doc_id = row["chunkshop_doc_id"]
            seq = row["chunkshop_seq_num"]
            emb = [float(x) for x in row["embedding"]]
            cur = await conn.execute(
                "UPDATE chunks SET embedding_tmp = %s "
                "WHERE metadata->>'chunkshop_doc_id' = %s "
                "  AND (metadata->>'chunkshop_seq_num')::int = %s",
                (emb, str(doc_id), int(seq)),
            )
            total += cur.rowcount

    total += await _backfill_table(db, entity_embedder, "entities", batch_size=batch_size)

    await db.execute(
        "UPDATE embedding_migration SET phase='backfilled', updated_at=now() WHERE id IS TRUE"
    )
    return total
