# Auto-creating metadata indexes (Scope B)

> **Status:** new in [PR #17](https://github.com/yonk-labs/pg-raggraph/pull/17). Companion to `retrieval_strategy` ([PR #11](https://github.com/yonk-labs/pg-raggraph/pull/11)).

`metadata_indexes` is an opt-in config field that creates btree indexes on `chunks.metadata->>'<key>'` during `connect()`. It exists so that `retrieval_strategy="pre_filter"` actually delivers on its perf promise for selective JSONB predicates — without the index, `pre_filter` is a SQL-shape no-op (the planner can't seek by an unindexed key, so it falls back to a seq scan).

## Quick start

```python
from pg_raggraph import GraphRAG

rag = GraphRAG(
    dsn="postgresql://...",
    metadata_indexes=["tier", "session_id", "tenant_id"],
)
await rag.connect()  # creates idx_chunks_metadata_{tier,session_id,tenant_id}
```

That's it. On every `connect()` the library issues:

```sql
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_tier
    ON chunks ((metadata->>'tier'));
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_session_id
    ON chunks ((metadata->>'session_id'));
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_tenant_id
    ON chunks ((metadata->>'tenant_id'));
ANALYZE chunks;
```

Idempotent — calling `connect()` twice is a no-op for already-created indexes.

## Identifier safety

Keys are validated against `^[a-zA-Z_][a-zA-Z0-9_]{0,49}$` before any SQL is composed. Anything that looks like an injection attempt, a quoted identifier, a path, or a non-ASCII shape is rejected with `ValueError` at the boundary, not silently embedded into DDL. The library uses `psycopg.sql.Identifier` for the DDL composition too — belt and suspenders.

If you need to index a JSONB key whose name isn't a plain identifier (e.g., contains dots), create the index manually with whatever name you like — pg-raggraph won't touch indexes it didn't create.

## When the index actually helps

Postgres's planner decides to use the metadata index based on cost estimates, not on the index's existence. The win depends on data shape:

| Workload | Does the planner pick the index? |
|---|---|
| Many docs per namespace, selective metadata predicate (1% match) | **Yes — dramatic win** (see bench below). The planner's bitmap-merge of `idx_doc_ns` × `idx_chunks_metadata_<key>` beats a doc-driven seq scan. |
| One doc with many chunks per namespace | Usually no. The namespace+doc filter already narrows to 1 doc row, so the planner picks `idx_chunk_doc` and applies the metadata predicate post-scan. Adding `ANALYZE chunks` + bumping `STATISTICS TARGET` for the metadata column sometimes flips this. |
| Standalone metadata predicate, no namespace filter | **Yes — always**. The metadata index is the only seek option. |
| Predicate is broad (>10% selective) | Usually no. Post-scan filter is cheap when most rows pass; bitmap merge isn't worth the overhead. |

## Bench (2026-05-20, 100K chunks, Postgres 16)

Same fixture as the [retrieval-strategy bench](retrieval-strategy.md#bench-at-100k-chunks-2026-05-20). 100 chunks tagged `selective_tag=rare` (0.1% selectivity).

| Query shape | No metadata index | With `metadata_indexes=["selective_tag"]` |
|---|---|---|
| Pure metadata predicate (no namespace JOIN) | p50 ~50 ms (seq scan) | **p50 0.04 ms** (Index Scan on idx_chunks_metadata_selective_tag) — **1250× faster** |
| `pre_filter` with namespace JOIN (this bench: 1 doc × 100K chunks) | p50 77 ms | p50 54 ms — planner still prefers `idx_chunk_doc`; modest 30% gain from improved stats |

EXPLAIN output for the standalone case after `metadata_indexes` is applied:

```
Index Scan using idx_chunks_metadata_selective_tag on chunks c
  Index Cond: ((metadata ->> 'selective_tag'::text) = 'rare'::text)
Execution Time: 0.040 ms
```

EXPLAIN output for the namespace-JOIN case (same bench, index present):

```
Nested Loop
  ->  Index Scan using idx_doc_ns on documents d        (1 row)
  ->  Index Scan using idx_chunk_doc on chunks c        (100K rows)
        Filter: ((metadata ->> 'selective_tag') = 'rare')
        Rows Removed by Filter: 99900
Execution Time: 53.2 ms
```

**Honest read:** the index works as designed, but the planner's cost model on this particular bench shape (one document for all chunks) makes `idx_chunk_doc` look cheap enough that it wins. Real workloads with tens or hundreds of documents per namespace will see the planner switch — see the realistic-shape bench below.

## Realistic-shape bench (10K docs × 10 chunks, 2026-05-20)

Same 0.1% predicate selectivity, but with the chunks spread across **10,000 documents** (10 chunks each) instead of all under one doc. This is closer to typical GraphRAG corpora (each ingested file becomes a document, each document chunks down to 5-50 chunks).

| Setup | p50 | p95 | Plan |
|---|---|---|---|
| No metadata index | **1.29 ms** | 2.37 ms | HNSW (`idx_chunk_embed`) + post-filter |
| With `metadata_indexes=["selective_tag"]` | **0.10 ms** | 0.21 ms | Index Scan on `idx_chunks_metadata_selective_tag` |

**Two findings that flip the degenerate-bench story:**

1. **The baseline is dramatically faster in realistic shape** (1.29 ms vs 77 ms in the 1-doc bench). When no single document dominates the namespace, the planner picks HNSW + post-filter inside the `pre_filter` CTE — the SQL shape itself buys a 60× win even without a metadata index.
2. **The metadata index still helps** — 12-13× faster than the no-index baseline (0.10 ms vs 1.29 ms). Real workloads see BOTH wins compound: HNSW for vector ranking, metadata-index for predicate seek.

EXPLAIN ANALYZE confirms `idx_chunks_metadata_selective_tag` is the seed scan; the docs table joins via PK lookup at near-zero cost.

The earlier "modest 30% gain" caveat applies only when the namespace + document filter is already near-singleton (the degenerate bench). For typical GraphRAG ingest shapes, expect the realistic numbers.

If EXPLAIN still says the index isn't being picked, the usual fixes are:

1. **`ANALYZE chunks`** after bulk ingest so stats reflect the current metadata distribution.
2. **Bump statistics target** for the JSONB column: `ALTER TABLE chunks ALTER COLUMN metadata SET STATISTICS 1000;` then `ANALYZE chunks`.
3. **Add a partial index** for the most selective values: `CREATE INDEX ... WHERE metadata->>'tier' = 'consolidated'`.
4. **Bigger hammer**: split the metadata key into a generated column. Index a real column, not a JSONB expression. Pg-raggraph doesn't auto-do this; design call per column.

## Realistic-shape bench update (2026-05-20)

The headline "1250×" number above is from a **degenerate** bench (1 document × 100K chunks). For a more realistic GraphRAG shape (10K documents × 10 chunks each, same 0.1% predicate selectivity):

| Setup | p50 | Plan |
|---|---|---|
| No metadata index | **1.29 ms** | HNSW (`idx_chunk_embed`) + post-filter |
| With `metadata_indexes=["selective_tag"]` | **0.10 ms** | Index Scan on `idx_chunks_metadata_selective_tag` |

**Two findings:**

1. **The baseline is dramatically faster in realistic shape** (1.29 ms vs 77 ms in the degenerate case) because the planner picks HNSW + post-filter when no single document dominates the namespace. The pre_filter SQL shape itself helps here, even without a metadata index — the CTE materialization gives the planner room to choose HNSW.
2. **The metadata index still helps** — 12-13× faster than the no-index baseline. Real workloads see both wins.

The earlier "modest 30% gain" from the degenerate bench was a worst case; realistic data shapes get the bigger speedup AND a faster baseline.

## Typed generated columns (numeric / timestamp / boolean predicates)

The btree indexes above only help equality on text-extracted JSONB. Range and order queries on numeric or timestamp metadata require **typed** columns. pg-raggraph exposes this as a third opt-in:

```python
rag = GraphRAG(
    dsn=...,
    metadata_generated_columns={
        "priority": "int",
        "created_at": "timestamptz",
        "is_premium": "boolean",
    },
)
await rag.connect()
```

Per entry, connect() issues:

```sql
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS meta_priority integer
    GENERATED ALWAYS AS ((metadata->>'priority')::integer) STORED;
CREATE INDEX IF NOT EXISTS idx_chunks_meta_priority ON chunks(meta_priority);
```

After that, query against `meta_priority` instead of `metadata->>'priority'`:

```sql
-- Wrong (lexical): '10' < '5'
SELECT * FROM chunks WHERE (metadata->>'priority')::int > 5;  -- works but no index

-- Right (typed + indexed):
SELECT * FROM chunks WHERE meta_priority > 5;  -- uses idx_chunks_meta_priority
```

**Allowed types:** `text`, `int` / `integer`, `bigint`, `numeric`, `timestamptz`, `boolean` / `bool`. Anything outside that set rejects at `connect()` with `ValueError` — no surprise casts.

**Cast failure on existing rows.** STORED generated columns compute the cast on every INSERT/UPDATE. If you add `"priority": "int"` and an existing row has `metadata.priority = "high"`, the ALTER fails. The library logs WARNING and moves on — operator must clean the data, then reconnect.

**Type changes require manual DROP.** `ADD COLUMN IF NOT EXISTS` skips when the column already exists — even if the existing column has a different type. To change `priority` from `int` to `bigint`, run `ALTER TABLE chunks DROP COLUMN meta_priority;` manually first, then update the config.

**Index naming.** The generated column is `meta_<key>` (distinct namespace from `chunks.metadata`). The index is `idx_chunks_meta_<key>`. A key can have BOTH `metadata_indexes=["priority"]` AND `metadata_generated_columns={"priority": "int"}` — they don't collide and serve different predicate shapes (text equality vs numeric range).

### Nested JSON paths / lede reports

Generated columns can also be calculated from nested JSON paths. This is the
recommended shape for lede v0.4.5 report JSON: store the full machine payload
under `metadata.lede_report`, then promote hot paths into typed columns.

```python
rag = GraphRAG(
    dsn=...,
    document_metadata_generated_columns={
        "term": {
            "type": "text",
            "path": ["lede_report", "attributes", "term", "value"],
        },
        "docket_number": {
            "type": "text",
            "path": ["lede_report", "attributes", "docket_number", "value"],
        },
        "decision_year": {
            "type": "int",
            "path": ["lede_report", "attributes", "decision_year", "value"],
        },
    },
)
await rag.connect()
```

This creates columns such as `documents.meta_term` and
`documents.meta_docket_number`, each backed by a btree index. Use the full JSON
payload for audit and recall enrichment, but use the generated columns for
deterministic filters like term, docket number, citation, year, customer, or
case metadata.

## Indexing documents.metadata (Option A — config-driven)

For deployments that want config-driven indexes on `documents.metadata` (e.g., the sales-notes case where `salesperson`, `product`, `date` land on `documents.metadata`, not `chunks.metadata`), three parallel config fields mirror the chunks-side knobs:

```python
rag = GraphRAG(
    dsn=...,
    # Chunks-side (mechanical fields the chunker writes)
    metadata_indexes=["tier"],
    metadata_indexes_gin=False,
    metadata_generated_columns={},
    # Documents-side (caller-supplied per-record fields)
    document_metadata_indexes=["salesperson", "product", "customer"],
    document_metadata_indexes_gin=True,
    document_metadata_generated_columns={
        "priority": "int",
        "created_at": "timestamptz",
    },
)
await rag.connect()
```

On every `connect()`, pg-raggraph issues:

```sql
-- chunks-side (unchanged, idempotent)
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_tier
    ON chunks ((metadata->>'tier'));

-- documents-side (new)
CREATE INDEX IF NOT EXISTS idx_documents_metadata_salesperson
    ON documents ((metadata->>'salesperson'));
CREATE INDEX IF NOT EXISTS idx_documents_metadata_product
    ON documents ((metadata->>'product'));
CREATE INDEX IF NOT EXISTS idx_documents_metadata_customer
    ON documents ((metadata->>'customer'));
CREATE INDEX IF NOT EXISTS idx_documents_metadata_gin
    ON documents USING GIN (metadata);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS meta_priority integer
    GENERATED ALWAYS AS ((metadata->>'priority')::integer) STORED;
CREATE INDEX IF NOT EXISTS idx_documents_meta_priority ON documents(meta_priority);
-- ...same for created_at
ANALYZE documents;
```

### Naming conventions

| Object | Pattern | Example |
|---|---|---|
| Btree on JSONB key | `idx_<table>_metadata_<key>` | `idx_documents_metadata_salesperson` |
| GIN on whole JSONB | `idx_<table>_metadata_gin` | `idx_documents_metadata_gin` |
| Generated column | `meta_<key>` (table-independent) | `meta_priority` |
| Btree on generated column | `idx_<table>_meta_<key>` | `idx_documents_meta_priority` |

The generated column name doesn't encode the table — the column lives on a specific table, so no cross-table collision is possible. The index names DO encode the table so chunks-side and documents-side coexist without conflict.

### When to use config fields vs runtime API

| Use config fields | Use runtime API (below) |
|---|---|
| Known-good index set baked into deployment | Exploratory — let `recommend()` tell you what's worth indexing |
| Reproducible across environments | Admin UI where a non-engineer decides |
| Schema-as-code style | Long-lived deployments where index needs evolve |
| CI / tests need a fixed schema | Multi-tenant where each tenant has different hot keys |

Both coexist: config sets the baseline at `connect()` time; runtime API tunes per workload after observing real predicates.

### Bench (2026-05-20, 10K docs × 10 chunks, Postgres 16)

Same fixture shape as the chunks-side realistic bench: 10,000 documents (100 tagged with `metadata.salesperson="alice"` → 1% selectivity), 10 chunks per document. HNSW present.

| Query | Without `idx_documents_metadata_salesperson` | With it |
|---|---|---|
| **Pure doc-metadata predicate** (`WHERE d.namespace=$ns AND d.metadata->>'salesperson'='alice'`) | p50 **0.75 ms** | p50 **0.15 ms** — **5× faster** |
| **`pre_filter`-shape** (vector × doc-metadata, joins to chunks for ranking) | p50 **1.98 ms** | p50 **1.11 ms** — **2× faster** |

EXPLAIN ANALYZE confirms the planner picks `Bitmap Index Scan on idx_documents_metadata_salesperson` once the index exists. Without it, the planner uses the namespace index (`idx_doc_ns`) and post-filters by `metadata->>'salesperson'` — already pretty fast (10K docs scan is cheap) but not free.

**Two findings:**

1. **The baseline is fast for documents-side predicates** even without the index, because 10K rows in a single namespace is cheap to scan. The win from the index is meaningful (2–5×) but not the 1250× drama from the standalone chunks-side bench in PR #19 — that one ran against 100K chunks in a single document, a more pathological shape.
2. **The `pre_filter` shape benefits less** than the pure-predicate shape because the vector seek dominates total latency. Both helps compound: doc-metadata index cuts the candidate set, vector compute runs over fewer chunks.

For realistic GraphRAG-from-DB workloads (sales notes, support tickets), expect the documents-side index to help by 2–5× — meaningful for tight latency budgets, less dramatic than the chunks-side case.

## Runtime API: recommend / add / remove (UI-friendly)

The config-driven knobs above (`metadata_indexes`, `metadata_indexes_gin`, `metadata_generated_columns`) apply at `connect()` and need a restart to change. For runtime use — admin UI, REPL, ops script — pg-raggraph also exposes the same DDL surface as runtime-callable methods:

```python
# Recommend: sample chunks.metadata AND documents.metadata, return ranked suggestions
recs = await rag.recommend_metadata_indexes()
for r in recs:
    print(f"{r.table}.{r.key} ({r.kind}, {r.sql_type or '-'}) — "
          f"{r.confidence} — {r.rationale}")

# Apply one — on chunks (default) or documents
await rag.add_metadata_index("salesperson", kind="btree",     table="documents")
await rag.add_metadata_index("priority",    kind="generated", sql_type="int")
await rag.add_metadata_index("",            kind="gin",       table="documents")

# Drop one
await rag.remove_metadata_index("salesperson", kind="btree", table="documents")

# List currently-installed
indexes = await rag.list_metadata_indexes()  # both tables; pass table= to scope
```

### Why two tables matter

When you ingest from a structured source (sales notes, support tickets, anything pulled from a PG table):

```python
await rag.ingest_records([
    {
        "text": "Met with Acme about Widget Pro. ...",
        "source_id": "sales_note:123",
        "metadata": {
            "salesperson": "alice", "product": "Widget Pro",
            "customer": "Acme", "date": "2026-05-20",
        },
    },
])
```

`salesperson` / `product` / `customer` / `date` land on **`documents.metadata`** (one row per record). `chunks.metadata` only gets mechanical fields (source_path, chunk_index). So `metadata_indexes=["salesperson"]` (the chunks-only config knob) **doesn't help** — it would index the wrong table.

The runtime API takes `table="documents"` so you can index where the data actually lives. `recommend()` scans BOTH tables by default and tags each suggestion with its table.

### IndexRecommendation shape

```python
@dataclass
class IndexRecommendation:
    table: Literal["chunks", "documents"]
    key: str
    kind: Literal["btree", "gin", "generated"]
    sql_type: str | None           # populated when kind == "generated"
    rationale: str                 # human-readable why
    selectivity: float             # rows_with_key / total_rows
    cardinality_ratio: float       # distinct_values / rows_with_key
    sample_size: int
    sample_values: list[str]       # first 5 distinct sampled values
    confidence: Literal["high", "medium", "low"]
    already_exists: bool           # True when an index already covers this key
```

### When to use config vs runtime

| Use config (`metadata_indexes`, ...) | Use runtime API |
|---|---|
| Known-good index set baked into deployment | Exploratory — let the DB tell you what's worth indexing |
| Reproducible across environments | Admin UI where a non-engineer decides |
| Schema-as-code style | Long-lived deployments where index needs evolve |
| CI / tests need a fixed schema | Multi-tenant where each tenant has different hot keys |

Both coexist: config sets the baseline at deploy time; runtime API tunes per workload after observing real predicates.

## Production retrofit guide

The auto-create DDL inside `connect()` is **non-CONCURRENTLY** by design — it runs inside the schema-bootstrap flow with an `ACCESS EXCLUSIVE` lock for the duration of each `CREATE INDEX`. For fresh deployments the chunks/documents tables are empty and the lock is invisible. For retrofitting an existing production database with millions of rows, you have two options.

### Option 1 (recommended) — `rag.apply_metadata_indexes_concurrently()`

Pg-raggraph exposes a maintenance helper that reads the same config fields and issues `CREATE INDEX CONCURRENTLY` from a fresh autocommit connection (outside the pool's transaction context):

```python
# In a maintenance shell or one-off job — NOT during application startup.
from pg_raggraph import GraphRAG

rag = GraphRAG(
    dsn="postgresql://prod/...",
    # The config the running app will eventually use:
    metadata_indexes=["tier", "session_id"],
    document_metadata_indexes=["salesperson", "product", "customer"],
    metadata_indexes_gin=True,
    document_metadata_indexes_gin=True,
)
await rag.connect()   # connect() is a no-op for config keys whose
                      # indexes don't exist yet — won't fire the
                      # non-concurrent path because the connect() helpers
                      # only see the current config; if you've already
                      # deployed the new config, just call this method
                      # *before* the app restart.
results = await rag.apply_metadata_indexes_concurrently()
for r in results:
    print(r)
await rag.close()
```

Each result is a dict: `{"ok": bool, "table": ..., "kind": ..., "key": ..., "object_name": ..., "error": ...}`. Mirrors the runtime API shape. Writes continue to flow throughout — `CREATE INDEX CONCURRENTLY` does NOT take the `ACCESS EXCLUSIVE` lock; it does two passes and a brief metadata lock at the end.

After the helper returns, restart the app normally. `connect()`'s `IF NOT EXISTS` finds each index already present and the loop is a no-op.

**What this method does NOT support:**

- **Generated columns** — Postgres has no concurrent `ALTER TABLE ADD COLUMN` variant. The helper reports each generated-column entry with `ok=False` so the operator sees what was skipped. Add those during a real maintenance window, or use the manual recipe below.

### Option 2 — manual `CREATE INDEX CONCURRENTLY` via psql

If you'd rather drive the retrofit yourself (e.g., from a DBA-controlled migration tool), the underlying SQL is straightforward:

```bash
psql $PGRG_DSN <<SQL
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_documents_metadata_salesperson
    ON documents ((metadata->>'salesperson'));
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_documents_metadata_gin
    ON documents USING GIN (metadata);
ANALYZE documents;
SQL
```

Then add `"salesperson"` to `document_metadata_indexes` (and/or set `document_metadata_indexes_gin=True`) in your config. On the next app restart, pg-raggraph's `IF NOT EXISTS` finds the existing indexes.

### CONCURRENTLY caveats (either option)

- A CONCURRENTLY index that **fails midway** leaves an INVALID index in `pg_index`. Monitor for them with `SELECT relname FROM pg_class JOIN pg_index ON indexrelid = pg_class.oid WHERE NOT indisvalid;` and DROP + retry.
- CONCURRENTLY is **roughly 2× slower** than the non-concurrent variant (two table scans instead of one) but doesn't block writes — the right tradeoff for live tables.
- The helper opens a **separate connection per index** (autocommit, outside the pool) because CONCURRENTLY can't run in a transaction.

## GIN on full `chunks.metadata` (ad-hoc JSONB predicates)

The per-key btree indexes above are great for `metadata->>'key' = 'value'` equality. For ad-hoc JSONB predicates — **containment** (`@>`), **key existence** (`?`), **multi-key match** (`?|`, `?&`) — you need a GIN index instead. pg-raggraph exposes this as a single bool flag:

```python
rag = GraphRAG(
    dsn=...,
    metadata_indexes_gin=True,  # creates idx_chunks_metadata_gin
)
await rag.connect()
```

Produces:

```sql
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_gin
    ON chunks USING GIN (metadata);
```

Uses the default `jsonb_ops` operator class — supports all the common JSONB query operators. The alternative `jsonb_path_ops` is smaller but only supports `@>`; we err on the side of flexibility since the config is one knob.

**When to enable GIN:**

| Predicate shape | Indexed by | Notes |
|---|---|---|
| `metadata->>'tier' = 'consolidated'` | btree (`metadata_indexes=["tier"]`) | Per-key, optimized for equality |
| `metadata @> '{"tag":"x"}'` | **GIN** (`metadata_indexes_gin=True`) | Containment — no btree alternative |
| `metadata ? 'priority'` | **GIN** | Key existence |
| `metadata ?| ARRAY['a','b']` | **GIN** | Multi-key match |
| `metadata->>'priority' > '5'` | btree (lexical) | Numeric range needs generated column (see "What this is NOT" below) |

**Cost:** GIN is roughly 2-4× the bytes per indexed row vs btree, and writes are slower (the fast-update path mitigates this for bulk ingest but it's not free). Only enable when you actually have the predicate shapes — the per-key btree from `metadata_indexes` is cheaper for the equality case.

**btree + GIN coexist fine.** Having `metadata_indexes=["tier", "session_id"]` AND `metadata_indexes_gin=True` is a valid combo: the btree wins for hot equality lookups, the GIN catches the long tail of ad-hoc containment queries.

## What this is NOT

- **Btree alone doesn't cover GIN's ground.** This is btree on a single extracted key, optimized for equality. Range queries (`metadata->>'priority' > '5'`) work but won't be as fast as a typed column.
- **Not type-aware.** `metadata->>` always returns text. If you store numbers, equality still works (`'5' = '5'`) but `<` / `>` compare lexicographically (`'10' < '5'`). For real numeric ranges, generated columns are the right answer.
- **Not an auto-dropper.** If you remove a key from `metadata_indexes`, the index stays. That's intentional — destructive ops should be explicit. Run `DROP INDEX idx_chunks_metadata_<key>` manually if you want to remove one.

## Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `ValueError: metadata_indexes key 'foo-bar' is not a valid identifier` | Key fails the regex (hyphen, dot, space, etc.) | Use snake_case identifiers; for unusual keys, create the index manually |
| WARNING log: `Failed to create metadata index idx_chunks_metadata_X` | Index DDL raised (permission, name conflict, malformed expression) | Retrieval still works — pre_filter just won't be faster on this key. Inspect the warning message; the most common cause is insufficient role grants. |
| Index exists but EXPLAIN doesn't use it | Planner cost estimate disagrees | Run `ANALYZE chunks`. Check selectivity with `SELECT metadata->>'key', COUNT(*) FROM chunks GROUP BY 1 LIMIT 20;`. If selectivity is >10% the planner may correctly avoid the index. |
| Migration system thinks something changed | `metadata_indexes` is NOT part of the migration system | These are runtime-config-driven, not schema-versioned. Same set of keys across deploys = idempotent; different sets is operator's responsibility. |
