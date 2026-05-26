# Online Embedding-Model Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator move a live pg-raggraph database to a new embedding model/dimension via an online expand/contract column swap, without a parallel database and without losing the entity graph.

**Architecture:** A new `embedding_migration.py` module exposes six phase functions driven by a `pgrg migrate-embeddings` CLI group. State lives in a singleton-row `embedding_migration` table (migration `010`). A second `embedding_tmp vector(new_dim)` column is added to `chunks` and `entities`, backfilled online with the new model, indexed CONCURRENTLY, then swapped into place as `embedding` during a brief locked cutover. The retrieval read-path is never touched — queries always read `c.embedding`.

**Tech Stack:** Python 3.12+, psycopg3 async, pgvector, Click CLI, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-26-online-embedding-migration-design.md`

---

## File Structure

- **Create** `src/pg_raggraph/sql/migrations/010_embedding_migration.sql` — the state table.
- **Create** `src/pg_raggraph/embedding_migration.py` — phase functions + helpers. Single responsibility: orchestrate the migration state machine over a `Database` pool.
- **Modify** `src/pg_raggraph/db.py` — add an embedding-dim startup guard in `connect()`.
- **Modify** `src/pg_raggraph/cli.py` — add the `migrate-embeddings` Click group.
- **Create** `tests/unit/test_embedding_migration.py` — pure-logic unit tests (text-source SQL, dim parsing, guard refusals).
- **Create** `tests/integration/test_embedding_migration.py` — full-lifecycle test against real PG with a stub embedder.

> **Test-infra note (revised during execution):** The migration is DB-wide and
> destructive, so it cannot share the namespace-isolated integration DB. Each
> integration test uses a `fresh_db` pytest fixture that creates a throwaway
> database (with `vector`/`pg_trgm` extensions), yields its DSN, and drops it after.
> The helper signature is `_fresh_rag(fresh_db, dim, embedder)` and every test takes
> the `fresh_db` fixture parameter. The Task-3..12 snippets below predate this and
> show `_fresh_rag(dim, embedder)` — use the fixture form when implementing.

Conventions observed from the codebase:
- `Database` (db.py) exposes `db.execute(sql, params)`, `db.fetch_all(sql, params)`, `db.fetch_one(sql, params)`, and the `db.pool` property whose `db.pool.connection()` async context manager is one transaction (commits on clean exit).
- Embedders satisfy `EmbeddingProvider` (`embedding.py`): `async def embed(self, texts: list[str]) -> list[list[float]]`.
- Migration files are auto-applied by `Database._apply_migrations` on `connect()`, tracked in `pgrg_applied_migrations` by filename.
- HNSW index names today: `idx_chunk_embed` (chunks), `idx_entity_embed` (entities). HNSW params from config: `hnsw_m=16`, `hnsw_ef_construction=64`.
- `pgrg_meta` holds an `embedding_dim` row written at bootstrap.

---

## Task 1: State-table migration

**Files:**
- Create: `src/pg_raggraph/sql/migrations/010_embedding_migration.sql`
- Test: `tests/integration/test_embedding_migration.py`

- [ ] **Step 1: Write the migration SQL**

Create `src/pg_raggraph/sql/migrations/010_embedding_migration.sql`:

```sql
-- Online embedding-model migration state (single active migration at a time).
CREATE TABLE IF NOT EXISTS embedding_migration (
    id              BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
    target_model    TEXT NOT NULL,
    target_dim      INT  NOT NULL,
    phase           TEXT NOT NULL,          -- prepared|backfilled|indexed|cutover
    backfill_source TEXT NOT NULL DEFAULT 'reembed',  -- reembed|chunkshop_sink
    started_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
```

- [ ] **Step 2: Write a failing test that the migration applies and the table exists**

Add to `tests/integration/test_embedding_migration.py`:

```python
import os
import pytest
from pg_raggraph import GraphRAG

DSN = os.environ.get("PGRG_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="requires PGRG_TEST_DSN")


async def _fresh_rag(dim, embedder):
    rag = GraphRAG(dsn=DSN, embedding_dim=dim, namespace="emig_test")
    rag._embedder = embedder
    await rag.connect()
    # isolate this test's schema objects from any shared DB
    await rag._db.execute("DELETE FROM embedding_migration")
    return rag


class StubEmbedder:
    def __init__(self, dim):
        self.dim = dim

    async def embed(self, texts):
        return [[float((i % 7) + 1)] * self.dim for i, _ in enumerate(texts)]


@pytest.mark.asyncio
async def test_migration_010_creates_state_table():
    rag = await _fresh_rag(4, StubEmbedder(4))
    try:
        row = await rag._db.fetch_one(
            "SELECT to_regclass('embedding_migration') AS t"
        )
        assert row["t"] == "embedding_migration"
    finally:
        await rag.close()
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py::test_migration_010_creates_state_table -v`
Expected: PASS (migration auto-applied on connect; table present).

- [ ] **Step 4: Commit**

```bash
git add src/pg_raggraph/sql/migrations/010_embedding_migration.sql tests/integration/test_embedding_migration.py
git commit -m "feat: add embedding_migration state table (migration 010)"
```

---

## Task 2: Module skeleton — `get_state`, `column_dim`, constants

**Files:**
- Create: `src/pg_raggraph/embedding_migration.py`
- Test: `tests/integration/test_embedding_migration.py`

- [ ] **Step 1: Write the module skeleton**

Create `src/pg_raggraph/embedding_migration.py`:

```python
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
```

- [ ] **Step 2: Write a failing test for `column_dim`**

Add to `tests/integration/test_embedding_migration.py`:

```python
from pg_raggraph import embedding_migration as em


@pytest.mark.asyncio
async def test_column_dim_reads_live_dimension():
    rag = await _fresh_rag(4, StubEmbedder(4))
    try:
        assert await em.column_dim(rag._db, "chunks", "embedding") == 4
        assert await em.column_dim(rag._db, "chunks", "embedding_tmp") is None
    finally:
        await rag.close()
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py::test_column_dim_reads_live_dimension -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/pg_raggraph/embedding_migration.py tests/integration/test_embedding_migration.py
git commit -m "feat: add embedding_migration module skeleton (state + column_dim)"
```

---

## Task 3: `prepare` phase

**Files:**
- Modify: `src/pg_raggraph/embedding_migration.py`
- Test: `tests/integration/test_embedding_migration.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/integration/test_embedding_migration.py`:

```python
@pytest.mark.asyncio
async def test_prepare_adds_tmp_columns_and_state():
    rag = await _fresh_rag(4, StubEmbedder(4))
    try:
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        assert await em.column_dim(rag._db, "chunks", "embedding_tmp") == 6
        assert await em.column_dim(rag._db, "entities", "embedding_tmp") == 6
        state = await em.get_state(rag._db)
        assert state["target_dim"] == 6
        assert state["target_model"] == "stub-6"
        assert state["phase"] == "prepared"
    finally:
        await rag.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py::test_prepare_adds_tmp_columns_and_state -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'prepare'`.

- [ ] **Step 3: Implement `prepare`**

Append to `src/pg_raggraph/embedding_migration.py`:

```python
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
```

Note: `int(target_dim)` is interpolated into DDL because pgvector's `vector(n)`
type modifier cannot be a bind parameter. It is cast to `int`, so it is safe.

- [ ] **Step 4: Run the test to verify it passes**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py::test_prepare_adds_tmp_columns_and_state -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/embedding_migration.py tests/integration/test_embedding_migration.py
git commit -m "feat: add prepare phase to embedding migration"
```

---

## Task 4: `status` phase

**Files:**
- Modify: `src/pg_raggraph/embedding_migration.py`
- Test: `tests/integration/test_embedding_migration.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/integration/test_embedding_migration.py`:

```python
@pytest.mark.asyncio
async def test_status_reports_phase_and_remaining():
    rag = await _fresh_rag(4, StubEmbedder(4))
    try:
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        st = await em.status(rag._db)
        assert st["active"] is True
        assert st["phase"] == "prepared"
        assert st["remaining"] == {"chunks": 0, "entities": 0}
        assert st["indexed"] == {"chunks": False, "entities": False}
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_status_inactive_when_no_migration():
    rag = await _fresh_rag(4, StubEmbedder(4))
    try:
        st = await em.status(rag._db)
        assert st["active"] is False
    finally:
        await rag.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py -k status -v`
Expected: FAIL with `AttributeError: ... 'status'`.

- [ ] **Step 3: Implement `status` and an index-presence helper**

Append to `src/pg_raggraph/embedding_migration.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py -k status -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/embedding_migration.py tests/integration/test_embedding_migration.py
git commit -m "feat: add status phase to embedding migration"
```

---

## Task 5: `backfill` phase (reembed source)

**Files:**
- Modify: `src/pg_raggraph/embedding_migration.py`
- Test: `tests/integration/test_embedding_migration.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/integration/test_embedding_migration.py`. This test ingests one
document so there are real chunk/entity rows to backfill:

```python
@pytest.mark.asyncio
async def test_backfill_fills_tmp_with_target_dim():
    rag = await _fresh_rag(4, StubEmbedder(4))
    try:
        await rag.ingest("Ada Lovelace wrote the first algorithm.", source_id="d1")
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        n = await em.backfill(rag._db, StubEmbedder(6), batch_size=2)
        assert n > 0
        assert await em._remaining_null(rag._db, "chunks") == 0
        row = await rag._db.fetch_one(
            "SELECT vector_dims(embedding_tmp) AS d FROM chunks "
            "WHERE embedding_tmp IS NOT NULL LIMIT 1"
        )
        assert row["d"] == 6
    finally:
        await rag.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py::test_backfill_fills_tmp_with_target_dim -v`
Expected: FAIL with `AttributeError: ... 'backfill'`.

- [ ] **Step 3: Implement `backfill`**

Append to `src/pg_raggraph/embedding_migration.py`:

```python
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
```

Note: pgvector vectors are passed as Python `list[float]`; psycopg's registered
vector adapter (via `register_vector_async` in `connect()`) handles binding.

- [ ] **Step 4: Run the test to verify it passes**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py::test_backfill_fills_tmp_with_target_dim -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/embedding_migration.py tests/integration/test_embedding_migration.py
git commit -m "feat: add backfill phase to embedding migration"
```

---

## Task 6: `build_index` phase

**Files:**
- Modify: `src/pg_raggraph/embedding_migration.py`
- Test: `tests/integration/test_embedding_migration.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/integration/test_embedding_migration.py`:

```python
@pytest.mark.asyncio
async def test_build_index_creates_tmp_hnsw():
    rag = await _fresh_rag(4, StubEmbedder(4))
    try:
        await rag.ingest("Ada Lovelace wrote the first algorithm.", source_id="d1")
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        await em.backfill(rag._db, StubEmbedder(6), batch_size=8)
        await em.build_index(rag._db)
        assert await em._index_exists(rag._db, "idx_chunk_embed_tmp")
        assert await em._index_exists(rag._db, "idx_entity_embed_tmp")
        st = await em.status(rag._db)
        assert st["phase"] == "indexed"
    finally:
        await rag.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py::test_build_index_creates_tmp_hnsw -v`
Expected: FAIL with `AttributeError: ... 'build_index'`.

- [ ] **Step 3: Implement `build_index`**

Append to `src/pg_raggraph/embedding_migration.py`:

```python
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
        "UPDATE embedding_migration SET phase='indexed', updated_at=now() "
        "WHERE id IS TRUE"
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py::test_build_index_creates_tmp_hnsw -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/embedding_migration.py tests/integration/test_embedding_migration.py
git commit -m "feat: add build-index phase to embedding migration"
```

---

## Task 7: `cutover` phase

**Files:**
- Modify: `src/pg_raggraph/embedding_migration.py`
- Test: `tests/integration/test_embedding_migration.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/integration/test_embedding_migration.py`:

```python
@pytest.mark.asyncio
async def test_cutover_swaps_columns_and_retypes_cache():
    rag = await _fresh_rag(4, StubEmbedder(4))
    try:
        await rag.ingest("Ada Lovelace wrote the first algorithm.", source_id="d1")
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        await em.backfill(rag._db, StubEmbedder(6), batch_size=8)
        await em.build_index(rag._db)
        await em.cutover(rag._db)
        # live column is now dim 6 and the old column is preserved
        assert await em.column_dim(rag._db, "chunks", "embedding") == 6
        assert await em.column_dim(rag._db, "chunks", "embedding_old") == 4
        # cache column retyped to new dim
        assert await em.column_dim(rag._db, "embedding_cache", "embedding") == 6
        # live index restored under its canonical name
        assert await em._index_exists(rag._db, "idx_chunk_embed")
        st = await em.status(rag._db)
        assert st["phase"] == "cutover"
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_cutover_refused_before_index_and_backfill():
    rag = await _fresh_rag(4, StubEmbedder(4))
    try:
        await rag.ingest("Ada Lovelace wrote the first algorithm.", source_id="d1")
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        with pytest.raises(RuntimeError, match="not ready"):
            await em.cutover(rag._db)
    finally:
        await rag.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py -k cutover -v`
Expected: FAIL with `AttributeError: ... 'cutover'`.

- [ ] **Step 3: Implement `cutover`**

Append to `src/pg_raggraph/embedding_migration.py`:

```python
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
            await conn.execute(
                f"ALTER TABLE {table} RENAME COLUMN embedding TO embedding_old"
            )
            await conn.execute(
                f"ALTER TABLE {table} RENAME COLUMN embedding_tmp TO embedding"
            )
            await conn.execute(
                f"ALTER INDEX {_TMP_INDEX[table]} RENAME TO {_LIVE_INDEX[table]}"
            )
        # embedding_cache is vector(old_dim); empty it then retype to new dim.
        await conn.execute("TRUNCATE embedding_cache")
        await conn.execute(
            f"ALTER TABLE embedding_cache "
            f"ALTER COLUMN embedding TYPE vector({target_dim})"
        )
        await conn.execute(
            "UPDATE pgrg_meta SET value = %s WHERE key = 'embedding_dim'",
            (str(target_dim),),
        )
        await conn.execute(
            "UPDATE embedding_migration SET phase='cutover', updated_at=now() "
            "WHERE id IS TRUE"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py -k cutover -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/embedding_migration.py tests/integration/test_embedding_migration.py
git commit -m "feat: add cutover phase to embedding migration"
```

---

## Task 8: `finalize` phase

**Files:**
- Modify: `src/pg_raggraph/embedding_migration.py`
- Test: `tests/integration/test_embedding_migration.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/integration/test_embedding_migration.py`:

```python
@pytest.mark.asyncio
async def test_finalize_drops_old_and_clears_state():
    rag = await _fresh_rag(4, StubEmbedder(4))
    try:
        await rag.ingest("Ada Lovelace wrote the first algorithm.", source_id="d1")
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        await em.backfill(rag._db, StubEmbedder(6), batch_size=8)
        await em.build_index(rag._db)
        await em.cutover(rag._db)
        await em.finalize(rag._db)
        assert await em.column_dim(rag._db, "chunks", "embedding_old") is None
        assert await em.get_state(rag._db) is None
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_finalize_refused_before_cutover():
    rag = await _fresh_rag(4, StubEmbedder(4))
    try:
        await em.prepare(rag._db, target_model="stub-6", target_dim=6)
        with pytest.raises(RuntimeError, match="cutover"):
            await em.finalize(rag._db)
    finally:
        await rag.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py -k finalize -v`
Expected: FAIL with `AttributeError: ... 'finalize'`.

- [ ] **Step 3: Implement `finalize`**

Append to `src/pg_raggraph/embedding_migration.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py -k finalize -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/embedding_migration.py tests/integration/test_embedding_migration.py
git commit -m "feat: add finalize phase to embedding migration"
```

---

## Task 9: Unit test for dimension parsing (no DB)

**Files:**
- Create: `tests/unit/test_embedding_migration.py`

This isolates the `_DIM_RE` parsing and text-source map so they are covered
without a database.

- [ ] **Step 1: Write the test**

Create `tests/unit/test_embedding_migration.py`:

```python
from pg_raggraph import embedding_migration as em


def test_dim_regex_parses_vector_type():
    assert em._DIM_RE.search("vector(768)").group(1) == "768"
    assert em._DIM_RE.search("vector") is None  # unconstrained vector has no dim


def test_text_source_map_covers_all_tables():
    assert set(em._TEXT_SOURCE) == set(em.TABLES)
    assert "embedded_content" in em._TEXT_SOURCE["chunks"]
    assert "description" in em._TEXT_SOURCE["entities"]


def test_index_name_maps_cover_all_tables():
    assert set(em._LIVE_INDEX) == set(em.TABLES)
    assert set(em._TMP_INDEX) == set(em.TABLES)
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_embedding_migration.py -v`
Expected: PASS (3 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_embedding_migration.py
git commit -m "test: unit cover embedding migration parsing and maps"
```

---

## Task 10: Startup embedding-dim guard

**Files:**
- Modify: `src/pg_raggraph/db.py` (inside `connect()`, after schema is ready, around line 276)
- Test: `tests/integration/test_embedding_migration.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/integration/test_embedding_migration.py`:

```python
@pytest.mark.asyncio
async def test_connect_raises_on_dim_mismatch():
    # bootstrap at dim 4
    rag = await _fresh_rag(4, StubEmbedder(4))
    await rag.close()
    # reconnect declaring a different dim -> guard must raise
    bad = GraphRAG(dsn=DSN, embedding_dim=5, namespace="emig_test")
    bad._embedder = StubEmbedder(5)
    with pytest.raises(ValueError, match="embedding_dim"):
        await bad.connect()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py::test_connect_raises_on_dim_mismatch -v`
Expected: FAIL (no exception raised; test errors on missing `pytest.raises` match).

- [ ] **Step 3: Implement the guard in `connect()`**

In `src/pg_raggraph/db.py`, inside `connect()`, immediately after the metadata-index
block (after line 276, still inside `async with self._pool.connection() as conn:`),
add:

```python
            await self._verify_embedding_dim(conn)
```

Then add this method to the `Database` class (near `_verify_schema_ready`):

```python
    async def _verify_embedding_dim(self, conn) -> None:
        """Fail fast if configured embedding_dim != live chunks.embedding dim.

        Catches "operator forgot to update PGRG_EMBEDDING_DIM after an embedding
        migration cutover" before it becomes an opaque pgvector runtime error.
        """
        cur = await conn.execute(
            "SELECT format_type(a.atttypid, a.atttypmod) AS t "
            "FROM pg_attribute a "
            "WHERE a.attrelid = 'chunks'::regclass AND a.attname = 'embedding' "
            "  AND a.attnum > 0 AND NOT a.attisdropped"
        )
        row = await cur.fetchone()
        if not row or not row[0]:
            return
        import re

        m = re.search(r"vector\((\d+)\)", row[0])
        if not m:
            return
        live_dim = int(m.group(1))
        if live_dim != self.config.embedding_dim:
            raise ValueError(
                f"Configured embedding_dim={self.config.embedding_dim} does not "
                f"match the live chunks.embedding dimension ({live_dim}). If you "
                f"just ran an embedding migration cutover, set "
                f"PGRG_EMBEDDING_DIM={live_dim} (and the matching "
                f"PGRG_EMBEDDING_MODEL). See "
                f"docs/superpowers/specs/2026-05-26-online-embedding-migration-design.md."
            )
```

Note: `conn.execute(...).fetchone()` returns a tuple by default here (the pool is
not opened with `dict_row`), so index `row[0]`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py::test_connect_raises_on_dim_mismatch -v`
Expected: PASS.

- [ ] **Step 5: Run the full integration file to confirm no regression in the guard path**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py -v`
Expected: all PASS. (Earlier tests reconnect at the bootstrap dim, so the guard is satisfied.)

- [ ] **Step 6: Commit**

```bash
git add src/pg_raggraph/db.py tests/integration/test_embedding_migration.py
git commit -m "feat: guard connect() against embedding_dim/schema mismatch"
```

---

## Task 11: CLI `migrate-embeddings` group

**Files:**
- Modify: `src/pg_raggraph/cli.py`
- Test: `tests/unit/test_cli_migrate_embeddings.py` (create)

- [ ] **Step 1: Write a failing test for command registration**

Create `tests/unit/test_cli_migrate_embeddings.py`:

```python
from click.testing import CliRunner
from pg_raggraph.cli import cli


def test_migrate_embeddings_group_registered():
    runner = CliRunner()
    result = runner.invoke(cli, ["migrate-embeddings", "--help"])
    assert result.exit_code == 0
    for sub in ("prepare", "backfill", "build-index", "status", "cutover", "finalize"):
        assert sub in result.output
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_cli_migrate_embeddings.py -v`
Expected: FAIL (group not found; non-zero exit).

- [ ] **Step 3: Implement the CLI group**

In `src/pg_raggraph/cli.py`, add (following the existing `_run`, `@click.pass_context`,
`GraphRAG(**ctx.obj["kwargs"])` patterns near the other commands):

```python
@cli.group("migrate-embeddings")
def migrate_embeddings():
    """Online embedding-model migration (expand/contract column swap)."""


@migrate_embeddings.command("prepare")
@click.option("--model", "model", required=True, help="New embedding model name")
@click.option("--dim", "dim", type=int, required=True, help="New embedding dimension")
@click.option(
    "--backfill-source",
    type=click.Choice(["reembed", "chunkshop_sink"]),
    default="reembed",
)
@click.pass_context
def _me_prepare(ctx, model, dim, backfill_source):
    """Add embedding_tmp columns and record migration state."""
    from pg_raggraph import embedding_migration as em

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        try:
            await em.prepare(
                rag._db, target_model=model, target_dim=dim,
                backfill_source=backfill_source,
            )
            click.echo(f"prepared migration to {model} (dim {dim})")
        finally:
            await rag.close()

    _run(_go())


@migrate_embeddings.command("backfill")
@click.option("--batch-size", type=int, default=256)
@click.pass_context
def _me_backfill(ctx, batch_size):
    """Re-embed all rows into embedding_tmp with the new model (resumable)."""
    from pg_raggraph import embedding_migration as em

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        try:
            n = await em.backfill(rag._db, rag._get_embedder(), batch_size=batch_size)
            click.echo(f"backfilled {n} rows")
        finally:
            await rag.close()

    _run(_go())


@migrate_embeddings.command("build-index")
@click.pass_context
def _me_build_index(ctx):
    """Build HNSW indexes on embedding_tmp (CONCURRENTLY)."""
    from pg_raggraph import embedding_migration as em

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        try:
            await em.build_index(
                rag._db,
                hnsw_m=rag.config.hnsw_m,
                hnsw_ef_construction=rag.config.hnsw_ef_construction,
            )
            click.echo("built embedding_tmp HNSW indexes")
        finally:
            await rag.close()

    _run(_go())


@migrate_embeddings.command("status")
@click.pass_context
def _me_status(ctx):
    """Show migration phase, remaining rows, and index presence."""
    import json

    from pg_raggraph import embedding_migration as em

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        try:
            click.echo(json.dumps(await em.status(rag._db), indent=2, default=str))
        finally:
            await rag.close()

    _run(_go())


@migrate_embeddings.command("cutover")
@click.pass_context
def _me_cutover(ctx):
    """Swap embedding_tmp into place as the live embedding column."""
    from pg_raggraph import embedding_migration as em

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        try:
            await em.cutover(rag._db)
            click.echo(
                "cutover complete. Restart the app with the new "
                "PGRG_EMBEDDING_DIM and PGRG_EMBEDDING_MODEL."
            )
        finally:
            await rag.close()

    _run(_go())


@migrate_embeddings.command("finalize")
@click.pass_context
def _me_finalize(ctx):
    """Drop the preserved embedding_old columns and clear migration state."""
    from pg_raggraph import embedding_migration as em

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        try:
            await em.finalize(rag._db)
            click.echo("finalized; embedding_old dropped")
        finally:
            await rag.close()

    _run(_go())
```

Note: `cutover` here calls `rag.connect()` first, which runs the dim-guard. Because
cutover runs *while the app config still names the old dim* but the live column is
still the old dim at that point (the swap happens inside `em.cutover`), the guard
passes. The mismatch only exists *after* cutover, on the next startup — which is
exactly what the guard is meant to catch.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_cli_migrate_embeddings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/cli.py tests/unit/test_cli_migrate_embeddings.py
git commit -m "feat: add migrate-embeddings CLI group"
```

---

## Task 12: `chunkshop_sink` backfill source

**Files:**
- Modify: `src/pg_raggraph/embedding_migration.py`
- Test: `tests/integration/test_embedding_migration.py`

This adds the Pattern-C backfill path: chunk vectors come from a re-embedded
chunkshop sink table (matched by stored `chunkshop_doc_id`/`chunkshop_seq_num`),
while entities still re-embed locally (chunkshop has no entity graph).

- [ ] **Step 1: Write a failing test**

Add to `tests/integration/test_embedding_migration.py`:

```python
@pytest.mark.asyncio
async def test_backfill_from_chunkshop_sink_matches_by_metadata():
    rag = await _fresh_rag(4, StubEmbedder(4))
    try:
        # ingest a pre_chunked record carrying chunkshop metadata
        await rag.ingest_records([
            {
                "text": "alpha",
                "source_id": "chunkshop:docX",
                "metadata": {"source": "chunkshop", "chunkshop_doc_id": "docX"},
                "pre_chunked": [{
                    "content": "alpha",
                    "embedding": [1.0, 1.0, 1.0, 1.0],
                    "metadata": {"chunkshop_doc_id": "docX", "chunkshop_seq_num": 0},
                }],
            }
        ])
        await em.prepare(
            rag._db, target_model="stub-6", target_dim=6,
            backfill_source="chunkshop_sink",
        )
        # sink rows: doc_id/seq_num -> 6-dim precomputed vectors
        sink_rows = [{
            "chunkshop_doc_id": "docX",
            "chunkshop_seq_num": 0,
            "embedding": [9.0] * 6,
        }]
        n = await em.backfill_from_sink(
            rag._db, sink_rows, entity_embedder=StubEmbedder(6)
        )
        assert n >= 1
        assert await em._remaining_null(rag._db, "chunks") == 0
        row = await rag._db.fetch_one(
            "SELECT vector_dims(embedding_tmp) AS d FROM chunks "
            "WHERE embedding_tmp IS NOT NULL LIMIT 1"
        )
        assert row["d"] == 6
    finally:
        await rag.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py::test_backfill_from_chunkshop_sink_matches_by_metadata -v`
Expected: FAIL with `AttributeError: ... 'backfill_from_sink'`.

- [ ] **Step 3: Implement `backfill_from_sink`**

Append to `src/pg_raggraph/embedding_migration.py`:

```python
async def backfill_from_sink(db, sink_rows, *, entity_embedder) -> int:
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

    # entities have no chunkshop counterpart — re-embed them locally
    total += await _backfill_table(db, entity_embedder, "entities", batch_size=256)

    await db.execute(
        "UPDATE embedding_migration SET phase='backfilled', updated_at=now() "
        "WHERE id IS TRUE"
    )
    return total
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_embedding_migration.py::test_backfill_from_chunkshop_sink_matches_by_metadata -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/embedding_migration.py tests/integration/test_embedding_migration.py
git commit -m "feat: add chunkshop_sink backfill source to embedding migration"
```

---

## Task 13: Full-suite regression + lint

**Files:** none (verification only)

- [ ] **Step 1: Lint the new/changed code**

Run: `uv run ruff check src/pg_raggraph/embedding_migration.py src/pg_raggraph/cli.py src/pg_raggraph/db.py tests/unit/test_embedding_migration.py tests/unit/test_cli_migrate_embeddings.py tests/integration/test_embedding_migration.py`
Expected: `All checks passed!`

- [ ] **Step 2: Run unit suite**

Run: `uv run pytest tests/unit -q`
Expected: all pass (prior 340 + new tests).

- [ ] **Step 3: Run integration suite on the clean DB**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration -q`
Expected: all pass (prior 174 passed / 17 skipped + the new migration file).

- [ ] **Step 4: Commit (only if lint/format produced changes)**

```bash
git add -A
git commit -m "chore: lint pass for embedding migration feature"
```

---

## Self-Review Notes

- **Spec coverage:** prepare/backfill/build-index/status/cutover/finalize → Tasks 3–8; startup dim-guard → Task 10; CLI → Task 11; chunkshop_sink source → Task 12; cache retype + pgrg_meta update → Task 7; both `chunks` and `entities` migrated together → `TABLES` constant used in every phase.
- **No per-namespace logic** — matches the database-wide non-goal in the spec.
- **TDD throughout** — every behavior task writes a failing test first.
- **Index names** consistent across tasks: `idx_chunk_embed`/`idx_entity_embed` (live), `idx_chunk_embed_tmp`/`idx_entity_embed_tmp` (tmp), defined once in `_LIVE_INDEX`/`_TMP_INDEX`.
- **Function signatures** consistent: `prepare`, `backfill(db, embedder, *, batch_size)`, `build_index(db, *, hnsw_m, hnsw_ef_construction)`, `status`, `cutover`, `finalize`, `backfill_from_sink(db, sink_rows, *, entity_embedder)` are used identically in tests, CLI, and implementation.
