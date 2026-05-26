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
