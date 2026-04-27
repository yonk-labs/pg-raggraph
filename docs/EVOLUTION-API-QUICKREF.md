# Tier 1 evolving-knowledge API — quick reference

This page collects the small set of API surfaces where natural intuition
disagrees with what `pg-raggraph` actually does, based on real
plan-vs-reality drift seen during the Path A + Path B real-corpus
benchmarks (2026-04-27). Read this before writing a plan that touches
Tier 1.

## Things people commonly try (wrong) vs. what actually works

### 1. Wipe a namespace before re-ingest

| ✗ Common attempt | ✓ Actual API |
|---|---|
| `await rag.delete_namespace(ns)` | `await rag.delete(ns)` |

`delete_namespace` does not exist. `rag.delete(ns)` is the public
primitive. Or skip the wipe entirely — `(namespace, content_hash)` is
UNIQUE on `documents`, so re-runs are idempotent.

### 2. Read `version_label` from query results

| ✗ Common attempt | ✓ Actual API |
|---|---|
| `documents.metadata->>'version_label'` | `documents.version_label` |

`version_label` is a real column on `documents`, indexed for fast
filtering. Same applies to `effective_from`, `effective_to`, and
`retracted` — all are dedicated columns, not JSONB.

The ingest API still accepts them via the `metadata` dict — pgrg
*promotes* them to columns at upsert time. The asymmetry is intentional
(metadata is a generous-input contract; the schema is strict) but
trips most readers up.

```python
# Ingest: pass through metadata dict (auto-promoted to columns)
await rag.ingest(
    [path], namespace="x",
    metadata={"version_label": "Python 3.12", "effective_from": dt},
)

# Query: read from the column directly
row = await rag.db.fetch_one(
    "SELECT d.version_label FROM chunks c "
    "JOIN documents d ON c.document_id = d.id WHERE c.id = %s",
    (chunk_id,),
)
```

### 3. Toggle retraction-hide per query

| ✗ Common attempt | ✓ Actual API |
|---|---|
| `await rag.query(q, retracted_behavior="hide")` | `rag.config.retracted_behavior = "hide"` |

`retracted_behavior` is **config-only**, not a per-call query kwarg.
Mutate `rag.config.retracted_behavior` before the query and restore
after. Same for `supersession_behavior`. The pydantic-settings model
is non-frozen, so direct mutation is fine.

```python
# Per-query toggle pattern
old = rag.config.retracted_behavior
rag.config.retracted_behavior = "hide"
try:
    result = await rag.query(q)
finally:
    rag.config.retracted_behavior = old
```

The kwargs that *are* per-query on `rag.query()`: `mode`, `namespace`,
`as_of`, `version_filter`, `evolution_aware`. That's the whole list.

### 4. Override top-K per query

| ✗ Common attempt | ✓ Actual API |
|---|---|
| `await rag.query(q, top_k=20)` | `rag.config.top_k = 20` |

`top_k` is config-only. Default is 10. Toggle via config like
`retracted_behavior`.

### 5. Read DB rows from `rag.db`

| ✗ Common attempt | ✓ Actual API |
|---|---|
| `async with rag.db.acquire() as conn: rows = await conn.fetch("...", arg1)` | `rows = await rag.db.fetch_all("...", (arg1,))` |

`Database` (the `rag.db` object) wraps psycopg, not asyncpg. API:

- `await rag.db.execute(sql, params)`
- `await rag.db.fetch_one(sql, params) -> dict | None`
- `await rag.db.fetch_all(sql, params) -> list[dict]`

Placeholders are `%s` (psycopg-style), parameters are passed as
**tuples**. No `.acquire()` context manager; no `$1` placeholders.

### 6. Resolve a chunk to its document

| ✗ Common attempt | ✓ Actual API |
|---|---|
| `result.chunks[0].id` | `result.chunks[0].chunk_id` |

`QueryResult.chunks` is `list[ChunkResult]`, not `list[Chunk]`.
`ChunkResult.chunk_id` is the DB primary key on `chunks` — use it for
joins and provenance lookups. There's no `.id` attribute.

### 7. `as_of` and `retracted_at` interaction

| ✗ Common assumption | ✓ Actual semantics |
|---|---|
| `as_of` "undoes" retraction tagging — papers retracted *after* `as_of` are treated as non-retracted | `as_of` filters on `effective_from`/`effective_to`. `retracted_at` is **not** compared against `as_of`. |

If a document has `retracted=true`, the retraction filter (active under
`retracted_behavior="hide"`) excludes it regardless of `as_of`.

To get pre-retraction-era results, **leave `retracted_behavior="flag"`**
(the default) and use `as_of` to bound the time window. Retracted
papers will surface alongside non-retracted ones, and the caller can
filter on `result.chunks[*].is_retracted` if they want richer
flag-based UX.

The Path B runner uses both: retraction-aware questions toggle
`retracted_behavior="hide"`; time-travel questions leave it on `"flag"`
and pass `as_of=...`.

## See also

- [`docs/cookbook/evolution-tracking.md`](cookbook/evolution-tracking.md) —
  the canonical Tier 1 quickstart
- [`docs/USE-CASES.md`](USE-CASES.md) — when to reach for evolving-knowledge
  vs classic GraphRAG
- [`docs/blog/03-path-b-medical-retractions.md`](blog/03-path-b-medical-retractions.md) —
  worked example of `retracted_behavior` + `as_of` semantics on real
  PubMed literature
- [`benchmarks/python-versioned-docs/run_path_a.py`](../benchmarks/python-versioned-docs/run_path_a.py) and
  [`benchmarks/medical-hrt/run_path_b.py`](../benchmarks/medical-hrt/run_path_b.py) —
  real runners using all the patterns above
