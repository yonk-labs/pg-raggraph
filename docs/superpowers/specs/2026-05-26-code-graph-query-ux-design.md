# Design — Code-Graph Query UX (`code-impact`) + Summary Enrichment (2026-05-26)

> **Status:** Approved design, pre-implementation. Next step: writing-plans.
> **Scope:** One focused slice — a read-side code-intelligence layer over the
> existing graph, plus FQN-matched enrichment of `CODE_SYMBOL` entity descriptions.
> No schema changes.

---

## Problem

pg-raggraph already imports chunkshop 0.6 `code_edges` into `CODE_SYMBOL` entities and
`CALLS`/`INHERITS`/`IMPLEMENTS` relationships (`chunkshop_bridge.py`). But there is no
ergonomic way to ask "who calls this symbol / what does it call / what breaks if I
change it." Users must hand-write `rag.query(mode="local")` and interpret raw results.
Separately, chunkshop's `code_summary` extractor produces a per-symbol `summary` that
reaches `chunks.metadata` but is never surfaced — `CODE_SYMBOL` entities keep the
generic description `"Code symbol {fqn}"`.

## Goals

- A `code-impact <fqn>` operation: direct callers and callees (1 hop each direction)
  with evidence, plus `--depth N` for transitive impact.
- Expose it as a reusable Python API and a CLI command.
- Enrich `CODE_SYMBOL` entity descriptions with the chunkshop `summary` when available,
  matched by FQN, at import time.

## Non-goals

- `code-path` (shortest path between two symbols) and `code-symbol` (detail view) —
  deferred; this slice is `code-impact` only.
- Cross-namespace queries. Everything is scoped to a single namespace, like the rest
  of pg-raggraph.
- Schema changes. This rides entirely on existing `entities` / `relationships` tables
  and their indexes (`idx_rel_src_type`, `idx_rel_dst_type`).
- A new retrieval mode. `code-impact` is a direct graph traversal, not part of the
  vector/hybrid retrieval path.

---

## Architecture

New module `src/pg_raggraph/code_graph.py` owns the traversal. It operates on a
`Database` pool and is namespace-scoped.

```python
from dataclasses import dataclass

CODE_REL_TYPES = ("CALLS", "INHERITS", "IMPLEMENTS")

@dataclass
class CodeEdge:
    fqn: str          # the other symbol's FQN (entities.name)
    rel_type: str     # CALLS | INHERITS | IMPLEMENTS
    evidence: str     # relationships.properties->>'evidence' snippet, or description
    depth: int        # hops from the queried symbol (1 = direct)

@dataclass
class CodeImpact:
    fqn: str
    found: bool
    callers: list[CodeEdge]   # symbols that depend on fqn (incoming edges)
    callees: list[CodeEdge]   # symbols fqn depends on (outgoing edges)

async def code_impact(
    db, fqn: str, *, namespace: str, depth: int = 1, min_confidence: float = 0.0
) -> CodeImpact: ...
```

### Resolution

```sql
SELECT id FROM entities
WHERE namespace = %s AND name = %s AND entity_type = 'CODE_SYMBOL'
```

If no row, return `CodeImpact(fqn, found=False, callers=[], callees=[])`.

### Traversal

Two recursive CTEs (one per direction), each bounded by `depth` and cycle-safe via a
visited-id path array. Callees walk `src_id → dst_id`; callers walk `dst_id → src_id`.

Callees (outgoing), shape:

```sql
WITH RECURSIVE walk AS (
    SELECT r.id, r.src_id, r.dst_id, r.rel_type,
           COALESCE(r.properties->>'evidence', r.description, '') AS evidence,
           1 AS depth, ARRAY[r.src_id] AS path
    FROM relationships r
    WHERE r.namespace = %(ns)s AND r.src_id = %(seed)s
      AND r.rel_type = ANY(%(rel_types)s) AND r.weight >= %(min_conf)s
  UNION ALL
    SELECT r.id, r.src_id, r.dst_id, r.rel_type,
           COALESCE(r.properties->>'evidence', r.description, ''),
           w.depth + 1, w.path || r.src_id
    FROM relationships r
    JOIN walk w ON r.src_id = w.dst_id
    WHERE r.namespace = %(ns)s AND w.depth < %(depth)s
      AND r.rel_type = ANY(%(rel_types)s) AND r.weight >= %(min_conf)s
      AND NOT (r.src_id = ANY(w.path))           -- cycle guard
)
SELECT e.name AS fqn, walk.rel_type, walk.evidence, walk.depth
FROM walk JOIN entities e ON e.id = walk.dst_id
ORDER BY walk.depth, e.name;
```

Callers is the mirror image (`dst_id = seed` seed, join `r.dst_id = w.src_id`, return
`e.id = walk.src_id`). `weight` carries the edge confidence (set by
`code_edges_to_known_graph`). The `evidence` column reads
`properties->>'evidence'` — note this is the JSON sub-object serialized as text; the
implementation may extract `evidence->>'snippet'` if a snippet key is present, else the
whole evidence object as text, else the description.

> **Evidence detail to resolve in the plan:** `code_edges_to_known_graph` stores
> `properties.evidence` as a JSON object (e.g. `{"snippet": "..."}`). The query should
> surface `properties->'evidence'->>'snippet'` when present, falling back to
> `properties->>'evidence'` then `description`. Pinned in the implementation plan.

---

## Surfaces

### Python API

`GraphRAG.code_impact(fqn, *, depth=1, min_confidence=0.0) -> CodeImpact` — resolves the
namespace from config (same resolution as `query`/`status`), delegates to
`code_graph.code_impact(self._db, fqn, namespace=ns, depth=depth, ...)`.

### CLI

`pgrg code-impact <fqn> [-n/--namespace NS] [--depth N] [--min-confidence F] [--json]`

- Default: human-readable tree.
- `--json`: structured output (the `CodeImpact` as a dict) for scripting, matching the
  `migrate-embeddings status` json style.

Tree rendering:

```
pkg.mod.func
  callers:
    - pkg.a.run        CALLS    "a() calls func()"
    - pkg.cli.main     CALLS    "" (depth 2)
  callees:
    - pkg.b.helper     CALLS    "func() calls helper()"
```

Empty sections render `(none)`. Not-found prints
`symbol 'pkg.mod.func' not found in namespace 'ns'` and exits non-zero (exit code 1).

---

## #1 enrichment: chunkshop `summary` → `CODE_SYMBOL` description

At import, FQN-matched, backward compatible.

- New helper in `chunkshop_bridge.py`:
  `summaries_by_fqn(records) -> dict[str, str]` — scans each record's `pre_chunked`
  chunk metadata; for chunks carrying both `fqn` and `summary`, maps `fqn → summary`.
  (chunkshop's `symbol_aware` chunker emits `metadata.fqn`; its `code_summary` extractor
  emits `metadata.summary`.)
- `code_edges_to_known_graph(rows, *, min_confidence=0.0, summaries=None)` — when
  building a `CODE_SYMBOL` entity, set `description = summaries.get(fqn) or f"Code symbol {fqn}"`.
- `attach_code_edges(records, edge_rows, *, min_confidence=0.0, summaries=None)` —
  when `summaries is None`, derive it from `records` via `summaries_by_fqn(records)`,
  then pass to `code_edges_to_known_graph`. (It already has the records.)
- `fetch_code_edges_from_table(dsn, *, schema, project_id=None, min_confidence=0.0,
  summaries=None)` — threads `summaries` to `code_edges_to_known_graph`.
- CLI `ingest-chunkshop-table` (the `--with-code-edges` branch in `cli.py`): build
  `summaries = chunkshop_bridge.summaries_by_fqn(records)` and pass it to
  `fetch_code_edges_from_table(..., summaries=summaries)`.

Defaults preserve today's behavior exactly (`summaries=None` → `"Code symbol {fqn}"`).

---

## Error handling

- Symbol not found → `found=False`; CLI prints a clear message and exits 1.
- `depth < 1` → `ValueError` (CLI surfaces it).
- Cycles in the `CALLS` graph → bounded by the visited-id path guard; no infinite loop.
- Empty graph / no edges → empty `callers`/`callees`, `found=True` if the symbol exists.
- All SQL identifiers are fixed; `fqn`, `namespace`, `depth`, `min_confidence`,
  `rel_types` are bound parameters (no injection surface).

---

## Testing

### Integration (fresh namespace, no LLM)

Seed a small code graph directly (insert `CODE_SYMBOL` entities + `CALLS`/`INHERITS`
relationships with `properties.evidence`), then:

- `code_impact("pkg.a", depth=1)` → correct direct callers and callees, evidence
  surfaced.
- `depth=2` → transitive symbols appear with `depth=2`.
- A cycle (a→b→a) does not hang and returns bounded results.
- Unknown FQN → `found=False`.
- `min_confidence` filters low-weight edges.

### Enrichment (integration)

- Import via `attach_code_edges` with records whose chunk metadata carries `fqn`+`summary`
  → matching `CODE_SYMBOL` entity description equals the summary.
- Without summary → description falls back to `"Code symbol {fqn}"`.
- `summaries_by_fqn` unit test (pure): extracts the map from representative records.

### CLI

- `pgrg code-impact --help` registered.
- Against seeded data: tree output contains caller/callee FQNs; `--json` parses to the
  expected dict shape; not-found exits non-zero.

---

## Files

- **Create** `src/pg_raggraph/code_graph.py` — dataclasses + `code_impact` traversal.
- **Modify** `src/pg_raggraph/__init__.py` — add `GraphRAG.code_impact(...)`.
- **Modify** `src/pg_raggraph/cli.py` — add `code-impact` command; thread `summaries`
  into the `ingest-chunkshop-table --with-code-edges` branch.
- **Modify** `src/pg_raggraph/chunkshop_bridge.py` — add `summaries_by_fqn`; add
  `summaries=` to `code_edges_to_known_graph`, `attach_code_edges`,
  `fetch_code_edges_from_table`.
- **Create** `tests/integration/test_code_graph.py`, `tests/unit/test_code_graph_cli.py`;
  extend `tests/integration/test_chunkshop_bridge.py` for enrichment.

## Out of scope (future slices)

- `code-path <src> <dst>` shortest-path command.
- `code-symbol <fqn>` detail view.
- Gap #4 (`top_terms` → query hint expansion) — separate retrieval-side slice.
