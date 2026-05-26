# Handover — Chunkshop 0.6 Integration (2026-05-26)

> **Purpose:** Pick up the Chunkshop integration work in a fresh session with no prior thread context.
> Read this document first, then run the validation commands, then continue at **Next steps**.

---

## TL;DR

PR #41 was merged into `main`, then this branch added the first pg-raggraph side of the new Chunkshop feature bridge.

Current branch: `chunkshop-0.6-integration`

Branch state: clean, ahead of `origin/main` by 2 commits:

- `182228d feat: bridge chunkshop code ingest surfaces`
- `08c18a7 docs: add chunkshop user guide`

The core work is done and committed:

- Runtime-detected Chunkshop 0.6 code chunker pass-throughs:
  - `chunk_strategy="chunkshop:code_aware"`
  - `chunk_strategy="chunkshop:symbol_aware"`
- New `pg_raggraph.chunkshop_bridge` module for Pattern C imports from Chunkshop Postgres sink tables.
- New CLI command: `pgrg ingest-chunkshop-table`.
- Optional import of Chunkshop `code_edges` into pg-raggraph `CODE_SYMBOL` entities and graph relationships.
- Relationship `properties` and known entity `properties` now persist through ingest.
- Dedicated user guide: `docs/chunkshop-user-guide.md`.
- Focused unit, integration, and scale coverage passed.

The main remaining work is productization: push/open a PR, review the docs, decide whether to add an automated live Chunkshop table e2e fixture, and optionally add a schema/dimension migration guide.

---

## Practical Answer: Are Vector Dimensions Changeable?

Yes, but only at the right lifecycle point.

pg-raggraph uses pgvector columns declared as `vector({dim})` in `src/pg_raggraph/sql/schema.sql`. The `{dim}` is filled from `PGRGConfig.embedding_dim` when the database schema is first bootstrapped.

That means:

- **New empty database:** yes. Set `GraphRAG(embedding_dim=768)` or `PGRG_EMBEDDING_DIM=768` before first `rag.connect()` / `pgrg init`.
- **Existing bootstrapped database with data:** treat it as effectively immutable. The `chunks.embedding`, `entities.embedding`, and embedding-cache vectors are already typed at the old dimension.
- **Per namespace:** no. Different namespaces in the same database cannot safely use different embedding dimensions because they share the same vector columns and indexes.
- **Chunkshop Pattern C:** Chunkshop's stored embeddings must match `GraphRAG(embedding_dim=...)`. The bridge validates precomputed embedding length and raises a clear error on mismatch.

Practical migration path if you want to move from 384-dim bge-small to 768/1024/etc.:

1. Create a fresh database, or a fresh isolated deployment/database for that corpus.
2. Enable `vector` and `pg_trgm`.
3. Initialize pg-raggraph with the new `embedding_dim` and matching `embedding_model`.
4. Re-ingest/re-embed the corpus, or import Chunkshop rows produced with the same dimension.
5. Cut callers over after validation.

Avoid trying to mix 384-dim and 768-dim embeddings in the same pg-raggraph database. It turns into a schema/index/cache migration plus full re-embed anyway.

---

## What Was Implemented

### Chunkshop Strategy Pass-Throughs

File: `src/pg_raggraph/chunking.py`

Added runtime-detected support for:

- `chunkshop:code_aware`
- `chunkshop:symbol_aware`

The implementation stays compatible with published Chunkshop 0.5.0 by checking whether the newer Chunkshop config classes exist at runtime. If a local/source Chunkshop 0.6 build is installed, the code strategies appear; if not, existing 0.5 prose strategies still work.

Supported `chunkshop:*` strategies now documented:

- `hierarchy`
- `sentence_aware`
- `semantic`
- `fixed_overlap`
- `neighbor_expand`
- `code_aware`
- `symbol_aware`

### Pattern C Bridge

New file: `src/pg_raggraph/chunkshop_bridge.py`

Exports:

- `rows_to_records(rows, source_prefix="chunkshop", skip_llm=False)`
- `fetch_records_from_table(dsn, schema, table, source_prefix="chunkshop", skip_llm=False)`
- `code_edges_to_known_graph(rows, min_confidence=0.0)`
- `attach_code_edges(records, edge_rows, min_confidence=0.0)`
- `fetch_code_edges_from_table(dsn, schema, project_id=None, min_confidence=0.0)`

Expected Chunkshop sink columns:

- `doc_id`
- `seq_num`
- `original_content`
- `embedded_content`
- `embedding`
- `metadata`
- `tags`
- `source`

The bridge groups Chunkshop chunks by `doc_id`, sorts by `seq_num`, reconstructs record text, and emits `ingest_records(..., pre_chunked=[...])` records. This bypasses pg-raggraph chunking and embedding while still allowing pg-raggraph to run graph extraction unless `skip_llm=True`.

### Code Edge Import

Chunkshop `code_edges` rows are converted into:

- `CODE_SYMBOL` entities.
- Relationships such as `CALLS`, `INHERITS`, `IMPLEMENTS`.
- Relationship `properties` preserving `project_id`, node ids, confidence/evidence provenance.
- Entity `properties` preserving Chunkshop symbol node ids.

Known relationship and known entity property persistence was fixed so this data actually lands in Postgres.

### CLI

File: `src/pg_raggraph/cli.py`

New command:

```bash
pgrg --db "$PGRG_DSN" ingest-chunkshop-table \
  --schema chunkshop_code \
  --table kb_code \
  --namespace code_graph \
  --with-code-edges \
  --project-id kb_code \
  --min-confidence 0.7 \
  --skip-llm
```

Options:

- `--schema`
- `--table`
- `--chunkshop-dsn`
- `--namespace`
- `--source-prefix`
- `--skip-llm`
- `--with-code-edges`
- `--project-id`
- `--min-confidence`

### Documentation

Added:

- `docs/chunkshop-user-guide.md`

Updated:

- `README.md`
- `docs/README.md`
- `docs/user-guide.md`
- `docs/Config-Reference.md`
- `docs/cookbook/chunkshop-integration.md`

The new guide covers:

- Pattern D chunker-only integration.
- Pattern C Postgres sink import.
- CLI examples.
- SDK examples.
- Code-edge imports.
- Verification SQL.
- Troubleshooting, especially embedding dimension mismatch.

---

## Validation Already Run

Environment notes:

- Full optional/dev extras were installed locally with `uv sync --extra all --extra dev --extra bench`.
- The sibling checkout was installed editable with `uv pip install -e ../chunkshop/python`, giving local `chunkshop==0.6.0`.
- `en_core_web_sm` was reinstalled for lede/spaCy tests after the sync rebuilt the venv.

Passed:

```bash
uv run ruff check src/pg_raggraph tests/unit/test_chunking.py \
  tests/unit/test_chunkshop_bridge.py tests/unit/test_cli_chunkshop.py \
  tests/integration/test_chunkshop_bridge.py
```

```bash
uv run pytest tests/unit/test_chunking.py \
  tests/unit/test_chunkshop_bridge.py \
  tests/unit/test_cli_chunkshop.py \
  tests/integration/test_chunkshop_bridge.py -q
# 48 passed
```

```bash
uv run pytest tests/unit -q
# 340 passed
```

```bash
uv run pytest tests/integration -q
# 174 passed, 17 skipped
```

```bash
env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph \
  uv run pytest tests/scale -q
# 38 passed
```

Scale note:

- Running `tests/scale` against the shared `localhost:5434` database produced one planner-sensitive failure in `test_twostage_retrieval.py`.
- That database had ~22k existing chunks and a large HNSW index, and Postgres chose a seq scan for a plan-shape assertion.
- The same scale suite passed on a clean pgvector database on `localhost:5437`.
- Practical conclusion: not a Chunkshop regression; local DB state affected a cost-based planner assertion.

---

## Current Git State

Expected state:

```bash
git status --short --branch
# ## chunkshop-0.6-integration...origin/main [ahead 2]
```

Expected commits:

```bash
git log --oneline --decorate -5
# 08c18a7 docs: add chunkshop user guide
# 182228d feat: bridge chunkshop code ingest surfaces
# 20304b5 origin/main Add retrieval profile ladder and benchmark matrix
```

After this handover is committed, the branch will be ahead by 3 commits.

---

## What Is Not Done Yet

1. **No PR opened yet for this branch.**
   The code is committed locally only.

2. **No live Chunkshop-generated table fixture in pg-raggraph tests.**
   Current tests validate the bridge with representative row dicts and a real pg-raggraph DB write. They do not run `chunkshop ingest` to create a sink table first.

3. **No schema migration guide for changing vector dimensions.**
   The answer is documented in existing config/ops docs, and this handover explains it, but a dedicated "changing embedding dimensions" operator page may be useful.

4. **No full codebase impact-of/query surface yet.**
   This session focused on ingest bridge surfaces. If the next goal is "impact-of" over Chunkshop code edges, that should be a separate feature slice.

5. **No decision yet on whether pg-raggraph should own a first-class code-symbol query API.**
   Today it imports code symbols into the existing entity/relationship graph. That is enough for graph traversal, but not a specialized code-intelligence UX.

---

## Next Steps

Recommended order:

1. **Commit this handover.**
   Use:

   ```bash
   git add docs/superpowers/HANDOVER-2026-05-26-chunkshop-integration.md
   git commit -m "docs: add chunkshop integration handover"
   ```

2. **Push branch and open PR.**

   ```bash
   git push -u origin chunkshop-0.6-integration
   gh pr create --draft \
     --title "Add Chunkshop code ingest bridge" \
     --body-file /tmp/pg-raggraph-chunkshop-pr.md
   ```

3. **PR description should call out:**

   - PR #41 was merged first.
   - Chunkshop 0.6 code chunkers are runtime-detected.
   - Published dependency floor stays `chunkshop>=0.5.0` because hard `>=0.6.0` is not safe until the release is available on PyPI.
   - Pattern C requires embedding dimensions to match.
   - Full unit/integration/scale results.
   - Scale-on-5434 planner note and clean-5437 pass.

4. **Add a real Chunkshop e2e if desired.**

   A strong follow-up test would:

   - Create a temporary Chunkshop sink table in Postgres.
   - Insert or produce rows with the canonical sink schema.
   - Run `pgrg ingest-chunkshop-table`.
   - Assert pg-raggraph documents/chunks/entities/relationships landed.

   If running real `chunkshop ingest` is too heavy for CI, keep the current bridge integration test and add a smaller CLI DB fixture around a manually-created sink table.

5. **Decide the vector-dimension operator story.**

   If this is becoming a user-facing concern, add `docs/cookbook/changing-embedding-dimensions.md` with:

   - Why `vector(dim)` is database-bootstrapped.
   - How to create a parallel DB at 768/1024/1536.
   - How to re-ingest or re-import from Chunkshop.
   - How to validate query parity before cutover.

6. **Next feature slice: code graph query UX.**

   If continuing the Chunkshop 0.6 feature adoption, build a small read-side layer:

   - Query by code symbol FQN.
   - Show direct callers/callees.
   - Show graph paths between two symbols.
   - Surface relationship evidence snippets from `relationships.properties->'evidence'`.
   - Add CLI command such as `pgrg code-impact <symbol>`.

---

## Suggested PR Body

```markdown
## Summary

Adds pg-raggraph support for the new Chunkshop code-ingest surfaces while keeping compatibility with published Chunkshop 0.5.x.

- Adds runtime-detected `chunkshop:code_aware` and `chunkshop:symbol_aware` chunk strategies.
- Adds `pg_raggraph.chunkshop_bridge` for importing Chunkshop Postgres sink rows through `ingest_records(pre_chunked=...)`.
- Adds `pgrg ingest-chunkshop-table`.
- Imports Chunkshop `code_edges` as `CODE_SYMBOL` entities and graph relationships.
- Persists known entity and known relationship `properties`.
- Adds user guide and cookbook updates.

## Testing

- `uv run ruff check src/pg_raggraph tests/unit/test_chunking.py tests/unit/test_chunkshop_bridge.py tests/unit/test_cli_chunkshop.py tests/integration/test_chunkshop_bridge.py`
- `uv run pytest tests/unit/test_chunking.py tests/unit/test_chunkshop_bridge.py tests/unit/test_cli_chunkshop.py tests/integration/test_chunkshop_bridge.py -q` → 48 passed
- `uv run pytest tests/unit -q` → 340 passed
- `uv run pytest tests/integration -q` → 174 passed, 17 skipped
- `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/scale -q` → 38 passed

## Notes

The stable extra remains `chunkshop>=0.5.0`. The new code-aware strategies activate only when a Chunkshop build containing the 0.6 config classes is installed.

Pattern C imports require the Chunkshop embedding dimension to match `GraphRAG(embedding_dim=...)`; pgvector columns are typed as `vector(dim)` at database bootstrap.
```

---

## Paste-Ready New Session Prompt

```text
Continue the Chunkshop integration work in /home/yonk/yonk-tools/pg-raggraph on branch chunkshop-0.6-integration.

Read docs/superpowers/HANDOVER-2026-05-26-chunkshop-integration.md first.

State: PR #41 was merged. This branch is clean and contains:
- 182228d feat: bridge chunkshop code ingest surfaces
- 08c18a7 docs: add chunkshop user guide
- plus the handover commit if present.

Implemented:
- chunkshop:code_aware and chunkshop:symbol_aware runtime-detected strategies.
- pg_raggraph.chunkshop_bridge Pattern C helpers.
- pgrg ingest-chunkshop-table.
- Chunkshop code_edges import into CODE_SYMBOL entities and graph relationships.
- known entity/relationship properties persistence.
- docs/chunkshop-user-guide.md.

Validation already passed:
- focused Chunkshop tests: 48 passed
- full unit: 340 passed
- full integration: 174 passed, 17 skipped
- scale on clean localhost:5437 pgvector DB: 38 passed

Important vector-dimension rule:
GraphRAG embedding_dim controls pgvector vector(dim) at database bootstrap.
It is configurable for a fresh DB, but effectively immutable after ingest.
Do not mix dimensions per namespace in one pg-raggraph DB. Chunkshop Pattern C
embeddings must match GraphRAG(embedding_dim=...).

Next:
1. Push branch and open a draft PR.
2. Add a live/manual Chunkshop sink-table e2e if desired.
3. Consider a dedicated operator guide for changing embedding dimensions.
4. If continuing features, build code read-side UX: code-impact, callers/callees, path between symbols, evidence snippets from relationship properties.
```
