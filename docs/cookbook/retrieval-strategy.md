# Picking a retrieval strategy

> **Status:** new in [PR #11](https://github.com/yonk-labs/pg-raggraph/pull/11) (stacked on [#10](https://github.com/yonk-labs/pg-raggraph/pull/10)). Applies to `naive` / `naive_boost` modes only — `local` / `global` / `hybrid` already pre-narrow via graph traversal and ignore this config.

pg-raggraph's `naive` mode now exposes three SQL-shape strategies via a single config + per-call kwarg:

```python
# Config (default is "weighted" — preserves existing behavior byte-for-byte)
PGRGConfig(retrieval_strategy="weighted")     # default
PGRGConfig(retrieval_strategy="pre_filter")
PGRGConfig(retrieval_strategy="vector_first")

# Per-call override (race-safe, multi-tenant friendly)
await rag.query(q, mode="naive", retrieval_strategy="vector_first")
await rag.ask(q, mode="naive_boost", retrieval_strategy="pre_filter")
```

## What each strategy does

```
weighted     :  SELECT ... FROM chunks JOIN documents
                 WHERE namespace=… AND predicates…
                 ORDER BY composite_score DESC LIMIT k
                 (today's behavior; may two-stage if config.two_stage_retrieval)

pre_filter   :  WITH filtered AS (
                   SELECT ... FROM chunks JOIN documents
                   WHERE namespace=… AND predicates…
                 )
                 SELECT ... FROM filtered ORDER BY composite_score DESC LIMIT k
                 (materializes filtered subset BEFORE the rank — planner-hint
                  to apply WHERE first when the optimizer wouldn't otherwise)

vector_first :  WITH candidates AS (
                   SELECT ... FROM chunks
                   ORDER BY embedding <=> $q LIMIT k * oversample_factor
                 )
                 SELECT ... FROM candidates JOIN documents
                 WHERE namespace=… AND predicates…
                 ORDER BY composite_score DESC LIMIT k
                 (HNSW-eligible — no namespace join in the seed CTE,
                  so idx_chunk_embed actually fires)
```

## Bench at 100K chunks (2026-05-20)

Same fixture as Pattern M's bench (100K chunks in one namespace, mix of metadata-tagged and untagged, Postgres 16 with HNSW present, single connection, 30-trial timings). 100 chunks were tagged `selective_tag=rare` to simulate the "Star Wars: A New Hope title match against 1M reviews" scenario.

| Strategy | No predicate | Broad (~25%): tier=consolidated | Narrow (~0.1%): rare_tag |
|---|---|---|---|
| **`weighted`** | p50 59 ms / p95 68 ms | p50 65 ms / p95 68 ms | p50 53 ms / p95 56 ms |
| **`pre_filter`** | p50 58 ms / p95 62 ms | p50 65 ms / p95 67 ms | p50 53 ms / p95 56 ms |
| **`vector_first`** | **p50 0.9 ms** / p95 2.9 ms | **p50 1.0 ms** / p95 2.6 ms | **p50 0.8 ms** / p95 2.1 ms |

**vector_first is 60–66× faster across the board.** EXPLAIN confirms why:

- weighted / pre_filter: planner picks `idx_chunk_doc` (document_id index) over HNSW because of the namespace join. Then scans all 100K chunks in the namespace, applies the predicate filter post-scan, top-N sorts. ~50–65 ms.
- vector_first: HNSW `idx_chunk_embed` Index Scan with `Order By: embedding <=> q`. ~0.8 ms. The post-filter (namespace + predicates) is cheap because the candidate set is already trimmed to `top_k × oversample_factor` rows.

## Recall caveat for vector_first (read this)

The narrow-predicate row in the bench above is **misleading on its own** — vector_first returned chunks fast, but the recall on a selective predicate is suspect. Here's why:

vector_first fetches `top_k × oversample_factor` (default 10 × 10 = 100) nearest-by-vector candidates BEFORE applying the post-filter. If your predicate matches only 0.1% of chunks (the Star Wars case), the top-100 nearest-by-vector candidates might contain **zero matching rows**, and the query returns < `top_k` results — or no results at all.

Mitigations, in increasing order of severity:

1. **Bump `retrieval_oversample_factor`** to 50 or 100 for known-selective predicates. Latency stays acceptable (HNSW is logarithmic in the limit) and recall improves.
2. **Switch to `pre_filter` for the call** when you know the predicate is selective. Slower per-query but recall guaranteed.
3. **Add an index for the predicate column** (Scope B; tracked separately). With a JSONB GIN or generated column + btree index, pre_filter becomes fast AND complete.

The default is `weighted` precisely because it's the safest middle: works regardless of predicate selectivity, no recall surprises, just slower than vector_first when HNSW would have applied.

## Decision guide

| Your query shape | Best strategy | Why |
|---|---|---|
| General-purpose, predicate selectivity unknown | `weighted` (default) | Works in all cases. No recall surprises. |
| Single-namespace, broad/no predicate, HNSW present | **`vector_first`** | Dramatic latency win (60×+). Post-filter is cheap when most candidates pass. |
| Multi-namespace, broad predicate | `weighted` or `pre_filter` | vector_first's seed pulls from all namespaces; post-filter discards most. Recall drops. |
| Selective predicate on **indexed** column (today: `namespace`; future: GIN-indexed JSONB key) | `pre_filter` | CTE materializes small filtered set → vector compute over only matching rows. |
| Selective predicate on **unindexed** JSONB | `weighted` (until Scope B lands JSONB indexing) | pre_filter buys nothing without the index; vector_first risks zero recall. |
| Multi-tenant API where different tenants want different strategies | per-call kwarg | Same race-safe pattern as `retracted_behavior` and `memory_tier`. |

## What's NOT solved by this (alone)

Selective predicates on **unindexed** JSONB columns still seq-scan, regardless of strategy. The win for `pre_filter` is conditional on having the right index. **[Scope B (PR #17)](metadata-indexes.md)** adds an opt-in `metadata_indexes: list[str]` config that auto-creates btree indexes during `connect()`:

```python
rag = GraphRAG(
    dsn=...,
    retrieval_strategy="pre_filter",
    metadata_indexes=["tier", "tenant_id", "language"],
)
```

See [`docs/cookbook/metadata-indexes.md`](metadata-indexes.md) for the full guide including bench results (1250× speedup on standalone predicates, modest gain on namespace-JOIN'd queries — read it before assuming the index will fire on your data shape), production-retrofit recipe with `CREATE INDEX CONCURRENTLY`, and planner troubleshooting.

## Backward compatibility

`retrieval_strategy="weighted"` is the default and the SQL is byte-identical to today's `_build_naive_query` / `_build_naive_query_twostage` flow. The `two_stage_retrieval` config still works (controls which weighted path is used). No existing benchmarks change.
