# Changing the embedding model / dimension on a live database

pg-raggraph stores embeddings in pgvector columns declared `vector({dim})`, where
`{dim}` is fixed at first schema bootstrap from `PGRGConfig.embedding_dim`. Changing
the embedding model usually changes the vector dimension (e.g. 384-dim
`bge-small-en-v1.5` → 768-dim `bge-base-en-v1.5`), which the existing columns can't
hold.

You do **not** need a parallel database. The `pgrg migrate-embeddings` command group
performs an online **expand/contract column swap**: add a second column, backfill it
with the new model while the app keeps serving the old one, build its index, then
swap it into place during a brief lock.

> **Design reference:** `docs/superpowers/specs/2026-05-26-online-embedding-migration-design.md`

## What it touches

The migration is **database-wide**: it moves `chunks.embedding` and
`entities.embedding` together (they share the dimension), and retypes the shared
`embedding_cache`. It is **not** per-namespace — all namespaces in the database move
at once. The query read-path is unchanged: queries always read `embedding`.

## Lifecycle

| Phase | Command | App serving? |
|---|---|---|
| Prepare | `pgrg migrate-embeddings prepare --model M --dim N` | yes (old column) |
| Backfill | `pgrg migrate-embeddings backfill` | yes |
| Build index | `pgrg migrate-embeddings build-index` | yes |
| Inspect | `pgrg migrate-embeddings status` | yes |
| Cut over | `pgrg migrate-embeddings cutover` | **brief lock** |
| Finalize | `pgrg migrate-embeddings finalize` | yes |

`prepare`, `backfill`, and `build-index` are fully online — the application keeps
answering queries against the old embeddings the whole time. Backfill is resumable
and idempotent (it only fills rows whose new column is still NULL), so you can
interrupt and re-run it.

## Procedure

```bash
# 1. Prepare: add the embedding_tmp column at the new dimension.
pgrg --db "$PGRG_DSN" migrate-embeddings prepare \
  --model BAAI/bge-base-en-v1.5 --dim 768

# 2. Backfill the new column with the new model. Resumable — re-run if interrupted.
pgrg --db "$PGRG_DSN" migrate-embeddings backfill --batch-size 256

# 3. Build the HNSW index on the new column (CONCURRENTLY — no table lock).
pgrg --db "$PGRG_DSN" migrate-embeddings build-index

# 4. Confirm readiness: remaining should be 0 for every table, indexed all true.
pgrg --db "$PGRG_DSN" migrate-embeddings status

# ---- downtime window ----
# 5. Stop the application (so no query embeds with the old model against the new column).

# 6. Swap: drop old index, rename columns, rename index, retype the cache. Sub-second.
pgrg --db "$PGRG_DSN" migrate-embeddings cutover

# 7. Restart the application with the NEW config:
#      PGRG_EMBEDDING_DIM=768
#      PGRG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
#    (Or GraphRAG(embedding_dim=768, embedding_model="BAAI/bge-base-en-v1.5").)
#    A startup guard refuses to connect if the config dim != the live column dim,
#    so a forgotten env var fails fast with a clear message instead of an opaque
#    pgvector runtime error.
# ---- end downtime window ----

# 8. After validating query quality on the new model, drop the old column.
pgrg --db "$PGRG_DSN" migrate-embeddings finalize
```

## Backfill sources

`prepare --backfill-source` selects where the new vectors come from:

- **`reembed`** (default) — re-embed the stored chunk text (`embedded_content`) and
  entity text (`name` + `description`) with the new model via the configured
  embedding provider. Fully self-contained; needs no source documents.
- **`chunkshop_sink`** — for [Pattern C](chunkshop-integration.md) deployments where
  chunkshop re-embeds its sink table upstream. Chunk vectors are re-imported from the
  re-embedded sink (matched on the stored `chunkshop_doc_id` / `chunkshop_seq_num`
  metadata); entities still re-embed locally, because chunkshop has no entity graph.
  Use the `pg_raggraph.embedding_migration.backfill_from_sink(...)` helper for this
  path.

## Safety and rollback

- **Atomic cutover.** All cutover DDL runs in one transaction; on any error it rolls
  back, leaving the live `embedding` column and its index intact. Just re-run.
- **Refusal guards.** `cutover` refuses unless every table is fully backfilled *and*
  the new index is built — it will not promote a half-empty column. `status` shows
  the remaining counts so you can confirm readiness.
- **Rollback escape hatch.** Cutover renames the old column to `embedding_old` rather
  than dropping it. Validate query quality on the new model first; `finalize` (a
  separate, explicit step) drops `embedding_old` only when you're satisfied. Until
  then the old vectors are still on disk.
- **Cache.** The shared `embedding_cache` is truncated and retyped to the new
  dimension at cutover; it repopulates from traffic.

> **Operational note:** the readiness guards in `cutover` are checked just before the
> swap. Ingesting new documents *between* `build-index` and `cutover` adds rows with a
> NULL new column, which `cutover` will (correctly) refuse on. Run `backfill` once more
> to fill them, or pause ingestion during the cutover window.

## Why not just `ALTER COLUMN TYPE`?

You can't cast existing `vector(384)` data to `vector(768)` — the numbers are from a
different model. Any dimension change requires re-embedding the corpus. The
expand/contract swap is how you do that re-embed online, with a sub-second cutover,
instead of taking the database offline for the whole backfill.
