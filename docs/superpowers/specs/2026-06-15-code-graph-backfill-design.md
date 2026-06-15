# Design: out-of-band code-graph backfill (#81)

**Status:** approved (design phase)
**Issue:** [#81](https://github.com/yonk-labs/pg-raggraph/issues/81)
**Date:** 2026-06-15

## Problem

`defer_extraction=True` lets `ingest_records` return fast by skipping the
synchronous extraction passes and marking docs `graph_status='pending'` for
later backfill. The existing backfill primitive (`backfill.extract_documents`
→ `_extract_one`) only runs **generic LLM/lede entity extraction**. It has no
code-graph path.

For code-aware ingests (`chunk_strategy="chunkshop:symbol_aware"`), the slow
synchronous step is the **corpus-level code-graph resolver**
(`_write_corpus_code_graph`, ~tens of minutes on ~5k chunks), which materializes
the `CALLS`/`INHERITS`/`IMPLEMENTS` graph. That resolver runs *only inline*
during the ingest transaction. When extraction is deferred:

- `__init__.py:1253` gates corpus `accumulate()` + spill on `not defer_extraction`
  → deferred ⇒ nothing accumulated/spilled.
- `__init__.py:1263` gates intra-file `code_edges` materialization on
  `not defer_extraction` → deferred ⇒ intra-file edges dropped too.
- `backfill._extract_one` has no `CorpusCodeGraph`/`_write_corpus_code_graph`
  path, so `pgrg extract` flips the doc to `ready` having written **zero** code
  edges.

Net effect: for code KBs, `defer_extraction=True` is **fast ingest OR code
graph, never both** — the call graph becomes unrecoverable out-of-band.
Downstream (EnterpriseDB/bento #768) needs fast code-KB ingest *without* losing
the call graph.

## Key facts that shaped the design

1. **The corpus code graph is a whole-corpus operation, not per-doc.** chunkshop
   resolves a call by matching its bare name against *all* symbols one extractor
   instance has accumulated. So cross-file `CALLS`/`INHERITS`/`IMPLEMENTS` edges
   can only resolve after *every* code doc's symbols are accumulated — unlike
   `extract_documents`, which resolves each doc independently. A backfill
   primitive must process the code docs as a **set**, per namespace.

2. **The raw document text is never persisted.** `documents` stores only
   `content_hash` + `source_path` + `metadata`; the original file content lives
   only as symbol-scoped bodies in `chunks.content`. Reconstructing a parse-able
   file by joining symbol chunks is lossy (imports / module-level glue between
   symbols are not faithfully recoverable). To re-parse faithfully at backfill
   time, the **raw content must be persisted at ingest time** for deferred code
   docs.

3. **The slow part is the resolver, not the per-doc parse.** Per-doc
   `accumulate()` is ~ms of tree-sitter; `_write_corpus_code_graph` (resolve +
   upsert across all call sites) is what pins the proxy. That resolve is the
   piece worth moving out-of-band; the existing #76 spill machinery already
   bounds its memory to `O(batch + symbol index)`.

## Decisions (locked with the user)

- **Content source:** persist raw content at ingest time (faithful re-parse),
  not reconstruct-from-chunks (lossy).
- **Surface:** a separate `pgrg backfill-code-graph` command + `backfill_code_graph`
  primitive, orthogonal to `pgrg extract` — so entity backfill and code-graph
  backfill never contend over `graph_status`.

## Design

### New table: `code_backfill_stage` (migration 015) — LOGGED/durable

```sql
CREATE TABLE IF NOT EXISTS code_backfill_stage (
    document_id BIGINT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    namespace   TEXT NOT NULL,
    content     TEXT NOT NULL,
    language    TEXT,
    source_path TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_code_backfill_stage_ns ON code_backfill_stage (namespace);
```

- **LOGGED, unlike `code_calls_stage`.** `code_calls_stage` is UNLOGGED because
  it is written-drained-deleted within a single `ingest_records()` call and
  surviving a crash has no value. This table is the opposite: its content must
  survive *between* the deferred ingest and a later `pgrg backfill-code-graph`
  run, possibly across a restart. An UNLOGGED table is truncated on crash
  recovery → silent content loss. So it is a normal (logged) table.
- `PRIMARY KEY (document_id)` → idempotent re-ingest of the same doc replaces
  the staged content (`ON CONFLICT (document_id) DO UPDATE`).
- `ON DELETE CASCADE` → deleting a document drops its staged content.
- The table **doubles as the code-graph work queue**, keyed independently of
  `graph_status`. This is what keeps entity backfill (`pgrg extract`, which owns
  `graph_status`) and code-graph backfill orthogonal.

Mirror the table into `sql/schema.sql` (for fresh installs) the same way
`code_calls_stage` appears in both schema and a migration.

### Ingest hook (`_ingest_one_content`)

Inside the existing per-doc transaction, immediately after the `documents`
INSERT (so `doc_id` is known):

```python
if defer_extraction and _code_lang and pre_chunked is None:
    await tx.execute(
        "INSERT INTO code_backfill_stage "
        "(document_id, namespace, content, language, source_path) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (document_id) DO UPDATE SET "
        "  content = EXCLUDED.content, "
        "  language = EXCLUDED.language, "
        "  source_path = EXCLUDED.source_path",
        (doc_id, ns, content, _code_lang, file_path),
    )
```

- **Gate:** deferred + code doc (`_code_lang` truthy = a symbol_aware chunk
  carries `language`) + not `pre_chunked`. Pattern C (`pre_chunked`) deferred
  code docs are out of scope for v1: there, `content` is joined-chunk text, not
  a faithful file.
- **Atomic** with the chunks/document writes — staged content lands iff the doc
  lands. A rolled-back ingest leaves no orphan stage row.

### New primitive: `backfill_code_graph(rag, namespace, *, batch_size=5000)`

In `backfill.py`, sibling to `extract_documents`. A per-namespace corpus pass:

1. If `namespace is None`: `SELECT DISTINCT namespace FROM code_backfill_stage`
   and run one pass per namespace (cross-file resolution is namespace-scoped —
   symbols never cross namespaces).
2. Fetch the staged `document_id`s for the namespace (ids only — bounded memory).
   If none, return zero stats.
3. `ccg = CorpusCodeGraph()`. If `not ccg.available` (installed chunkshop lacks
   the extractor), log a warning, **leave** the staged rows in place (so a later
   run with chunkshop present can complete the work), and return a `skipped`
   stat. Do not delete rows or mark anything done.
4. `run_id = uuid4().hex`. For each staged doc id, fetch its
   `content`/`language`/`source_path` (one row at a time), call
   `calls = await ccg.accumulate(content, source_path=..., language=...)`, and
   `if calls: await rag._spill_code_calls(ns, run_id, calls)`. Discard the
   content after each doc → peak memory `O(one doc + symbol index + spill batch)`.
5. `n_rels = await rag._write_corpus_code_graph(ns, ccg, run_id, batch_size=batch_size)`
   — reuses the #76 keyset-batched resolver + spill drain + class-edge pass +
   `code_calls_stage` cleanup verbatim.
6. `DELETE FROM code_backfill_stage WHERE document_id = ANY(claimed_ids)`.
7. Return `CodeGraphStats(namespaces, docs, edges, skipped, errors)`.

**Resumability:** staged rows are deleted only after the resolve succeeds. A
crash mid-pass leaves them in place; re-running reprocesses (the edge upserts in
`_persist_code_edges` are idempotent, so re-resolve is safe).

**Concurrency:** this is a corpus "finalize" — intended to run as a single
worker per namespace. Two concurrent runs over the same namespace are *correct*
(idempotent upserts) but do duplicate work. v1 documents this rather than adding
a claim column; `graph_status` is untouched so it never contends with
`pgrg extract`.

### CLI: `pgrg backfill-code-graph`

```
pgrg backfill-code-graph --namespace NS [--batch-size 5000]
```

Thin wrapper mirroring `pgrg extract` ergonomics minus the daemon: connect,
call `backfill_code_graph`, echo `docs=… edges=…`. One-shot; re-run to resume.
`--batch-size` is forwarded to the resolver's spill-drain batch.

## Testing (TDD)

New `tests/integration/test_backfill_code_graph.py` (chunkshop + tree_sitter
gated, mirroring `test_code_graph.py`):

1. **Cross-file parity (acceptance):** ingest `_PKG_A`/`_PKG_B` with
   `defer_extraction=True, cross_file_code_graph=True`. Assert: zero CALLS rows,
   `code_backfill_stage` has 2 rows, docs are `graph_status='pending'`. Run
   `backfill_code_graph(rag, NS)`. Assert: `a.helper` has caller `b.run`, the
   edge's `resolved_intra_file='false'`, `code_calls_stage` empty,
   `code_backfill_stage` empty — i.e. byte-identical outcome to
   `test_cross_file_code_graph_resolves_callers`.
2. **Intra-file default parity:** single `_INGEST_SRC` doc, `defer_extraction=True`,
   no cross-file flag → after backfill, intra-file `CALLS`/`INHERITS` resolve
   (e.g. `sample.runner` callee `sample.helper`, `sample.Base` caller
   `sample.Child`).
3. **Idempotency:** run `backfill_code_graph` twice → identical edge set, no
   duplicate relationships.
4. **Persistence gate:** a prose doc deferred → no `code_backfill_stage` row; a
   code doc ingested *without* `defer_extraction` → no `code_backfill_stage` row
   (edges materialized inline as today).
5. **CLI smoke:** `pgrg backfill-code-graph -n NS` exits 0 and reports edges.

Migration applies cleanly via the existing migration-runner harness.

## Docs

Update `docs/cookbook/background-extraction.md`: document the code-KB flow —
defer code ingest, then run `pgrg extract` (entities) **and**
`pgrg backfill-code-graph` (call graph). Note the LOGGED staging table and the
single-worker-per-namespace guidance.

The CLAUDE.md MCP House Rule (server_instructions.py + user-guide.md + README.md)
is **not** triggered — this adds a CLI command + primitive, not an MCP tool
change — so `tests/unit/test_instructions_sync.py` stays green untouched.

## Out of scope (v1)

- Pattern C (`pre_chunked`) deferred code docs.
- Daemon mode for the code-graph pass.
- Multi-worker cross-file claim coordination (single-worker corpus finalize).
