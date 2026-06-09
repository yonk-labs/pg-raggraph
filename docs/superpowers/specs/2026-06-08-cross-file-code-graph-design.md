# Design — Corpus-Wide Cross-File Code Graph (#76) — 2026-06-08

> **Status:** Approved decisions, pre-implementation.
> **Fixes:** GH #76 — `extract_symbol_graph` resolves intra-file CALLS only;
> cross-file calls (the majority in real code) are never materialized, so most
> symbols have 0 callers. Downstream: EnterpriseDB/bento#779.
> **Builds on:** #74/#75 (v0.5.0a11 symbol_aware code graph at ingest).

## Problem

`extract_symbol_graph` builds **one chunkshop `CodeRelationshipsExtractor` per
document** and calls `finalize()` per file. chunkshop resolves a call by matching
its bare name against the symbols that *one extractor* has accumulated — so a call
in `b.py` to a function defined in `a.py` never resolves (verified: per-file → 0
edges; one extractor over both files → `CALLS b.runner → a.helper`). Evidence
from a 765-file ingest: every edge `resolved_intra_file=true`, 58% of symbols have
0 callers.

## Decisions (locked)

1. **Opt-in.** New flag `cross_file_code_graph` (config + per-call kwarg). Default
   stays the per-file/streaming behavior — no regression for existing ingests.
2. **Compact parsed state, streaming-preserving.** Use **one shared extractor**
   across the whole `ingest_records` batch via chunkshop's **public API**
   (`extract()` per doc, `finalize()` once). The extractor holds O(symbols), never
   the corpus content, so bounded-memory streaming (the #46 thesis) is preserved.

## Architecture

A small holder owns the shared extractor + an `asyncio.Lock`:

```python
# chunkshop_bridge.py
class CorpusCodeGraph:
    """Accumulates code symbols/calls across a whole ingest for corpus-wide
    cross-file resolution. One per ingest_records call when cross_file is on."""
    def __init__(self): self._ext = <load CodeRelationshipsExtractor> ; self._lock = asyncio.Lock()
    async def accumulate(self, content, *, source_path, language): ...  # locked extract()
    def finalize(self, *, project_id) -> list[dict]: ...               # one resolve at end
    @property
    def available(self) -> bool: ...  # None-safe on older chunkshop
```

- `accumulate()` wraps `self._ext.extract(content, source_path=, language=)` in
  the lock (extract() mutates shared state and isn't thread-safe; it's ~ms of
  tree-sitter so lock contention is negligible — embedding stays outside the lock,
  still concurrent).
- `finalize()` returns the corpus edge list (intra **and** cross-file), edge dicts
  key-compatible with the existing `code_edges_to_known_graph` mapper.

### Flow (when `cross_file_code_graph=True`)

```
ingest_records:
  corpus = CorpusCodeGraph()            # created before the gather
  ── per doc (concurrent, phase 1) ──
     _ingest_one_content:
       chunk + embed + write chunks (+ per-doc callees as today, #74)
       await corpus.accumulate(content, source_path=file_path, language=<from chunk meta>)
       # SKIP the per-doc __code_edges__ write — deferred to the corpus pass
  ── after gather (phase 2, sequential) ──
     edges = corpus.finalize(project_id=namespace)
     entities, rels = code_edges_to_known_graph(edges)   # REUSED (Pattern C mapper)
     for rel: rel.properties["resolved_intra_file"] = (evidence.resolution == "intra_file")
     one transaction: upsert CODE_SYMBOL entities (exact-name, no fuzzy) + relationships
```

- Phase 2 entities/relationships use the same exact-name insert + relationship
  upsert as #74/#75 (idempotent via `ON CONFLICT`). Endpoints are corpus FQNs;
  entities are created here if a symbol had no intra-file edge.
- `resolved_intra_file` is persisted in `relationships.properties` so consumers
  can distinguish the two edge classes (acceptance criterion). `code_impact`'s
  read path is unchanged (it already unions all CODE_REL_TYPES).

### Default path (`cross_file_code_graph=False`)

Untouched. `_chunk_via_chunkshop` still attaches callees + stashes per-doc
`__code_edges__`, and `_ingest_one_content` writes them per-doc. (We feed the
corpus extractor with a second cheap `parse`/`extract` pass rather than rewiring
chunking, keeping the default path zero-risk.)

## Non-goals

- Changing the default (stays per-file). - The `pgrg extract` background path
  (corpus pass is synchronous-only). - Cross-namespace resolution. - chunkshop's
  own language-detection gap (tracked separately at yonk-labs/chunkshop).
- Schema changes (`resolved_intra_file` rides existing `properties` JSONB).

## Testing

- **Unit** (`importorskip` chunkshop + tree_sitter_python): `CorpusCodeGraph`
  over two in-memory files (`b` imports+calls `a.helper`) → `finalize()` yields a
  cross-file `CALLS b.runner → a.helper`; per-file control yields none.
- **Integration** (DB): ingest a 2-file package with `cross_file_code_graph=True`
  where `mod_b.run()` calls `mod_a.helper()`; assert
  `code_impact("a.helper").callers` includes `b.run` and the edge's
  `resolved_intra_file` is false. Control: same ingest without the flag → caller
  absent (documents the per-file limitation).
- **Self-ingest validation**: ingest pg-raggraph's own `src/` with the flag; assert
  cross-file CALLS now appear (e.g. a `retrieval`→`db` edge) and the
  `resolved_intra_file=false` count is > 0 (was 0 before).

## Files

- `src/pg_raggraph/config.py` — `cross_file_code_graph: bool = False`.
- `src/pg_raggraph/chunkshop_bridge.py` — `CorpusCodeGraph` + resolved_intra_file helper.
- `src/pg_raggraph/__init__.py` — `ingest_records`/`_ingest_one_content`: create,
  feed, finalize+write the corpus graph when the flag is on.
- `tests/unit/test_code_relationships.py`, `tests/integration/test_code_graph.py`.
- `docs/cookbook/chunkshop-integration.md`, `CHANGELOG.md`.
