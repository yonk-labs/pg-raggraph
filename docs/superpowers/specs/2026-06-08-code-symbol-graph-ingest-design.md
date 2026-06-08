# Design — Code-Symbol Graph at Ingest (`chunkshop:symbol_aware`) — 2026-06-08

> **Status:** Approved design, pre-implementation. Next step: writing-plans.
> **Fixes:** GH #74 (per-chunk `callees` never populated), GH #75 (`entities`/
> `relationships` never populated for code-aware ingests → `code_impact()` reads
> an empty graph).
> **Filed by:** downstream consumer (EnterpriseDB/bento). Version of record:
> pg-raggraph `feb9a0b7` (v0.5.0a10).

---

## Problem

When ingesting with `chunk_strategy="chunkshop:symbol_aware"`, pg-raggraph
produces correct per-symbol chunks (`fqn`, `node_id`, `symbol_type`, line ranges
all land in `chunks.metadata`) but **stops there**:

- **#74** — it never runs chunkshop's `CodeRelationshipsExtractor`, so
  `chunk.metadata['callees']` (per-chunk tree-sitter call sites) is never
  populated. A consumer building a call graph from stored chunk metadata gets
  nothing.
- **#75** — the graph tables `entities` (CODE_SYMBOL nodes) and `relationships`
  (CALLS/INHERITS/IMPLEMENTS edges) — and the recursive-CTE traversal
  `code_graph.py::code_impact()` that reads them — all exist and are indexed, but
  **nothing writes to them** during a `symbol_aware` ingest. `code_impact()`
  therefore returns empty for code corpora: the read side is ready, there is no
  writer on the in-process path.

The read side already works for **Pattern C** (chunkshop runs its *own* full
pipeline, writes a `<schema>.code_edges` table; `pgrg ingest --with-code-edges`
reads it via `chunkshop_bridge.fetch_code_edges_from_table` →
`code_edges_to_known_graph` → `known_entities`/`known_relationships`). The gap is
the **Pattern D** in-process path (`chunk_strategy="chunkshop:symbol_aware"`),
where pg-raggraph drives chunkshop itself and never runs the extractor.

## Goals

- `symbol_aware` chunks carry `metadata['callees']` —
  `[{name, line, snippet, resolved_intra_file}, ...]` — for every chunk (#74).
- A `symbol_aware` ingest populates `CODE_SYMBOL` entities and
  `CALLS`/`INHERITS`/`IMPLEMENTS` relationships so `code_impact(fqn)` returns real
  callers/callees (#75).
- Both **always-on** when `chunk_strategy="chunkshop:symbol_aware"` — no new
  config knob, "just works" for the downstream consumer.
- Maximal reuse of the existing Pattern C machinery; the in-process path lands on
  the **same** `known_entities`/`known_relationships` ingest seam.

## Non-goals (out of scope)

- **Corpus-wide cross-file resolution.** Resolution is **per-file/per-document**:
  chunkshop's `finalize()` only resolves edges among symbols accumulated in one
  extractor instance, and pg-raggraph ingests one document per file in its own
  transaction. Intra-file edges resolve precisely; cross-file calls are
  best-effort (the ticket explicitly accepts this). Corpus-wide resolution is a
  documented fast-follow.
- **Fixing fuzzy entity-merge for code symbols.** ~~Out of scope.~~ **Pulled
  in-scope during execution (user-approved).** Implementation revealed the
  fuzzy leg corrupts the *common* `Class` vs `Class.method` case (shared FQN
  prefix), not just rare bare-name collisions — without a fix, `code_impact`
  collapses every class with methods. A targeted guard now skips fuzzy
  resolution for `entity_type == 'CODE_SYMBOL'` (identity-keyed by FQN); no
  effect on other entity types, and it also fixes the latent Pattern C case.
  See `resolution.py` + `test_resolution.py::test_code_symbols_never_fuzzy_merge`.
- The background-extraction (`pgrg extract`) path. `defer_extraction` ingests
  skip synchronous extraction; the code-graph step rides the synchronous path
  only.
- Strategies other than `symbol_aware` (e.g. `code_aware`, which is not
  symbol-based and emits no `fqn` chunks).
- Schema changes. This rides entirely on existing `entities` / `relationships` /
  `entity_chunks` tables and their indexes.

---

## Architecture

### chunkshop API (installed version, verified against `.venv` source)

- `chunkshop.extractors.load_extractor(cfg)` → extractor instance.
- `chunkshop.config.CodeRelationshipsExtractor(type="code_relationships")` — the
  config (pydantic). The runtime class is the same name in
  `chunkshop/extractors/code_relationships.py`.
- `extractor.extract(text, *, source_path=None, language=None) -> ExtractResult`
  — parses one chunk, returns `ExtractResult(tags, metadata)` where
  `metadata['callees'] = [{name, line, snippet, resolved_intra_file}, ...]`.
  Accumulates symbols + pending call/class edges as a side effect.
- `extractor.finalize(*, project_id="default") -> list[dict]` — resolves the
  accumulated pending edges to FQNs and returns edge dicts with keys:
  `edge_type` ("CALLS"|"INHERITS"|"IMPLEMENTS"), `edge_kind`, `src_fqn`,
  `dst_fqn`, `src_node_id`, `dst_node_id`, `confidence` (0.9 unique / 0.5
  ambiguous), `evidence` (dict), `provenance`, `provenance_metadata`.

These `finalize()` edge dicts are key-compatible with the rows
`chunkshop_bridge.code_edges_to_known_graph()` already consumes
(`src_fqn`/`dst_fqn`/`edge_type`/`confidence`/`src_node_id`/`dst_node_id`/
`evidence`). That compatibility is the linchpin of this design — **no new mapper.**

### Parser requirement — tree-sitter (verified empirically)

chunkshop's symbol/call parsing uses **tree-sitter** with a silent **regex
fallback** when the language grammar isn't importable. The difference is
load-bearing and was confirmed against the installed package:

- **With tree-sitter** (`tree-sitter` + `tree-sitter-python` installed): symbol
  chunks span full bodies, per-chunk `extract()` returns correct callees
  (`runner` → `helper`), and `finalize()` returns exactly the real edges
  (`runner→helper` CALLS, `Child.go→runner` CALLS, `Child→Base` INHERITS).
- **Regex fallback** (no grammar): symbol spans collapse to the `def`/`class`
  line, chunk bodies lose their content, per-chunk `extract()` misses real calls
  and emits self-edge noise. The feature is effectively non-functional.

The downstream consumer already gets correct line ranges (ticket #74), so their
env has tree-sitter. Implications for this slice:

- **Test dependency:** add `tree-sitter` + `tree-sitter-python` to the dev/test
  dependency group so tests exercise the real parse path. Integration/unit tests
  for this feature `pytest.importorskip("tree_sitter_python")`.
- **Docs:** `symbol_aware` code intelligence requires the relevant tree-sitter
  grammar for the source language; document this in the chunkshop cookbook. No
  hard runtime dependency is added to pg-raggraph (grammars are per-language and
  the consumer chooses them).
- **`resolved_intra_file`** from per-chunk `extract()` is conservatively `False`
  (a chunk parsed in isolation can't see siblings). The authoritative cross-symbol
  resolution is `finalize()`. This is a documented, minor limitation of the
  per-chunk callee flag, not of the persisted edges.

### New seam — `chunkshop_bridge.extract_symbol_graph()`

Add to `src/pg_raggraph/chunkshop_bridge.py` (already the home of chunkshop glue;
update its module docstring to cover Pattern D in-process extraction alongside
Pattern C sink reads). Lazy-imports chunkshop's extractor; returns `None` if the
installed chunkshop is too old to expose it (graceful degradation — older
`symbol_aware` users keep working, just without callees/edges).

```python
from dataclasses import dataclass, field

@dataclass
class SymbolGraph:
    # callees_by_index[i] is the callees list for chunk i (parallel to cs_chunks)
    callees_by_index: list[list[dict]] = field(default_factory=list)
    # raw finalize() edge dicts — fed straight into code_edges_to_known_graph()
    edges: list[dict] = field(default_factory=list)

def extract_symbol_graph(
    cs_chunks,                 # the chunkshop Chunk objects from chunker.chunk(doc)
    *,
    source_path: str | None,
    project_id: str = "default",
) -> SymbolGraph | None:
    """Run chunkshop's CodeRelationshipsExtractor over symbol_aware chunks.

    Returns per-chunk callees (#74) + resolved edges (#75), or None if the
    installed chunkshop lacks the extractor.
    """
```

Behavior: build one `CodeRelationshipsExtractor`; for each `cs` in `cs_chunks`
call `extract(cs.original_content, source_path=<path>, language=cs.metadata.get("language"))`
and collect `result.metadata.get("callees", [])`; then `finalize(project_id=...)`
for `edges`. Per-file scope = one call per document.

### #74 wiring — `chunking._chunk_via_chunkshop`

When the resolved chunkshop strategy is `symbol_aware`, after
`cs_chunks = chunker.chunk(doc)`:

1. `sg = chunkshop_bridge.extract_symbol_graph(cs_chunks, source_path=source_path, project_id=source_path or "doc")`
2. If `sg` is not `None`: as each chunk dict is built, set
   `meta["callees"] = sg.callees_by_index[i]` (#74).
3. Stash `sg.edges` on the **first** chunk's metadata under a reserved key
   `_CODE_EDGES_KEY = "__code_edges__"` (the only cross-module seam; see below).

Placing #74 here means `callees` populate for **every** caller of
`chunk_document` (including bare/unit-test calls), and #74 is unit-testable with
no DB. If `sg is None`, chunks are returned exactly as today (callees absent, no
crash).

### #75 wiring — `__init__._ingest_one_content`

The edges reach the ingest write path on the reserved `__code_edges__` key
(a single, private, popped-and-stripped metadata entry — chosen over changing
`chunk_document`'s widely-used `list[dict]` return type, and over re-parsing the
chunks a second time in the ingest path). Immediately after chunking
(`chunks = chunk_document_fn(...)`), before the existing known-graph merge:

```python
code_edges = chunks[0]["metadata"].pop("__code_edges__", None) if chunks else None
if code_edges:
    from pg_raggraph import chunkshop_bridge
    code_entities, code_rels = chunkshop_bridge.code_edges_to_known_graph(code_edges)
    known_entities = (known_entities or []) + code_entities
    known_relationships = (known_relationships or []) + code_rels
```

`pop` strips the key so it never persists on the chunk row. From here, the
existing merge blocks (lines ~1272–1331) and the transaction writer handle
CODE_SYMBOL entity insertion (via `resolve_entity`), `entity_chunks` links, and
relationship insertion — **identical to Pattern C**. No new write code.

Notes:
- The `pre_chunked` path is untouched (caller controls metadata; no `__code_edges__`).
- `defer_extraction` ingests skip extraction; they also skip the code-graph step
  (chunks still land for naive retrieval). Acceptable for this slice.
- `summaries` default to empty → CODE_SYMBOL descriptions fall back to
  `"Code symbol {fqn}"`, matching Pattern C when no `code_summary` extractor ran.

### Data flow (Pattern D, in-process)

```
chunk_document(strategy="chunkshop:symbol_aware")
  └─ _chunk_via_chunkshop
       ├─ chunker.chunk(doc) ───────────────► cs_chunks (fqn/node_id/symbol_type/language)
       ├─ extract_symbol_graph(cs_chunks)
       │     ├─ extract() per chunk ─────────► callees_by_index   (#74)
       │     └─ finalize() ──────────────────► edges              (#75)
       ├─ chunk[i].metadata["callees"] = callees_by_index[i]
       └─ chunk[0].metadata["__code_edges__"] = edges
                                   │
_ingest_one_content ◄─────────────┘
  ├─ pop "__code_edges__"  ──► code_edges_to_known_graph()  (REUSED, Pattern C path)
  │                              └─► (CODE_SYMBOL entities, CALLS/… relationships)
  ├─ merge into known_entities / known_relationships
  └─ existing transaction writer ──► entities + entity_chunks + relationships
                                          │
code_impact(fqn) ◄────────────────────────┘  (now non-empty)
```

---

## Testing

Per the project rule (everything gets tests; cumulative E2E). All code-graph
tests `pytest.importorskip("chunkshop")` **and** `pytest.importorskip(
"tree_sitter_python")` (regex fallback gives degraded parses — see Parser
requirement). `tree-sitter` + `tree-sitter-python` are added to the dev/test deps.

**Unit (`tests/unit/`, no DB):**
- `test_symbol_aware_attaches_callees` — chunk a small multi-function Python
  source via `chunk_document(strategy="chunkshop:symbol_aware")`; assert each
  function chunk's `metadata["callees"]` contains the expected `{name, line,
  snippet, resolved_intra_file}` entries, and that `__code_edges__` is present on
  chunk[0] and shaped as a list of edge dicts.
- `test_extract_symbol_graph_returns_edges` — `extract_symbol_graph` over a
  caller→callee pair returns a `CALLS` edge with both FQNs; returns `None` cleanly
  when the extractor is monkeypatched as unavailable.
- `test_finalize_edges_feed_code_edges_to_known_graph` — `finalize()` edge dicts
  pass through `code_edges_to_known_graph()` producing CODE_SYMBOL entities +
  CALLS/INHERITS/IMPLEMENTS relationships (pure, no DB).

**Integration (`tests/integration/`, requires PG on 5434):**
- `test_symbol_aware_ingest_populates_code_graph` — ingest a small Python module
  (two functions where `a` calls `b`, a class inheriting a base) with
  `chunk_strategy="chunkshop:symbol_aware"`; then `rag.code_impact("<fqn of b>")`
  returns `a` among callers, and `code_impact("<fqn of a>")` returns `b` among
  callees; assert `CALLS` and `INHERITS` edges exist.
- `test_distinct_code_symbols_stay_separate` — ingest clearly-dissimilar symbols
  (e.g. `mod.alpha` and `mod.omega`); assert two distinct CODE_SYMBOL rows exist
  and each is independently resolvable by `code_impact`. This is the deterministic
  green assertion that the in-process path creates per-FQN nodes.
- `test_bare_name_collision_merge_risk` — `xfail(strict=False, reason="pre-existing
  resolve_entity fuzzy-merge; see follow-up ticket")` probe: ingest `mod.process`
  and `mod.process_batch` and assert two distinct rows. Documents the pre-existing
  fuzzy-merge concern without reddening the suite; flips to a real pass if/when the
  follow-up fix lands.

**End-to-end coverage:** the
`test_symbol_aware_ingest_populates_code_graph` integration test above is the
end-to-end path (ingest a code module → `code_impact` returns real edges); it
lives alongside the existing read-side tests in
`tests/integration/test_code_graph.py`. (There is no `tests/test_e2e.py` despite
the CLAUDE.md reference — code_impact's tests live in `test_code_graph.py`.)

---

## Files touched

- `src/pg_raggraph/chunkshop_bridge.py` — add `SymbolGraph` dataclass +
  `extract_symbol_graph()`; update module docstring + `__all__`.
- `src/pg_raggraph/chunking.py` — in `_chunk_via_chunkshop`, call
  `extract_symbol_graph` for `symbol_aware`, attach `callees`, stash
  `__code_edges__` on chunk[0].
- `src/pg_raggraph/__init__.py` — in `_ingest_one_content`, pop `__code_edges__`,
  convert via `code_edges_to_known_graph`, merge into known graph args.
- `tests/unit/…`, `tests/integration/…`, `tests/test_e2e.py` — as above.
- `pyproject.toml` — add `tree-sitter` + `tree-sitter-python` to the dev/test
  dependency group (test-only; not a runtime dep).
- `docs/cookbook/chunkshop-integration.md` — document that Pattern D
  (`symbol_aware`) now populates `callees` + the code graph automatically, and
  that it requires the source language's tree-sitter grammar (regex fallback
  degrades results).

## Risks / concerns

- **Pre-existing fuzzy-merge of code symbols** (see Non-goals). Surfaced by an
  `xfail` test + a follow-up ticket; not fixed here.
- **chunkshop version drift** — `extract_symbol_graph` feature-guards and returns
  `None` if the extractor is absent; the integration tests `importorskip`.
- **Per-file scope** — cross-file edges are best-effort by design; documented as
  a fast-follow, not a regression.
- **Performance** — one extra tree-sitter parse per `symbol_aware` chunk at
  chunk time. Bounded by chunk count; only on the `symbol_aware` path.
