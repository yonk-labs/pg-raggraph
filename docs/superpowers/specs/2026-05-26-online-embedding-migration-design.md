# Design — Online Embedding-Model Migration (2026-05-26)

> **Status:** Approved design, pre-implementation. Next step: writing-plans.
> **Scope:** A single, self-contained feature slice in pg-raggraph. Independent of the
> other Chunkshop-integration workstreams (live e2e fixture, code-graph query UX,
> operator docs). The operator guide will document *this* feature once built.

---

## Problem

pg-raggraph stores embeddings in pgvector columns declared `vector({dim})`, where
`{dim}` is baked into the schema at first bootstrap from `PGRGConfig.embedding_dim`.
Today, changing the embedding model (and therefore the vector dimension) means
creating a fresh database and re-ingesting the whole corpus. There is no in-place
path to move a live deployment from, say, 384-dim `bge-small` to 768-dim `bge-base`.

The prior handover claimed dimensions were "effectively immutable after bootstrap."
That is rejected. A column is cheap — "nothing but space" prevents us from having a
second one. We can migrate online using the classic **expand/contract column swap**.

## Goals

- Move an existing pg-raggraph database to a new embedding model / dimension without
  a parallel database and without losing the graph (entities, relationships, facts).
- Keep the app serving from the old embeddings during the long backfill.
- Confine downtime to a brief, deliberate cutover window.
- Keep the retrieval read-path **untouched** — queries always read `c.embedding`.

## Non-goals

- Per-namespace independent migration. The swap is **database-wide** by nature: a
  column has one type. All namespaces move together.
- Zero-downtime cutover. There is a brief `ACCESS EXCLUSIVE` lock window (sub-second,
  catalog-only renames). The app is expected to be stopped and restarted around it.
- Hot-reloading the embedding model in a running process. Cutover is operator-driven:
  stop app → cutover → restart with new config.
- Making this a chunkshop primitive. The operation is about pg-raggraph's own schema
  (`chunks`/`entities` vector columns, HNSW indexes, `embedding_cache`) and the
  pg-raggraph-only entity graph. chunkshop supplies *vectors* via the
  `EmbeddingProvider` protocol or a Pattern-C sink; it does not own the migration.

## Why expand/contract (and not column-name parameterization)

The retrieval SQL hardcodes the column name `c.embedding <=> %(embedding)s::vector`
across ~10 query builders in `retrieval.py`, plus `resolution.py`. By keeping the
*live* column always named `embedding` and renaming around it, the read-path never
changes. The alternative — making the active column name a runtime parameter — would
touch every query builder and the resolution path, for no functional gain.

---

## Architecture

A new module `src/pg_raggraph/embedding_migration.py` orchestrates a six-phase,
operator-driven state machine. Migration state lives in a new singleton-row table
created by migration `010_embedding_migration.sql`:

```sql
CREATE TABLE IF NOT EXISTS embedding_migration (
    id            BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),  -- enforce single row
    target_model  TEXT NOT NULL,
    target_dim    INT  NOT NULL,
    phase         TEXT NOT NULL,        -- prepared|backfilled|indexed|cutover (row deleted at finalize)
    backfill_source TEXT NOT NULL DEFAULT 'reembed',  -- reembed|chunkshop_sink
    started_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);
```

When no migration is active, the table is empty. `prepare` inserts the row;
`finalize` deletes it.

### Phases

| Phase         | Work                                                                                                   | App serving?  |
|---------------|--------------------------------------------------------------------------------------------------------|---------------|
| `prepare`     | `ALTER TABLE chunks/entities ADD COLUMN embedding_tmp vector(target_dim)`; insert state row            | yes (old col) |
| `backfill`    | re-embed into `embedding_tmp`, batched + resumable (`WHERE embedding_tmp IS NULL`)                     | yes           |
| `build-index` | `CREATE INDEX CONCURRENTLY` HNSW on both `embedding_tmp` columns                                        | yes           |
| `status`      | report phase, remaining-NULL counts, index presence                                                    | yes           |
| `cutover`     | one txn: drop old HNSW, rename `embedding→embedding_old`, `embedding_tmp→embedding`, rename HNSW indexes, retype `embedding_cache`, update `pgrg_meta`; set phase=`cutover` | **brief lock** |
| `finalize`    | `ALTER TABLE ... DROP COLUMN embedding_old` on both tables; delete state row                            | yes           |

Each phase is a `pgrg migrate-embeddings <verb>` subcommand.

### Lock window detail

The new HNSW index is fully built (CONCURRENTLY) *before* cutover. The cutover
transaction therefore only performs catalog-only operations: `DROP INDEX` of the old
HNSW, three `RENAME`s (column, column, index), a `DELETE`/`TRUNCATE` of
`embedding_cache`. Renames do **not** rebuild indexes — pgvector/HNSW indexes track
columns by attribute number, so the index built on `embedding_tmp` stays valid after
the column is renamed to `embedding`. The `ACCESS EXCLUSIVE` window is sub-second.

---

## Components

### `embedding_migration.py`

Phase functions, each taking the `Database` connection pool:

- `prepare(db, *, target_model, target_dim, backfill_source="reembed")`
- `backfill(db, embedder, *, batch_size)`
- `build_index(db)`
- `status(db) -> dict`
- `cutover(db)`
- `finalize(db)`

Backfill reuses the existing batching shape (cf. `_embed_texts_with_cache`) but
**bypasses `embedding_cache`** — the cache is `vector({dim})` and content-hash keyed,
so an in-flight second dimension would collide. Backfill writes straight to
`embedding_tmp`.

### Backfill sources

- `reembed` (default): re-embed stored text with the new model via any configured
  `EmbeddingProvider`. Chunks use `embedded_content` (fallback `content`); entities
  use `name || ' ' || description`. Both already live in their tables — backfill is
  fully self-contained and needs no source-document re-fetch.
- `chunkshop_sink`: Pattern-C deployments where chunkshop re-embeds its sink table
  upstream. Backfill re-imports those precomputed vectors via `chunkshop_bridge`
  helpers, matching chunks by the stored `chunkshop_doc_id`/`chunkshop_seq_num`
  metadata. (Entities still re-embed locally — chunkshop has no entity graph.)

### CLI

New `migrate-embeddings` group in `cli.py` with subcommands `prepare`, `backfill`,
`build-index`, `status`, `cutover`, `finalize`. `prepare` takes
`--model`, `--dim`, `--backfill-source`; `backfill` takes `--batch-size`.

### Startup dim-guard

In `connect()` (db.py), after pool creation, compare `config.embedding_dim` against
the live `chunks.embedding` column dimension (read via `atttypmod` from
`pg_attribute`, or `information_schema`). On mismatch, raise a clear, actionable error
naming both dims and pointing at the migration docs. This catches "operator forgot to
update `PGRG_EMBEDDING_DIM` after cutover" before it becomes an opaque pgvector
runtime error.

---

## Data flow (backfill)

```
loop:
  rows = SELECT id, <text-source> FROM <table>
         WHERE embedding_tmp IS NULL
         ORDER BY id LIMIT batch_size
  if not rows: break
  vecs = embedder.embed([text for each row])        # NEW model
  UPDATE <table> SET embedding_tmp = vec WHERE id = ...
```

Run once per table (`chunks`, then `entities`). Progress is implicit in the
remaining-NULL count, so the job is resumable and idempotent — re-running only fills
what is left.

---

## Error handling & safety

- **Phase guards.** `cutover` refuses unless `build-index` has completed *and* zero
  `embedding_tmp IS NULL` rows remain across both tables — otherwise the swap would
  promote a half-empty column. `status` surfaces these counts so the operator can see
  readiness.
- **Atomic cutover.** Single transaction; on any failure it rolls back leaving the
  live `embedding` column and its index intact. Worst case: re-run cutover.
- **Rollback escape hatch.** `embedding_old` is *not* dropped at cutover. `finalize`
  is a separate, explicit step so the operator can validate query quality on the new
  model before discarding the old vectors.
- **Cache invalidation + retype.** `embedding_cache.embedding` is itself
  `vector({dim})`, so clearing rows is not enough — the column type stays the old
  dim and new-dim puts would fail. Cutover runs `TRUNCATE embedding_cache` then
  `ALTER COLUMN embedding TYPE vector(target_dim)` (safe because the table is now
  empty, and the cache has no vector index). It repopulates from traffic.
- **`pgrg_meta` consistency.** Cutover updates the `embedding_dim` row in `pgrg_meta`
  so any tooling reading it sees the new dimension.
- **Startup dim-guard** (above) prevents a config/schema mismatch from reaching query
  time.

---

## Testing

### Unit

- Phase-transition guard logic (e.g. cutover refused before backfill complete /
  before index built).
- Backfill SQL builders (correct table/column/where).
- Dimension parse from `atttypmod`.
- State-machine refusals and idempotent re-runs.

### Integration (real PostgreSQL)

Full lifecycle on a small corpus, using a **stub embedder** that emits N-dim vectors
so no model download is needed:

1. Ingest at dim 384.
2. `prepare`/`backfill`/`build-index` to a new dim N (stub embedder).
3. Assert `embedding_tmp` fully populated and HNSW index present.
4. `cutover` → assert live `embedding` column is now dim N, a query still runs end to
   end, `embedding_old` still exists.
5. `finalize` → assert `embedding_old` gone, state row gone.
6. Separate test: startup dim-guard raises on a deliberate config/schema mismatch.

---

## Operator procedure (also the basis for the docs slice)

```bash
# online, app keeps serving from old embeddings
pgrg migrate-embeddings prepare --model BAAI/bge-base-en-v1.5 --dim 768
pgrg migrate-embeddings backfill          # resumable
pgrg migrate-embeddings build-index       # CONCURRENTLY
pgrg migrate-embeddings status            # confirm 0 remaining, index present

# downtime window
#   1. stop app
pgrg migrate-embeddings cutover
#   2. set PGRG_EMBEDDING_DIM=768 ; PGRG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
#   3. start app  (startup dim-guard confirms config matches schema)

# after validating query quality on the new model
pgrg migrate-embeddings finalize          # drops embedding_old
```

---

## Out of scope (tracked separately)

- Live Chunkshop sink-table e2e fixture.
- Code-graph query UX (`code-impact`, callers/callees, path-between, evidence).
- The operator-guide doc page (depends on this feature landing first).
