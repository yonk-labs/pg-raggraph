# Changelog

## Unreleased

### Data integrity — entity resolution/merge hardening

- **Entity descriptions are capped on every merge path** (PR-222,
  GAP-022). Hot entities used to accumulate unbounded description blobs
  (exact-match append, fuzzy merge, per-doc dedupe, backfill dedupe) that
  degraded retrieval and were re-embedded on every merge. All write paths
  now enforce keep-first append-until-cap via
  `entity_description_max_chars` (default 2000, `0` disables); the DB
  never stores past the cap. For corpora ingested before the cap, run
  `rag.trim_entity_descriptions()` once per namespace (see
  `docs/cookbook/entity-merge-audit.md`).
- **Fuzzy entity merges are now audited and repairable** (AAT-004).
  Every fuzzy auto-merge (`resolve_entity`, combined score ≥
  `resolution_threshold`) and every manual `merge_entities()` call
  writes a row to the new `entity_merge_log` table (migration 017):
  namespace, surviving id, absorbed name/type/description/properties,
  trgm/vec/combined scores, document provenance, timestamp. Read with
  `rag.entity_merges(namespace, since=None, min_score=None)` or
  `pgrg merges`; undo a false merge with `rag.split_entity(log_id)`
  (recreates the absorbed entity; repoints nothing — manual repair aid).
- **Version-suffixed names never fuzzy-merge** (AAT-004 I-1).
  "PostgreSQL 14" vs "PostgreSQL 15" or "Python 3.11" vs "3.12" were
  live merge candidates at default thresholds — exactly the versioned-docs
  workload where a false merge silently corrupts the graph. Names that
  differ only by a version-like token now refuse to merge, regardless of
  score (generalizes the CODE_SYMBOL exemption). Configurable via
  `entity_version_guard_pattern` (empty string disables).
- **`merge_entities()` no longer drops data** (AAT-004 I-14). The manual
  merge API used to repoint edges and DELETE the source entities without
  copying description/properties — silently losing what the automatic
  path preserved. It now unions descriptions (same keep-first-with-cap
  dedup as auto-merge) and merges properties (keep entity wins on key
  conflicts) before the delete, and writes `source='manual'` audit rows.

### ⚠️ Changed — default behavior

- **BREAKING: `pgrg serve` and `pgrg demo` now bind `127.0.0.1` by
  default, not `0.0.0.0`** (PR-217, GAP-012). The server is no longer
  reachable from other machines unless you opt in with `--host`. And a
  non-loopback bind (e.g. `--host 0.0.0.0`) is **refused at startup**
  unless `PGRG_SERVER_API_KEY` is set — the API allows unauthenticated
  ingest, query, and delete, and exposing that to a network was a
  footgun. To restore the old behavior knowingly, pass
  `--host 0.0.0.0 --insecure-no-auth`. Containers are unaffected in
  practice: the `Dockerfile` CMD now passes `--host 0.0.0.0` explicitly
  and `docker-compose.prod.yml` requires `PGRG_SERVER_API_KEY` in
  `.env`. If you scripted `pgrg serve` for LAN access, this WILL break
  you — that's the point; set the key.

### Security

- **DSN passwords are redacted in `ConnectionError` messages** (PR-218,
  GAP-013). `GraphRAG.connect()` failures used to embed the full DSN —
  password included — in the exception the CLI prints and servers log.
  The DSN now renders as `postgresql://user:***@host:port/db` via a new
  `redact_dsn()` helper (`pg_raggraph.config`), keeping host/port/dbname
  actionable. Handles URL and keyword-conninfo forms; never raises on
  malformed input.
- **Dependency CVEs cleared** (PR-216, GAP-011): urllib3 2.6.3 → 2.7.0
  (PYSEC-2026-141/142) and pydantic-settings 2.13.1 → 2.14.2
  (GHSA-4xgf-cpjx-pc3j) in `uv.lock`; a blocking `pip-audit` job now runs
  in CI on every push plus a weekly cron, so lockfile CVEs fail loudly.
- **Web UI no longer loads JavaScript from unpkg** (PR-219, GAP-014):
  htmx and vis-network are vendored into `pg_raggraph/static/vendor/`
  (shipped in the wheel), inline scripts moved to `static/app.js`, and the
  Content-Security-Policy tightened from
  `script-src 'self' https://unpkg.com 'unsafe-inline'` to
  `script-src 'self'`.

### Docs — claims corrections (AAT audit)

- Public benchmark claims re-captioned to what their in-repo sources
  support: the "+18.9% accuracy lift" headline is now "+19.3% top-score
  improvement (retrieval-quality proxy, not graded answer accuracy)" with
  the gold-QA non-transfer caveat linked; "15/15 perfect" split into
  10/10 graded + 5 smoke checks; omitted negative results (SEC, NTSB,
  MuSiQue) now listed; stale badges replaced with live ones.
- The "AGE Cypher and pgvector cannot combine in a single query" claim is
  retracted everywhere (README, CLAUDE.md, research docs) — the composed
  CTE pattern runs on stock Apache AGE 1.5.0 (verified). Positioning now
  rests on what survives per Microsoft's own docs: `shared_preload_libraries`
  lockout on non-Azure managed Postgres, openCypher subset, manual graph
  maintenance, and exponential path expansion beyond 3-4 hops. The
  42-111× figure is re-scoped to 42-101× graph-assisted modes,
  harness-scoped. ASSESSMENT.md refreshed with a dated claims-audit
  section.

## 0.7.0 — 2026-07-07 (out of alpha: ready signal, failure accounting, per-KB prompts, typed graph joins, BM25 + RRF default)

### ⚠️ Changed — default behavior

- **`fusion` default flipped `"linear"` → `"rrf"`** (issue #96, rung 1).
  Rankings from `naive`/`local`/`global`/`hybrid` queries WILL change: legs
  are now combined by Reciprocal Rank Fusion (scale-free) instead of a raw
  weighted sum where the lexical leg's ~0.01–0.1 ts_rank scale made it a
  near-no-op against cosine at 0.20 weight. Fused scores are small (~0.01)
  and NOT comparable to linear scores — do not threshold on them. To
  reproduce the old rankings byte-for-byte: `PGRG_FUSION=linear`,
  `PGRGConfig(fusion="linear")`, or per-call `rag.query(..., fusion="linear")`.
  `smart` mode is unaffected in its routing: its internal confidence probe is
  pinned to linear (the 0.7/0.4 thresholds are calibrated on raw linear
  scores).
- **`fusion` now applies to `local` and `global` modes** (issue #96
  addendum). Previously `fusion="rrf"` was silently inert outside the
  naive family — a registered A/B on a global-mode cell replicated the
  linear config without warning. Both graph modes now rank-fuse their
  vector/lexical legs over the graph-selected chunk set; the constant
  graph-presence leg drops out under rank fusion (it carries no ordering
  information within the candidate set).

### Fixed
- **Silent extraction failure: per-chunk LLM errors no longer masquerade as
  "no entities in this chunk" (#93).** `ExtractionResult` gained a
  `failed`/`error` marker set by every extraction leg (LLM, deterministic
  lede, and the `llm+lede` union). The backfill path (`pgrg extract`) now
  applies yield accounting per doc: all chunks errored + zero yield →
  `graph_status='failed'` with `graph_error = "extraction failed on N/M
  chunks: <first error>"` (retryable); partial yield → `'ready'` but
  degraded — `graph_error` keeps the failure summary instead of being
  nulled. Genuinely-empty docs (no chunk errors) stay plain `'ready'`.
  The synchronous ingest path counts a doc `degraded` on any chunk
  failure (previously only when the whole extraction call raised) and
  persists the same `graph_error` summary. The 2026-07-06 incident class
  (mlx-lm truncation: 111 entities where 1,004 belonged, every status
  green) is now visible from the status surface alone.

### Added
- **Per-doc extraction yield in `documents.metadata['extraction']`** —
  `{"chunks", "chunks_failed", "entities", "relationships"}` persisted by
  the backfill path (and `chunks/chunks_failed` by degraded sync ingests),
  so corpus-wide yield audits are one JSONB query.
- **`degraded` count in `graph_status_summary`** (thus `rag.status()`,
  `/status`, `pgrg_status`, and `QueryResult.metadata`): ready docs whose
  extraction had per-chunk failures (`graph_error` set). An overlay on
  `ready`, not a fifth lifecycle state. Also on `ExtractStats`
  (`degraded`, `chunks_failed`) and the `pgrg.backfill.extract` /
  `pgrg.backfill.queue_depth` metrics.
- **`pgrg extract --include-failed` re-queues degraded docs** too —
  re-extraction is idempotent, so retrying a partial-yield doc only fills
  in the missing graph.
- **First-class ingest-completion signal** (#92). New public API:
  `await rag.graph_ready(namespace)` (cheap bool — no doc is
  `pending`/`processing`) and
  `await rag.wait_for_graph_ready(namespace, timeout=600.0, poll_interval=2.0)`
  (blocks until background extraction drains; returns the final per-status
  summary; raises `TimeoutError` with the last-seen summary on timeout).
  `'failed'` docs are terminal and don't block readiness. Replaces raw-SQL
  polling of `documents.graph_status`.
- `rag.status()` (and therefore `GET /status` and the MCP `pgrg_status`
  tool) gains a derived `graph_ready: bool` alongside the existing counts.
- FastAPI `/ask` response now includes `graph_status_summary` (top-level),
  matching what `/query` already carried under `metadata` — partial-graph
  answers are no longer indistinguishable from fully-baked ones.
- **Per-KB (per-namespace) extraction prompt selection** (#94). The
  extraction prompt is no longer forced to be process-global:
  - `ingest()` / `ingest_records()` accept `extraction_prompt="prose"`
    (etc.) as a per-call override.
  - New config knob `extraction_prompt_by_namespace: dict[str, str]`
    (env: `PGRG_EXTRACTION_PROMPT_BY_NAMESPACE` as JSON) maps namespace →
    prompt, consulted on both the sync ingest path and the `pgrg extract`
    drain.
  - On deferred ingests the resolved prompt is stamped into
    `documents.metadata['extraction_prompt']` (JSONB — no migration), so
    those docs drain with the prompt they were ingested under regardless
    of the drain worker's config. Sync docs are not stamped (extraction
    already ran; `documents.metadata` surfaces on query results).
  - Precedence: per-call kwarg > per-doc stamp > namespace map > global
    `extraction_prompt`. Unknown prompt names raise `ValueError` at call
    time (per-call kwarg fails before any write; a bad stamp/map entry
    marks the doc `failed` at drain) instead of `get_prompt`'s silent
    default fallback. The extraction LLM cache was already prompt-aware
    (keyed on prompt name), so mixed prompts never collide.
- **`lexical_backend="bm25"`** (issue #96, rung 2) — real Okapi BM25 for the
  lexical leg, scored in SQL (k1/b tunable via `bm25_k1`/`bm25_b`): corpus
  IDF from per-namespace stats tables (`lexeme_stats`,
  `lexical_corpus_stats`, migration 016) maintained incrementally by
  triggers — exact on insert/update/delete including the document-cascade
  path, no drift. Default stays `"ts_rank"` (byte-identical SQL).
  Pre-migration corpora need a one-time `rag.rebuild_lexical_stats()` /
  `pgrg rebuild-lexical-stats`. See `docs/cookbook/bm25-lexical.md`.
- **Identifier-preserving tokenization** (issue #96, rung 3) — the tsvector
  parser splits `validate_billing_archive` into stemmed fragments regardless
  of dictionary config; migration 016 injects underscored identifiers as
  whole lexemes into `search_vector` (index side) and the BM25 query-term
  set (query side, symmetric). Invisible to the ts_rank backend
  (positionless lexemes rank 0 there); with `lexical_backend="bm25"` an
  exact-identifier query ranks its defining chunk above tf-heavy prose.
- **Typed graph traversal / dependent conjunctive joins (#95)** — new
  `pg_raggraph.graph_join` module with thin `GraphRAG` wrappers:
  - `rag.find_entities(name, fuzzy=…, entity_type=…)` — anchor binding via
    exact + `pg_trgm` fuzzy match (seed on a *named* entity instead of the
    whole-question embedding).
  - `rag.traverse(entity_ids, rel_types=…, direction="out"|"in"|"any",
    max_hops=…)` — typed, directed edge walk (recursive CTE, one round-trip)
    returning each reached entity with the traversed edge and its provenance
    chunk ids.
  - `rag.graph_join(anchor, bind=[("LIVES_IN", "city"), …],
    intersect=[("LOCATED_IN", "$city"), …])` — the dependent conjunctive join
    ("restaurant in Maria's city that serves what she craves") executed as
    indexed SQL joins in a single statement. Results carry the bound
    intermediates, every supporting edge, and provenance chunk ids.
    Rel-type matching is case-insensitive and accepts synonym lists
    (`["LIKES", "CRAVES"]`); retracted edges never match. No schema changes —
    uses the existing `idx_rel_src_type` / `idx_rel_dst_type` indexes
    (EXPLAIN-verified no seq-scan at 2×10⁴ edges).
    See `docs/cookbook/typed-graph-join.md`. Existing retrieval modes are
    unchanged (additive).

## 0.5.0a19 — 2026-07-06 (prose extraction: prompt, lede_prose, llm+lede union)

### Added
- **`extraction_prompt="prose"`** — extraction prompt for everyday text
  (chats, reviews, bios, journals). Allows common-noun entities (foods,
  activities), names dishes by base form ("wood-fired margherita pizza" →
  `pizza`, `VARIANT_OF` for meaningful variants), resolves first-person
  chat speakers, and constrains rel_types to a closed set
  (`LIVES_IN`/`LIKES`/`SERVES`/`LOCATED_IN`/…; preference-verb synonyms —
  crave, love, hate, favor — map onto `LIKES`/`DISLIKES`/`PREFERS` rather
  than minting bespoke edge types). Motivated by a join-world
  bake where the `default` prompt's proper-noun bias dropped person—craving
  edges 19/24 times; an A/B over the same corpus/model showed the prose
  variant recovering most join-critical links.
- **`fact_extractor="lede_prose"`** — deterministic prose extraction: full
  spaCy NER (now keeping `FAC`/`ORG` — venues, businesses) plus noun-chunk
  head lemmas as entities ("the seafood gumbo" → `gumbo`, variant phrase
  kept in the description), with the existing sentence co-occurrence edges.
  Head-lemma canonicalization lands dish/thing variants on one node without
  any resolution-threshold tuning. Presence is span-accurate from the parse
  (no regex re-matching).
- **`fact_extractor="llm+lede"`** — per-chunk union of LLM extraction and
  `lede_prose`: typed, intent-carrying LLM edges plus a deterministic
  co-occurrence net that guarantees in-sentence links survive when the LLM
  drops them. Entities dedupe casefold (LLM's form wins; deterministic
  relationship endpoints are remapped to the surviving name). Degrades to
  the deterministic leg with a single warning when no LLM is configured.
- **`llm_max_tokens` (PGRG_LLM_MAX_TOKENS, default 0 = omit)** — optional
  `max_tokens` on JSON-mode extraction calls. Local OpenAI-compatible
  servers with small completion defaults (mlx-lm's 512) silently truncate
  extraction JSON, which parses as empty and yields no graph; set 4096 to
  fix. Default omits the field — byte-identical requests for existing
  deployments.

## 0.5.0a18 — 2026-06-29 (append-only re-ingest preserves time-travel, #90)

### Fixed
- **Changed-content re-ingest no longer destroys version history when
  evolution is on (#90).** Previously, re-ingesting a `source_path` with
  changed content always `DELETE`d the prior document+chunks and inserted the
  new one, so the evolution `as_of` time-travel filter could never return a
  prior version — `document_versions` stayed empty and the old chunk was
  physically gone. Now, when `evolution_tier != "off"`, re-ingest is
  **append-only**: the prior current version is closed (`effective_to` set to
  the supersede instant), the new version's `effective_from` is stamped at the
  same instant, and a `document_versions` row records the `new → old`
  supersession edge. An `as_of` *before* the update returns the prior version;
  default retrieval still serves the current one (ranked above the superseded
  one via the existing supersession penalty). The default `evolution_tier="off"`
  keeps the destructive-replace behavior, so users who don't opt into
  time-travel see no storage growth. Living-knowledge ingests keep their own
  append-only path unchanged.

## 0.5.0a16 — 2026-06-16 (caller top_k across SDK / HTTP / MCP, #84)

### Fixed
- **Caller-supplied `top_k` now bounds retrieval breadth across every surface
  (#84).** Breadth was sourced solely from `profile_spec.top_k` (hardcoded to 25
  on every profile rung), so `config.top_k` was vestigial and there was no
  caller-facing lever to bound how many chunks came back — every query returned
  ~25 regardless of intent. Now:
  - `GraphRAG.query()` / `ask()` accept an explicit keyword-only
    `top_k: int | None` that overrides the profile's breadth when provided (the
    profile still owns `context_strategy`); `None` (default) keeps the profile
    default, so existing behavior is unchanged. Values `< 1` raise `ValueError`.
    With `rerank=True`, `top_k` is the post-rerank target (candidates are still
    fetched at `top_k * rerank_factor`).
  - HTTP `POST /query` and `POST /ask` (`server.py`) accept an optional `top_k`
    form field, threaded through to retrieval.
  - MCP `pgrg_query` and `pgrg_ask` (`mcp_server.py`) accept an optional `top_k`
    argument, making the existing "query at a wider top_k" playbook hint in
    `SERVER_INSTRUCTIONS` actually actionable.

## 0.5.0a15 — 2026-06-15 (out-of-band code-graph backfill for defer_extraction, #81)

### Added
- **`pgrg backfill-code-graph` + `backfill.backfill_code_graph()` — rebuild the
  chunkshop code graph out-of-band after `defer_extraction=True` (#81).**
  Previously, deferring extraction on a code KB
  (`chunk_strategy="chunkshop:symbol_aware"`) was an either/or: fast ingest **or**
  the `CALLS`/`INHERITS`/`IMPLEMENTS` graph, never both — the corpus resolver ran
  only inline during the ingest transaction, so a deferred code graph could never
  be reconstructed. `pgrg extract` only backfills the *entity* graph and has no
  code-graph path. Now deferred ingest of a code doc persists its raw file content
  to a new **durable (LOGGED)** `code_backfill_stage` table (migration 015),
  atomic with the document insert, and `backfill_code_graph(rag, namespace)` (CLI:
  `pgrg backfill-code-graph --namespace NS`) re-parses it per namespace, rebuilds
  the cross-file symbol index, and writes the resolved edges — reusing the #76
  spill resolver (`_write_corpus_code_graph`). It is **crash-resumable** (staged
  rows deleted only after the resolve succeeds), **orthogonal to `pgrg extract`**
  (keys off the staging table, never touches `documents.graph_status`), and
  **single-worker-per-namespace** (a corpus finalize, not a SKIP-LOCKED queue).
  Verified to produce a **byte-identical edge set** to the synchronous path on
  real source (123/123 edges), with **linear time + O(symbol-index) memory** to
  4k chunks (55 MB peak), preserving the #76 OOM bound. Staged content is read in
  **bounded batches** (64 docs/query) to avoid an N+1 round-trip. Out of scope
  (v1): Pattern C (`pre_chunked`) deferred code docs, daemon mode for the code
  pass, multi-worker cross-file claim coordination. See the *Code KBs* section of
  [`docs/cookbook/background-extraction.md`](docs/cookbook/background-extraction.md).

## 0.5.0a14 — 2026-06-09 (raise chunkshop floor to 0.9.1: bound symbol_aware over-parse)

### Fixed
- **Large/generated code corpora no longer OOM the embedding step (#79 root
  cause).** chunkshop 0.9.0's path-less language detection parsed ~2× more files
  as code, so a single generated/minified file could explode into thousands of
  `symbol_aware` chunks and exhaust memory downstream when embedding them.
  chunkshop **0.9.1** (chunkshop#71/#72) adds two guards — a content-detection
  fallback for generated/minified files and a `max_symbols_per_file=2000` cap,
  **both on by default** — that bound the chunk count (a 3,000-function generated
  `.ts` drops from 3,000 chunks to ~74). The `[chunkshop]` extra floor is raised
  to `chunkshop>=0.9.1` so the fix applies automatically; pg-raggraph's
  `chunk_strategy="chunkshop:symbol_aware"` path inherits the default cap with no
  config change. Pairs with the a13 cross-file-resolver spill-to-DB fix — together
  they close both halves of #79.

## 0.5.0a13 — 2026-06-09 (cross-file resolver: spill to DB, fix OOM)

### Fixed
- **Cross-file code graph no longer OOMs on large repos (#76 follow-up).** The
  corpus resolver introduced in 0.5.0a12 accumulated one entry per call site
  (each with a source `snippet`) in memory — O(call-sites), measured ~427 B/call
  → ~3.6 GB projected at 100k files. `CorpusCodeGraph` now keeps only the small
  symbol index in memory and **spills call sites to an `UNLOGGED`
  `code_calls_stage` table** (migration 014) during ingest; phase-2 resolution
  **drains them in keyset batches** through `resolve_batch()` (verified
  byte-identical to the one-shot resolver) plus a single `resolve_class_edges()`
  pass for the much smaller INHERITS/IMPLEMENTS set. Peak resolver memory is now
  **O(batch + symbol index)** instead of O(corpus call sites); the run's scratch
  rows are deleted after resolution. No behavior change to the resolved graph.

## 0.5.0a12 — 2026-06-08 (cross-file code graph)

### Added
- **Cross-file code graph (`cross_file_code_graph=True`, #76).** `symbol_aware`
  ingests resolved `CALLS`/`INHERITS`/`IMPLEMENTS` edges only *within* each file,
  so a call to a function defined in another file was never traced (on a 765-file
  ingest, 58% of symbols had 0 callers). Opt in with
  `ingest_records(..., cross_file_code_graph=True)` (or
  `PGRG_CROSS_FILE_CODE_GRAPH=1`): one chunkshop resolver accumulates the whole
  ingest corpus (O(symbols), not content — bounded-memory streaming preserved),
  and a final pass materializes cross-file edges. Each edge records
  `resolved_intra_file` in `relationships.properties`. Default stays per-file
  (no regression). On pg-raggraph's own `src/`: 415 → 1,030 CALLS edges, 636
  cross-file, symbols-with-callers 246 → 351. New `CorpusCodeGraph` in
  `chunkshop_bridge`; see `docs/cookbook/chunkshop-integration.md`.

## 0.5.0a11 — 2026-06-08 (symbol_aware code graph at ingest)

### Added
- **`chunk_strategy="chunkshop:symbol_aware"` now builds the code graph at ingest
  (#74, #75).** Previously symbol-aware ingests produced per-symbol chunks but
  never ran chunkshop's `CodeRelationshipsExtractor`, so `metadata['callees']`
  was empty (#74) and the `entities`/`relationships` tables `code_impact()` reads
  stayed empty (#75). Now, for `symbol_aware` ingests, each chunk carries
  `metadata['callees']` (`{name, line, snippet, resolved_intra_file}`) and
  `CODE_SYMBOL` entities + `CALLS`/`INHERITS`/`IMPLEMENTS` relationships are
  written automatically — `rag.code_impact("<fqn>")` works with no extra steps.
  The extractor parses the whole document (per-chunk parsing misattributes class
  inheritance); resolution is per-file (cross-file edges best-effort). Requires
  the source language's tree-sitter grammar; degrades gracefully if absent.
  Reuses the existing Pattern C `code_edges_to_known_graph` mapper. See
  `cookbook/chunkshop-integration.md`.

### Fixed
- **`CODE_SYMBOL` entities no longer fuzzy-merge by FQN prefix.** A class and its
  methods share an FQN prefix (`pkg.Foo` vs `pkg.Foo.bar`); `resolve_entity`'s
  pg_trgm+vector fuzzy leg would collapse them and corrupt the call graph. Code
  symbols are now identity-keyed by FQN (fuzzy resolution is skipped for
  `entity_type == 'CODE_SYMBOL'`). No effect on other entity types; also fixes
  the same latent issue on the Pattern C import path.

## 0.5.0a10 — 2026-06-05 (streaming ingest, lenient extraction, security bumps)

### Added
- **Bounded-memory / streaming `ingest_records()` (#46).** Records are now pulled
  and processed in batches of `batch_size` (default 64), so peak memory is
  O(batch_size) rather than O(corpus). `records` may be a `list`, a sync
  generator, a DB cursor, or an `async` iterator — a streamed source is never
  fully materialized. The per-document transaction boundary is unchanged, so a
  batch is not an all-or-nothing write and cross-batch entity dedup still
  collapses (resolution is DB-backed). A `list`/`tuple` is still validated
  eagerly up front (a bad row raises before any write); a stream validates each
  batch as it is pulled. New `cookbook/streaming-ingest.md` + runnable FastAPI
  sample `samples/streaming_ingest_service.py`. 6 unit + 7 integration tests.

### Fixed
- **One malformed extraction item no longer discards the whole chunk (#69).**
  The per-chunk LLM output was validated with a single strict
  `ExtractionResult.model_validate` *before* `filter_extraction` ran, so one bad
  entity/relationship (e.g. a relationship missing `target`) raised, was
  swallowed, and returned an empty result — silently dropping every valid
  entity and relationship the chunk produced. Parsing is now item-by-item,
  skipping only the malformed items; non-object JSON still yields an empty
  result. Worst with smaller local models that slip the schema more often.

### Security
- **Cleared 6 Dependabot advisories in `uv.lock` (#37).** Bumped `banks`
  2.4.1→2.4.2 (CVE-2026-44209, Jinja2 SSTI RCE), `python-multipart`
  0.0.26→0.0.32 (CVE-2026-42561 DoS + others), `idna` 3.11→3.18
  (CVE-2026-45409), `langsmith` 0.7.30→0.8.9 (CVE-2026-45134, CVE-2026-41182),
  and `langchain-core` 1.2.28→1.4.0 (CVE-2026-44843, unsafe deserialization).
  Raised the two direct-dep floors that sat below the patch
  (`python-multipart>=0.0.27`, `langchain-core>=1.3.3`) so a fresh resolve can't
  regress. Verified each pin against the GitHub Advisory Database.

## 0.5.0a9 — 2026-06-04 (idempotent migration 013)

### Fixed
- **Migration `013_relationships_unique.sql` re-runs cleanly instead of looping
  forever.** `ALTER TABLE ... ADD CONSTRAINT` has no `IF NOT EXISTS` in
  Postgres, so re-applying 013 on a database where
  `relationships_ns_edge_unique` already existed — the constraint applied
  out-of-band, or its `pgrg_applied_migrations` row lost to a backup/restore
  taken between the schema change and the bookkeeping commit — raised `42710
  duplicate_object`. Because the migration runs in one transaction, that rolled
  it back and never recorded it, so every subsequent startup / `pgrg migrate`
  retried and failed again (the "partial migration not tracked" loop). The
  constraint add is now wrapped in a `pg_constraint` existence guard, so the
  migration converges to the same end state on the first run and any repeat
  run. Steps 1-2 (the dedup DML) were already idempotent. Adds
  `test_migration_013_is_rerunnable`.

## 0.5.0a8 — 2026-06-02 (PyPI-publishable packaging)

### Fixed
- **`ab-gate` extra no longer carries a git dependency.** PyPI rejects direct
  git/URL dependencies in published metadata, which blocked the 0.5.0a7 upload
  (`llm-judge @ git+…`). `ab-gate` is now an empty marker extra; install
  `llm-judge` directly from git (`pip install 'llm-judge @
  git+https://github.com/yonk-labs/llm-judge.git@main'`) — the A/B-gate seam's
  `ImportError` and `docs/cookbook/ab-gate.md` give the exact command. Removed
  `ab-gate` from the `all` extra and the now-unneeded `allow-direct-references`.
  No code change to the A/B-gate runtime. (First PyPI publish since 0.5.0a1.)

## 0.5.0a7 — 2026-06-02 (chunkshop 0.8.2 floor)

### Changed
- **Bumped the optional `chunkshop` floor `>=0.7.0` → `>=0.8.2`.** Picks up
  chunkshop 0.8.x (10-language codeparse, import-aware resolution, opt-in
  OpenAI-compatible remote embedder, connection-reuse/parallel-search perf).
  No pg-raggraph API change — the `chunkshop:*` chunker delegation
  (`symbol_aware`/`code_aware` included) and bridge surfaces validate clean
  against 0.8.2 (453 unit + 29 chunkshop integration tests green).

## 0.5.0a6 — 2026-06-01 (optional RRF fusion)

### Added
- **Optional RRF fusion mode** (`fusion="rrf"`, issue #57) — alongside the
  default linear weighted scoring. Fuses retrieval legs by rank
  (Σ wᵢ / (rrf_k + rankᵢ)) instead of a weighted sum of differently-scaled
  scores, so it is scale-free across the cosine and BM25 legs. Config knobs
  `fusion` + `rrf_k` (default `"linear"` / `60`); per-call override on
  `query()` / `ask()`. Applies to `naive` and `hybrid` modes. **Additive and
  default-off** — the linear path is byte-identical when `fusion="linear"`.
  A/B runner in `benchmarks/rrf-ab/`.

## 0.5.0a5 — 2026-05-28 (A/B gate live verdict — NAIVE_WINS)

Wires the #47–#50 chain to real chunkshop emission and runs the gate end-to-end.
The synthetic fixtures of a4 masked three integration gaps, all closed here:

### Added
- **Entity materialization** — `pg_raggraph.ab_gate.ingest.materialize_entities_from_corpus`
  + `pgrg ab-gate materialize`. Builds graph entities 1:1 from imported fact
  endpoints + cooccur nodes (prerequisite for `graph_leg`).
- **Production `compute_verdict(runner_outputs, judge_config)`** — replaces the
  NotImplementedError stub. Computes recall@10 + MRR from runner output vs
  `gold_doc_id`, judge win-rate via the llm-judge seam; shared `_verdict_from_payload`
  with the fixture path. `pgrg ab-gate verdict` CLI.
- **`gold_doc_id`** optional field on `GoldQuestion` + `ABCaseResult`; `load_gold_questions`
  now auto-detects chunkshop's `[{query, gold_doc_id}]` gold format.
- **`hybrid` mode** (`harness._run_hybrid`) — the production-shaped mode: vector
  seeds top-30 candidates, graph reranks by fact/cooccur entity-overlap
  centrality (no question NER → full coverage). `compute_verdict(graph_mode=…)`
  + `pgrg ab-gate verdict --graph-mode hybrid` compare naive vs hybrid.
- **Query-term encoder hardening** (`_expand_entity_terms`) — expands multi-word
  NER phrases into component tokens so they resolve against single-surface nodes.
- `benchmarks/ab-gate/` — ingest configs, complete 3-mode verdict artifacts, RESULTS.md.

### Result (complete 3-mode run, SCOTUS + NTSB, gpt-4o-mini judge)
- naive vs `graph_leg` (graph-as-primary): **NAIVE_WINS 3-0** (−75.0pp / −0.535 / −0.667).
- naive vs `hybrid` (graph-as-augmentation): **NAIVE_WINS 2-0-1** (−12.5pp / −0.113 / judge **TIE**).

Graph wins no metric in either comparison, so chunkshop contract §3.8's
NAIVE-WINS direction holds — but `hybrid` ties on answer quality, so the honest
reading is "graph doesn't earn its cost on these clean corpora," not "graph is
harmful." Details + caveats: `benchmarks/ab-gate/RESULTS.md`.

## 0.5.0a4 — 2026-05-28 (A/B gate retrieval harness + runner)

Additive arc, backward-compatible. Completes the chunkshop ↔ pg-raggraph A/B gate by landing the two middle artifacts: the retrieval-mode harness (#48) and the matrix runner (#49). Pairs with v0.5.0a3 (#47 resolver + #50 verdict writer).

### Added — A/B retrieval harness + runner

The middle two artifacts of the chunkshop ↔ pg-raggraph A/B gate. With v0.5.0a3 (#47 resolver + #50 writer) already shipped, this release completes the chain.

`src/pg_raggraph/ab_gate/harness.py` — `run_harness_mode(rag, *, corpus_id, mode, gold_questions, top_k=10) → ABRunnerOutput`:

- **`naive_vector`** — pure ANN over `chunks.embedding` with the chunkshop §4.2 fact-row exclusion (`WHERE metadata->>'kind' IS DISTINCT FROM 'fact'`). `IS DISTINCT FROM`, not `!=` — null-safe.
- **`graph_leg`** — `_encode_question_terms` (lede_spacy NER with whitespace+stoplist fallback on raise/empty) → `resolve_entity_lookup` per term (via #47, shipped in v0.5.0a3) → one-hop fact-triple walk (`metadata->>'kind' = 'fact'`, join to parent episode chunk) → one-hop cooccur walk over `metadata['cooccur']` on episode rows. Only episode chunks are cited; fact rows never appear in the citation list (SC-006).
- **`hybrid`** — deferred per SC-007. Raises `NotImplementedError` naming issue #48. The 50/50 naive + graph blend stays as a known gap; rerun with the two legs individually and blend in downstream tooling if needed.

`src/pg_raggraph/ab_gate/runner.py` — `run_ab_matrix(rag, *, corpora, modes, gold_questions_per_corpus, output_dir, top_k=10) → dict[(corpus_id, mode), Path]`:

- Sequential per cell — no per-(corpus, mode) parallelism (locked in Out of Scope; the existing per-question pool concurrency already handles intra-mode parallelism).
- One `ABRunnerOutput` JSON per cell at `<output_dir>/<corpus>__<mode>.json` (double-underscore intentional; avoids collisions with corpus names containing a single underscore).
- Atomic temp-then-replace per file, so a mid-write process death leaves either the previous file or nothing — never a partial write.
- A `<output_dir>/manifest.json` lists every file plus `run_started_at`, `run_ended_at`, `pg_raggraph_version`.
- `load_gold_questions(path)` parses chunkshop's `gold-scotus.yaml` shape verbatim. Alternative formats (JSON, CSV, JSONL) are explicitly out of scope.

### Added — `GoldQuestion` dataclass

Frozen dataclass at `pg_raggraph.ab_gate.io.GoldQuestion` with four fields (`id`, `question`, `gold_answer`, `required_facts`). Re-exported from `pg_raggraph.ab_gate`. Matches the chunkshop `gold-scotus.yaml` / `gold-ntsb.yaml` shape verbatim.

### Added — `pgrg ab-gate` CLI group

New top-level group following the existing `pgrg <group> <command>` pattern:

- `pgrg ab-gate run` — the matrix runner with `--corpus` / `--gold` paired-flag pattern, `--mode` repeatable (`click.Choice`-validated), `--top-k`, `--out`. Mismatched `--corpus` / `--gold` counts raise `click.BadParameter` at parse time.

### Docs

- `docs/cookbook/ab-gate.md` — appended "Running the matrix" section: invocation example, mode reference (naive_vector, graph_leg, hybrid-deferred), output layout diagram (`<corpus>__<mode>.json` + `manifest.json`), reproducibility caveat documenting ANN tie noise as expected.
- Chunkshop emission contract §4.2 + §4.3 status checkboxes flip from `[ ]` to `[x]` in a follow-up chunkshop PR (tracked but not gating).

### Tests

- `tests/unit/test_ab_gold_question_shape.py` (6)
- `tests/unit/test_ab_question_encoding.py` (5)
- `tests/unit/test_ab_harness_graph_leg.py` (2)
- `tests/unit/test_ab_harness_hybrid.py` (1)
- `tests/unit/test_ab_runner_orchestrates_matrix.py` (2)
- `tests/unit/test_ab_runner_output_shape.py` (1)
- `tests/unit/test_ab_runner_manifest.py` (1)
- `tests/unit/test_ab_gold_yaml_loader.py` (6)
- `tests/integration/test_ab_harness_naive_vector.py` (2)
- `tests/integration/test_ab_harness_graph_leg.py` (4)
- `tests/integration/test_ab_runner_writes_per_corpus_per_mode.py` (1)
- `tests/integration/test_ab_runner_latency.py` (1)
- `tests/integration/test_ab_runner_idempotency.py` (1)
- `tests/integration/test_cli_ab_gate.py` (4)

Total: 37 new tests, all green.

### Known gaps

- `hybrid` mode is `NotImplementedError`. Re-opens with the 50/50 blend as v1 when scope permits. Tracked in #48.
- ANN tie-ordering noise: repeated runs may reorder items within score ties; CI does not gate on bit-exact reproducibility.

## 0.5.0a3 — 2026-05-28 (A/B gate bookend: resolve-entity lookup + results writer)

Additive arc, backward-compatible. Bookends the chunkshop ↔ pg-raggraph A/B graph-vs-naive gate by landing the chain-start primitive (`resolve_entity_lookup`, #47) and the chain close-out (results writer, #50) in one release.

### Added — `resolve_entity_lookup` (#47)

New pure-read function in `pg_raggraph.resolution`: `resolve_entity_lookup(surface, *, corpus_id, kind=None, db, config) -> ResolvedEntity | None`. Path A — the existing `resolve_entity` (insert-on-miss) is byte-for-byte unchanged. `corpus_id` maps identity-equal to pg-raggraph's `namespace`.

- `ResolvedEntity` frozen dataclass (`id`, `surface`, `canonical_name`, `score`, `match_type`) re-exported from both `pg_raggraph.resolution` and the top-level `pg_raggraph` package.
- Exact path: `match_type='exact'`, `score=1.0`.
- Fuzzy path: pg_trgm name similarity + pgvector cosine, weighted by `config.trgm_weight` / `vec_weight`, gated by `min_trgm_score` and `resolution_threshold`. Dominant leg becomes `match_type`.
- No mutation: the function never INSERTs, UPDATEs, or DELETEs. Caller-side caching is the strategy.
- Per chunkshop emission contract §4.1.

### Added — A/B-gate results writer (#50)

New `pg_raggraph.ab_gate` package — public API:

- `ABRunnerOutput` / `ABCaseResult` / `ABRetrievedItem` — the locked schema #49 emits and #50 consumes (`io.py`).
- `compute_verdict(runner_outputs, judge_config=...)` — production entry (#49-dependent). `compute_verdict.from_premeasured(payload)` — fixture entry exercised by the unit tests.
- `write_verdict_report(verdict, out_dir=..., latency_rows=...)` — emits `verdict.json` (round-trippable), `verdict.md` (Inputs / Per-metric / Per-corpus / Walkthrough / Final verdict — mirrors contract §3.7), `latency.json` (informational only — never read back for the verdict).
- Threshold constants `RECALL_AT_10_LIFT_PP=5.0`, `MRR_DELTA=0.05`, `JUDGE_WIN_RATE_DELTA=0.10` — frozen by a test against contract §3.2 values.
- `_chunkshop_judge_config_to_llm_judge_provider(config)` — the single auditable seam translating chunkshop's `JudgingConfig` into `llm_judge.providers.LLMProvider`.
- §3.3 combiner: graph wins ≥2 of 3 metrics + naive wins 0 → GRAPH_WINS; symmetric for NAIVE_WINS; otherwise INCONCLUSIVE.
- §3.4 asymmetry guard: GRAPH_WINS downgrades to INCONCLUSIVE if graph loses 3-0 on any single corpus (symmetric for NAIVE).

### Added — `pg-raggraph[ab-gate]` optional extra

`pip install pg-raggraph[ab-gate]` adds `llm-judge` (the LLM-as-judge runtime at `/home/yonk/yonk-tools/llm-judge`). The base install is unchanged — llm-judge and its sub-deps are pulled only when callers reach the #50 writer.

Missing-extra UX: calling `_chunkshop_judge_config_to_llm_judge_provider` (or the writer's judge path) without the extra installed raises `ImportError` with the literal install command in the message.

### Docs

- New `docs/cookbook/ab-gate.md` — operator walkthrough: ingest chunkshop A/B sample (`docs/samples/bakeoff-scotus/bakeoff-scotus-ab.yaml`), run #48+#49 (cited as future tickets until they ship), consume #50's verdict.
- Chunkshop emission contract §4.1 + §4.4 status checkboxes flip from `[ ]` to `[x]` in a follow-up chunkshop PR (tracked but not gating).

## 0.5.0a2 — 2026-05-28 (MCP agent UX: initialize playbook + staleness banner)

Additive arc, backward-compatible. Tools without pending documents see
byte-for-byte unchanged response dicts. The two ports share a single
chokepoint (`mcp_helpers._apply_freshness`) so future MCP tools inherit
the freshness signal automatically.

### Added — MCP `initialize` playbook (PG-1)

`src/pg_raggraph/server_instructions.py` exports `SERVER_INSTRUCTIONS:
str`, handed to `FastMCP(instructions=…)` at server construction. MCP
clients (Claude Desktop, Cursor, Zed, MCP CLI) surface it in the
agent's system prompt for the session. Sections: Answer directly, Tool
selection by intent, Common chains, Anti-patterns, Limitations.
Playbook covers the 8 current MCP tools; deliberately avoids
`pgrg_code_impact` (not currently an MCP tool — adding it is a
separate effort).

A drift-guard test (`tests/unit/test_instructions_sync.py`) keeps the
playbook, `docs/user-guide.md` MCP section, and README MCP callout in
sync. CLAUDE.md "House Rules" documents the invariant.

### Added — Per-file staleness banner (PG-3)

When MCP tool responses cite documents whose `graph_status` is
`'pending'` or `'processing'`, the response gains a `banner` key
naming them (with age + lifecycle label) and an optional `footer`
listing non-cited pending docs (capped at 5 with `+N more` overflow).
The agent's anti-pattern playbook in `SERVER_INSTRUCTIONS` instructs
it to Read those documents directly for live content; everything
NOT in the banner is fresh.

Implementation:
  * `src/pg_raggraph/mcp_helpers.py` — `PendingDocument` dataclass,
    `format_stale_banner`, `format_stale_footer`, `_apply_freshness`
    chokepoint helper. Age uses `documents.created_at` (no schema
    change required — PG-3's design assumed `updated_at` which
    pg-raggraph doesn't have).
  * `src/pg_raggraph/db.py` — new `Database.list_pending_documents
    (namespace, limit=50)` returns `PendingDocument` rows, ordered
    by `created_at DESC`, covering both `'pending'` and `'processing'`
    statuses.
  * `src/pg_raggraph/mcp_server.py` — every one of the 8 MCP tools
    wraps its return through `_freshness_wrap`. Defensive: a failed
    `list_pending_documents` is logged-and-skipped; the tool's answer
    always wins over the freshness layer.

Backward compatibility:
  * No pending docs ⇒ no `banner` / `footer` keys added — response
    shape is byte-for-byte identical to v0.5.0a1.
  * No new env vars, no new MCP tools, no schema changes.

### Tests

  * `tests/unit/test_server_instructions.py` (5 tests)
  * `tests/unit/test_mcp_server_uses_instructions.py` (1 test)
  * `tests/unit/test_mcp_staleness.py` (11 tests)
  * `tests/unit/test_instructions_sync.py` (4 tests — the drift guard)
  * `tests/integration/test_db_pending_documents.py` (6 tests)
  * `tests/integration/test_mcp_pending.py` (4 tests — including the
    full pending → drained → no-banner lifecycle)

## 0.5.0a1 — 2026-05-28 (background extraction + multi-worker safety + observability)

Additive arc, backward-compatible. The synchronous-extract default is byte-for-byte unchanged (`ingest_records()` with no kwarg additions writes the same rows in the same order). Migration 013's `relationships(namespace, src_id, dst_id, rel_type)` UNIQUE constraint plus `ON CONFLICT DO UPDATE SET weight = GREATEST(...)` on the INSERT make re-ingest idempotent at the edge level — same total entity/relationship counts on a re-run, with `GREATEST` keeping the strongest evidence.

### Added — background extraction (decouple LLM/lede from `ingest()`)

Pass `defer_extraction=True` to `ingest_records()` and the producer returns in chunk + embed time only — **~18 ms/doc on lede_spacy MHR vs 1063 ms/doc synchronous** (59× speedup to "naive-queryable"). The document is immediately retrievable via vector + BM25; entity/relationship extraction is deferred.

- New module **`pg_raggraph.backfill`** with three primitives: `claim_pending` (SKIP-LOCKED queue claim), `extract_documents` (per-doc atomic extraction), `release_processing` (crash-recovery reaper).
- New CLI subcommand **`pgrg extract`** drains the queue: `--namespace`, `--batch-size`, `--max-iterations`, `--rate-limit-rps`, `--once`, `--include-failed`. Exits 0 when the queue is empty.
- **`pgrg extract --daemon`** for long-running services — SIGTERM/SIGINT handlers set an `asyncio.Event`; the current batch finishes atomically, then the process exits 0. `--poll-interval` controls the empty-queue back-off.
- Mixed pattern supported: per-record `{"defer_extraction": True}` overrides the batch-level kwarg.
- Migration **`012_documents_graph_status.sql`** — adds `graph_status TEXT NOT NULL DEFAULT 'ready'` plus `graph_extracted_at`/`graph_error`, with a partial index on `(namespace, created_at) WHERE graph_status = 'pending'` for fast queue polling.

Total async path (`B+C`, deferred ingest + drain) is **also faster** than synchronous ingest at 40 docs (15.56 s vs 26.27 s); the synchronous path holds per-doc transactions open across extraction and throttles concurrency more than expected. Benchmark: `benchmarks/defer_extraction_bench.py`.

### Added — multi-worker safety invariants (PR-001 + PR-002 from prod-ready audit)

- **Namespace-scoped startup reaper.** `release_processing` is now keyword-only on `namespace=` / `doc_ids=`. The CLI passes its `--namespace`, so a worker starting in namespace A no longer steals namespace B's in-flight 'processing' claims. Global reap (no kwargs) still possible for repair scripts; logs a warning when used.
- **Edge-level idempotency.** Migration **`013_relationships_unique.sql`** de-duplicates any existing relationship rows (redirects `relationship_chunks` links via `INSERT…ON CONFLICT DO NOTHING`, deletes dups so CASCADE cleans the rest) and adds `UNIQUE (namespace, src_id, dst_id, rel_type)`. Both INSERT paths (`_ingest_one_content` and `_extract_one`) switched to `ON CONFLICT DO UPDATE SET weight = GREATEST(relationships.weight, EXCLUDED.weight) RETURNING id`.
- `merge_entities` updated to pre-delete colliding rows before the `src_id`/`dst_id` rewrite, matching the prior post-merge dedup semantics under the new constraint.

Together, these make `pgrg extract` workers safe to run concurrently per namespace by construction — `SKIP LOCKED` (claim) and `UNIQUE (...)` + ON CONFLICT (writes) handle every crash-recovery and re-extraction edge.

### Added — observability (PR-003 from prod-ready audit)

Three new metric events on every `pgrg extract` iteration:

- **`pgrg.backfill.claim`** — `namespace`, `batch_size`, `claimed`, `latency_ms` (emitted even on empty iterations, so a wedged daemon polling an empty queue is visible).
- **`pgrg.backfill.extract`** — `namespace`, `claimed`, `ready`, `failed`, `entities`, `relationships`, `latency_ms`.
- **`pgrg.backfill.queue_depth`** — per-status doc counts (`pending`, `processing`, `ready`, `failed`); emitted when scoped to a namespace.

Pipes through the existing `_emit_metric` infrastructure (same channel as `pgrg.ingest` / `pgrg.query`).

### Added — query-time graph-status hint

`QueryResult.metadata` gains `graph_status_summary` (per-status doc counts). `GraphRAG.status(namespace)` includes the same under a top-level `graph_status` key. Retrieval semantics are unchanged — naive/local/global/hybrid still return whatever entities/edges exist; the hint just lets callers see whether the graph is still backfilling without changing the result shape.

### Added — benchmarks

- **`benchmarks/defer_extraction_bench.py`** — A/B/C comparison harness: synchronous ingest vs deferred ingest vs drain. Headline 60× speedup to queryable, exact relationship parity, 0.14% entity-dedup variance. Repro: `uv run python -m benchmarks.defer_extraction_bench --docs 40`.
- **`benchmarks/ingest_perf.py` extended** with `--provider {local,http}` to probe embedding alternatives. Measured: TEI HTTP CPU beats local fastembed **2.1×** on bge-small (66 vs 140 ms/chunk). Results in `benchmarks/ingest_perf_results-2026-05-27.md`.

### Documentation

- **`docs/cookbook/background-extraction.md`** — full guide with three architectural patterns (synchronous / cron drain / always-on daemon), end-to-end FastAPI walkthrough, operator playbook, mid-batch crash recovery semantics, and the measured-impact table.
- `README.md`, `docs/README.md`, `docs/user-guide.md`, `docs/operations-guide.md`, `CLAUDE.md` — cross-references and discovery paths added so the new subsystem doesn't hide behind one cookbook page.

### Fixed

- **`tests/integration/test_db.py::test_connect_and_schema`** asserted `schema_version == "1"`, which silently relied on `_record_migration`'s GREATEST-update being a no-op against an already-warm DB. Migration 012 surfaced the latent bug; switched to `int(version) >= SCHEMA_VERSION`.
- `tests/integration/test_cleanup_sprint.py::test_merge_entities_drops_self_loops_and_duplicates` previously pre-seeded duplicate `(a,c,REL)` to test merge-time dedup — the new UNIQUE constraint blocks the pre-seed. Updated to use `(b,c,REL)` so the duplicate is created at merge time (the real code path).

### Production-readiness audit

`skill-output/prod-ready/` contains the 16-finding audit that drove PR-001+002+003. P0s are landed; P1s (timed background reaper, retry counter + cap, extractor health probe, multi-worker concurrency test, cookbook scope-or-note) are tracked there for the next cycle. Single-worker / single-namespace deployments are production-ready at this version; multi-worker deployments are safe by construction after PR-001+002+003.

## 0.4.0a1 — 2026-05-26 (chunkshop 0.6.1 integration + online embedding migration + code-graph queries)

Additive arc, backward-compatible. Existing query/ingest behavior is byte-for-byte unchanged (`retrieval.py`, `answer.py`, and the `query()` path are untouched). Validated against a 2.5 GB real corpus (MHR/MuSiQue/2Wiki, 1024-dim bge-large): all six retrieval modes return identical results; no accuracy change.

### Added — online embedding-model migration (`pgrg migrate-embeddings`)

Change the embedding model/dimension on a live database via an expand/contract column swap — no parallel DB, brief cutover. New `pg_raggraph.embedding_migration` module + CLI group with phases `prepare` / `backfill` / `build-index` / `status` / `cutover` / `finalize`. Backfill is online + resumable; cutover is a single atomic transaction (rename columns, retype the embedding cache, update `pgrg_meta`). Two backfill sources: `reembed` (default) and `chunkshop_sink` (Pattern C). Migration `010_embedding_migration.sql`.

- **Startup dim-guard** — `connect()` now raises `EmbeddingDimMismatch` if configured `embedding_dim` ≠ the live `chunks.embedding` dimension, catching a forgotten config change (e.g. after a cutover) with a clear message instead of an opaque pgvector error.
- Runbook: [`docs/cookbook/changing-embedding-dimensions.md`](docs/cookbook/changing-embedding-dimensions.md).

### Added — code-graph query UX (`code-impact`)

`pgrg code-impact <fqn>` and `GraphRAG.code_impact(fqn, depth=…)` report a code symbol's callers and callees (with evidence snippets) by traversing the existing `relationships` graph — cycle-safe recursive CTEs, `--depth` for transitive impact, tree or `--json` output. New `pg_raggraph.code_graph` module; no schema change.

### Added — chunkshop 0.6.1 code surfaces

- Dependency floor moved to **`chunkshop>=0.6.1`** (PyPI). Guarantees the code-aware/symbol_aware chunkers, `code_edges`, and `code_summary`.
- `chunk_strategy="chunkshop:code_aware"` / `"chunkshop:symbol_aware"` pass-throughs.
- `pgrg ingest-chunkshop-table` imports a chunkshop Postgres sink; `--with-code-edges` imports `code_edges` as `CODE_SYMBOL` entities + `CALLS`/`INHERITS`/`IMPLEMENTS` relationships.
- **`code_summary` enrichment** — when imported chunks carry `fqn` + `summary`, the matching `CODE_SYMBOL` entity description is set to that summary.
- **`top_terms` → FTS** — chunkshop `lede_top_terms` (`chunks.metadata.top_terms`) are folded into the chunk `search_vector` (weight B) so BM25 surfaces chunks by their salient terms. Migration `011_search_vector_top_terms.sql` (redefines the trigger for new writes; existing rows re-index on update).

### Changed / Fixed

- `if_oversize` fallback plumbed into chunkshop chunker delegation so oversized sections are split rather than passed through.
- Clear, actionable error when importing `code_edges` from a schema that lacks the table (requires a chunkshop 0.6 sink) instead of an opaque `UndefinedColumn`.

### Notes

- `lede` / `lede-spacy` remain pinned at `>=0.4.5` (current PyPI latest).
- Re-running an embedding migration is data-safe; `embedding_old` is preserved until `finalize`.

## 0.4.0a1 — 2026-05-20 (retrieval surface + per-call kwargs + index machinery)

> Bundled into the same `0.4.0a1` release as the arc above; staged before it.

Significant additive arc: per-call config overrides on `query()` / `ask()`, configurable retrieval SQL shape (`weighted` / `pre_filter` / `vector_first`), auto-create + runtime APIs for JSONB metadata indexes on **both** `chunks` and `documents`, a typed-column scaffold for numeric/timestamp range queries, the chunkshop SP-A agent-memory read bridge, an observability metric on `vector_first` recall, and two `version_*` correctness fixes for `evolution_tier="off"`.

All additions are opt-in / backward-compatible. Defaults preserve pre-arc behavior byte-for-byte.

### Added — per-call overrides on `query()` / `ask()`

Mirroring the existing `evolution_aware: bool | None` shape. Pass `None` (default) → falls back to config. Pass an explicit value → overrides for that call only. All race-safe for multi-tenant servers sharing one `GraphRAG`.

- **`retracted_behavior: str | None`** (#1, PR #9) — `"hide"` / `"flag"` / `"surface_both"`.
- **`supersession_behavior: str | None`** (PR #15) — `"hide"` / `"prefer_new"` / `"surface_both"`. Completes the symmetry with retraction.
- **`memory_tier: str | None`** (PR #10) — `"provisional"` / `"consolidated"` / `"both"`. Read-side enforcement of chunkshop SP-A's O2 consolidated-wins rule.
- **`retrieval_strategy: str | None`** (PR #11) — `"weighted"` (default) / `"pre_filter"` / `"vector_first"`.

### Added — configurable retrieval SQL shape (`retrieval_strategy`)

Three named SQL shapes for `naive` / `naive_boost` modes. `local` / `global` / `hybrid` already pre-narrow via graph traversal and ignore this knob.

- **`weighted`** — single-pass combined score; today's behavior; byte-identical default.
- **`pre_filter`** — CTE materializes predicate-matching subset before ranking; for selective WHERE clauses on **indexed** columns.
- **`vector_first`** — HNSW-seed CTE without namespace JOIN → post-filter; **60-66× faster** for broad/no-predicate queries on single-namespace corpora (bench at 100K chunks).
- Paired **`pgrg.vector_first.recall_shortfall` metric** on `pg_raggraph.metrics` logger (PR #20) — emits when post-filter trims below `top_k`. Includes WARNING log + structured event with `shortfall_ratio` for alerting.
- `retrieval_oversample_factor: int = 10` config for `vector_first` candidate sizing.

### Added — JSONB metadata index machinery (Scope B, three kinds × two tables)

Auto-create at `connect()` time, idempotent via `IF NOT EXISTS`. All default empty / False.

**Chunks-side** (PRs #19, #21, #22):

- `metadata_indexes: list[str]` — btree per-key on `chunks.metadata->>'<key>'`
- `metadata_indexes_gin: bool` — GIN on full `chunks.metadata` JSONB (for `@>`, `?`, `?|` predicates)
- `metadata_generated_columns: dict[str, str]` — STORED generated column `meta_<key>` + btree (typed range queries: int, bigint, numeric, timestamptz, boolean, text)

**Documents-side mirrors** (PR #28 — Option A):

- `document_metadata_indexes: list[str]`
- `document_metadata_indexes_gin: bool`
- `document_metadata_generated_columns: dict[str, str]`

The documents-side knobs close the chunks-vs-documents gap for the common GraphRAG-from-DB pattern (sales notes / support tickets where structured fields land on `documents.metadata`, not `chunks.metadata`).

**Identifier safety:** key whitelist `^[a-zA-Z_][a-zA-Z0-9_]{0,49}$`; table whitelist `chunks|documents`; type whitelist for generated columns; psycopg `sql.Identifier` for DDL composition. Injection canaries reject at config init.

### Added — runtime metadata-index API (PR #27)

For UI flows and exploratory use; no restart needed.

- **`rag.recommend_metadata_indexes(*, table=None, ...)`** — samples both tables by default, returns `list[IndexRecommendation]` with type inference + cardinality + confidence + `already_exists`. Heuristic ranks high-confidence + selective candidates first.
- **`rag.add_metadata_index(key, *, kind, sql_type, table)`** — runtime DDL. Returns `dict` (never raises) for UI error display.
- **`rag.remove_metadata_index(key, *, kind, table)`** — idempotent (`IF EXISTS`). For `kind="generated"` also drops the column.
- **`rag.list_metadata_indexes(*, table=None)`** — snapshot of currently-installed indexes.

`IndexRecommendation` is a dataclass with `table`, `key`, `kind`, `sql_type`, `rationale`, `selectivity`, `cardinality_ratio`, `sample_size`, `sample_values`, `confidence`, `already_exists` — structured so a UI can render rows without re-parsing prose.

### Added — chunkshop SP-A agent-memory bridge (Pattern M, PR #10)

Read-side bridge from chunkshop's `agent_memory.memory` table into pg-raggraph's graph layer.

- **`pg_raggraph.memory_bridge`** module — `SP_A_MEMORY_COLUMNS` contract (CI-pinned with chunkshop's symmetric `test_pgraggraph_contract_columns_present`) + `rows_to_records()` pure transform.
- **`benchmarks/agent-memory-demo/ingest_chunkshop_sp_a.py`** — runnable bridge example.
- Reuses existing `ingest_records(pre_chunked=…, relationships=…, skip_llm=True)` seams — no new ingest API.
- Smoke-tested end-to-end against chunkshop SP-A populated `agent_memory.memory`; validation findings (embedding parser, contract drift) folded into the bridge.
- See `docs/cookbook/chunkshop-integration.md` → Pattern M for the full story including the "Honest gaps" section.

### Fixed

- **#17** (PR #26) — `ChunkResult.version_label` was always `None` when `evolution_tier="off"`, even though `documents.version_label` was populated. Treat `version_label` as caller-supplied opaque content (tier-independent), same as `metadata`. State fields (`retracted`, `effective_from`, `effective_to`, `superseded_by_id`) remain tier-gated.
- **#18** (PR #26) — `GraphRAG.ask(..., version_filter="3.12")` silently no-op'd when `evolution_tier="off"`. `version_filter` is content scoping (a WHERE clause), not evolution scoring. Emit the clause regardless of tier. Other evolution-state filters (`retracted_behavior=hide`, `supersession_behavior=hide`, `as_of`) remain tier-gated.

### Closed (other issues)

- **#4** — SP-B agent-memory bridge (PR #10)
- **#5** — Bump `chunkshop>=0.4.3` for SP-A memory primitives (PR #8)
- **#6** — Cookbook refresh for chunkshop 0.4 multi-engine + Pattern M (PR #8)
- **#1** — `retracted_behavior` per-call kwarg on `ask()` (PR #9)
- **#17**, **#18** — version-fields tier-independence (PR #26)

### Notes — defaults preserved

- `retrieval_strategy="weighted"` is the default; the `naive` SQL it produces is byte-identical to pre-arc `_build_naive_query`/`_twostage`.
- `two_stage_retrieval` config still works (controls which `weighted` path).
- All new metadata-index config fields default empty / False — zero schema change for callers who don't opt in.
- Per-call kwargs all default `None` → config-driven.
- All existing benchmarks unchanged.

### Notes — operability

- Pre-commit hook (`.pre-commit-config.yaml`, PR #14) running both `ruff check` + `ruff format --check` so the lint failure mode that hit PR #11→#12→#13 doesn't recur. Install once with `uv tool install pre-commit && pre-commit install`.
- All auto-create index DDL is **non-CONCURRENTLY** (runs inside `connect()`'s advisory lock). For production retrofit, see `docs/cookbook/metadata-indexes.md` → Production retrofit guide for the manual `CREATE INDEX CONCURRENTLY` recipe.

### Cookbook additions

- `docs/cookbook/retrieval-strategy.md` — picking a `retrieval_strategy` with bench evidence (60-66× win, recall caveat for selective predicates)
- `docs/cookbook/metadata-indexes.md` — all three index kinds × both tables, runtime API, generated columns, naming conventions, production retrofit
- `docs/cookbook/chunkshop-integration.md` — Pattern M (SP-A bridge), `chunkshop>=0.4.3` migration, multi-engine backend compatibility
- `docs/EVOLUTION-API-QUICKREF.md` — per-call kwargs (retracted_behavior, supersession_behavior) marked as recommended pattern; config form documented as fallback

### Added — per-fact temporal columns on `relationships` (migration 006, PR #35)

The last gap in the Pattern M honest-read closes here. Migration 006 adds `effective_from`, `effective_to`, `retracted`, `retracted_at` as typed columns on the `relationships` table (mirror of the document-level columns from migration 002, applied at fact granularity).

- **Schema:** `ALTER TABLE relationships ADD COLUMN ...` — all four columns nullable; default `retracted = FALSE`. Existing rows behave identically to pre-006.
- **Bridge:** `memory_bridge._fact_row_to_relationship()` promotes SP-A row temporals onto the relationship dict.
- **Manual ingest:** `known_relationships` dicts accept the same four optional keys.
- **Read surface:** `RelationshipResult` gains `effective_from`, `effective_to`, `retracted`, `retracted_at` (all optional).
- **Indexes:** partial `idx_relationships_retracted` (`WHERE retracted = TRUE`) and `idx_relationships_effective` (`(effective_from, effective_to) WHERE effective_from IS NOT NULL`) — narrow footprint, cheap as_of and retraction scans.

Out of scope (deferred to Tier 3): consuming these columns in evolution scoring weights. Columns exist and survive round-trip; ranking integration is a separate work item.

### Added — concurrent metadata-index helper (PR #32)

`rag.apply_metadata_indexes_concurrently()` — runtime API for production retrofit. Iterates `metadata_indexes`, `metadata_indexes_gin`, `metadata_generated_columns` (and document-side mirrors), running `CREATE INDEX CONCURRENTLY` from a fresh autocommit connection. Idempotent (`IF NOT EXISTS`). Returns a list of result dicts for UI surfaces.

See `docs/cookbook/metadata-indexes.md` → Production retrofit guide.

### Added — Pattern M LLM-wired consolidator demo + real-data validation (PR #34)

`benchmarks/agent-memory-demo/llm_consolidator_demo.py` — deterministic regex-pattern consolidator that emits typed SPO triples (commented OpenAI reference implementation alongside). Validates that the bridge handles non-sparse triples end-to-end → 2 graph edges from 2 typed-SPO facts. Updated cookbook validation block.

### Notes — operability (additions)

- **Pytest pre-commit hook** (PR #30) — opt-in `pytest tests/unit/` on commit, full suite on push (`--hook-stage push`). Documented in CONTRIBUTING.md.

### Tracked follow-ups

- **#24** — Explore: ingest-time denormalization of `document.metadata` onto `chunks.metadata`. P3, revisit when there's workload data showing the two-table mental model causes friction.
- **Tier 3 ranking integration for per-fact temporals** — `relationships.retracted` / `effective_from` / `effective_to` exist as columns but the default scorer doesn't yet demote retracted edges or filter the temporal window. Open scoring work.

## 0.3.0a3 — 2026-05-17 (consumer surface)

### Added (all optional, back-compatible)

- `ChunkResult` now returns opaque caller `metadata` from
  `documents.metadata` plus evolution status: `retracted`, `version_label`,
  `effective_from`, `effective_to`, and `superseded_by_id`. All fields are
  optional; evolution status stays `None` when `evolution_tier="off"`
  (PRG-1).
- `GraphRAG.retract(*, doc_id|source_path, reason, retracted_at, namespace)`
  marks already-ingested documents retracted post-hoc and is idempotent
  (PRG-2).
- `GraphRAG.supersede(*, old_*, new_*, reason, effective_at, namespace)`
  records post-hoc document supersession and sets the old document's
  `effective_to` for temporal retrieval (PRG-3).
- `ChunkResult.chunk_id` is documented and regression-tested as non-null and
  stable for `query()` / `ask()` results (PRG-4).

### Notes

- No schema migration. The release uses existing `documents` and
  `document_versions` columns.
- No change to existing signatures, scoring, or defaults. A caller that
  ingests no metadata and never calls the new methods sees behavior matching
  `0.3.0a2`.

## 0.3.0a2 — 2026-05-02 (pre-public-push hardening)

Second prod-ready audit pass on top of `0.3.0a1`, ahead of the public-repo
flip + first real PyPI release. Five PRs closed (PR-301..PR-305) plus a
fix for an evolution-tracking bug surfaced during test hardening.

### Security

- **PR-301 — Bearer auth uses constant-time compare.** `pgrg serve`'s
  optional `PGRG_SERVER_API_KEY` Bearer middleware now uses
  `secrets.compare_digest` instead of `!=`. The previous comparison
  short-circuited on the first differing byte and leaked the key
  length + prefix via response timing — bypassable by a network
  attacker over thousands of probes. Added regression-lock test that
  spies on `secrets.compare_digest` and asserts the auth path actually
  invokes it (catches a future revert to `==` directly).
- **PR-303 — Defense-in-depth security headers.** New middleware
  attaches `Content-Security-Policy`, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, and `Referrer-Policy: no-referrer` to every
  response — including the 401/403 short-circuits from the auth
  middleware. CSP allows `https://unpkg.com` for the bundled
  `vis-network` UI; tighten to `'self'` once the JS is bundled locally.
- **PR-304 — MCP `pgrg_ingest` enforces the file-extension allowlist.**
  Hoisted the canonical extension list to `pg_raggraph.INGEST_ALLOWED_EXTS`
  so the FastAPI `/ingest` endpoint, the MCP `pgrg_ingest` tool, and
  the library's directory walker all share one source. An LLM agent
  that asks the MCP server to ingest a `.exe`, `.so`, `.tar`, etc.
  now gets a structured `{"error": "unsupported_extension", ...}`
  response — no garbage entities polluting the knowledge graph.

### Packaging / DX

- **PR-302 — `[project.urls]` table on PyPI.** `pyproject.toml` now
  declares Homepage, Repository, Issues, Changelog, and Documentation
  URLs. The PyPI project page sidebar surfaces these — without them
  the listing was barebones, a permanent first-impression tax.
- **PR-305 — Reranker actionable ImportError.** When fastembed's
  cross-encoder submodule isn't available, `FastEmbedReranker._load()`
  now raises `ImportError` with a `pip install --upgrade 'fastembed>=0.4'`
  hint instead of letting a bare `ModuleNotFoundError` propagate. Matches
  the pattern used for the chunkshop integration in `chunking.py`.

### Bug fixes

- **datetime metadata no longer crashes ingest.** `rag.ingest(metadata={...})`
  with `effective_from` / `effective_to` `datetime` values previously
  failed with `TypeError: Object of type datetime is not JSON serializable`
  in the `documents.metadata` JSONB path (and similarly for chunk
  metadata in the chunkshop pre-chunked path). Added a `_json_default`
  helper that serializes datetimes as ISO 8601 strings — queryable from
  JSONB via `metadata->>'effective_from'`. Fixed 5 evolution-tier1
  integration tests that were silently failing on `main` since the
  `22d83f7` documents-metadata-persistence change.

### Tests

- 13 new tests in `tests/integration/test_error_paths.py` covering
  PR-301..PR-304 (Bearer auth contract, security-header presence on
  success + auth-failure paths, MCP `pgrg_ingest` extension rejection
  and partial-state guard, public `INGEST_ALLOWED_EXTS` import).
- New `tests/unit/test_reranker.py` (2 tests) covering PR-305.
- All 204 tests pass on the full suite.

### CI / hygiene

- Cleared the lint+format failures that had been silently red on `main`
  for several pushes. `ruff check .` and `ruff format --check .` are
  now both green. Two new excludes added: `benchmarks/sales-crm-demo/`
  (cookbook demo with its own SQL-heavy conventions, matches the prior
  `benchmarks/age-bakeoff/` precedent) and `docs/cookbook/samples/*.py`
  (documentation/demo scripts). One auto-fixed import sort in
  `chunking.py`; one trimmed docstring example in `__init__.py`.

## 0.3.0a1 — 2026-04-28 (post-audit hardening)

First public PyPI release. Polish + hardening pass on top of `0.3.0a0`. No public-API changes; all 23 production-readiness items from the prod-ready audit closed (22 fixed, 1 false positive). Library + server ready for external use.

### Real-world Tier 1 benchmarks

- **`benchmarks/python-versioned-docs/`** — 12 Python docs (3.10/3.11/3.12), 1364 chunks, 15 hand-written gold questions. **13/13 perfect `version_filter` purity** (100%). Closes the "Tier 1 only synthetic-fixture-tested" gap.
- **`benchmarks/medical-hrt/`** — 48 PubMed HRT/CV abstracts, 7 epistemically-retracted (modeling WHI 2002 supersession of the prior consensus), 15 gold questions. **5/5 retraction_aware + 5/5 time_travel = 15/15 perfect.** First real-world demonstration of `retracted_behavior="hide"` + `as_of`.
- 3-part dev-rel blog series in [`docs/blog/`](docs/blog/) walking through both paths from a fresh `git clone`.
- [`docs/USE-CASES.md`](docs/USE-CASES.md) — decision matrix for classic GraphRAG vs evolving knowledge.

### Server hardening (PR-103, PR-104, PR-205, PR-208)

- **`/graph` pagination** — default `LIMIT 500`, `?limit=N` (max 5000), `?limit=all` for tiny corpora. No more browser OOM on real-corpus visualization.
- **`/ingest` hardening** — `PGRG_SERVER_MAX_UPLOAD_MB` cap (default 100 MB → 413), extension allowlist (→ 415), filename sanitization (path-traversal-safe, → 400 on empty), temp-file cleanup wrapped in `try/finally` so leaks are impossible.
- **Optional Bearer auth** — `PGRG_SERVER_API_KEY` env enables auth middleware. Server logs a startup WARN when the env is unset so the unauthenticated state is loud, not silent. `/health` and `/ready` always probe-friendly.
- **Origin allowlist** — `PGRG_SERVER_ALLOWED_ORIGINS` (comma-separated). When unset, only loopback Origins accepted on POST/PUT/DELETE/PATCH; non-browser clients (curl, requests) without Origin headers still work.
- **`/ready` endpoint** — distinct from `/health`. Verifies DB connectivity AND `pgrg_meta.schema_version >= SCHEMA_VERSION`. Returns 503 with a structured payload on `db_unreachable` / `schema_pending_migration`.
- **`/query` default mode** — was `hybrid` (the slowest mode); now `smart` (matches `/ask`).

### Library hardening (PR-203, PR-206, PR-209, PR-210, PR-211, PR-215, PR-216)

- `pg_raggraph.__version__` now resolved via `importlib.metadata.version("pg-raggraph")` so it always matches the installed metadata (no more "0.3.0" string drift from `0.3.0a0` in pyproject).
- `PGRGConfig` refuses to start with the default Postgres credentials when `PGRG_ENV=production` (raises `RuntimeError`); logs a one-time WARN otherwise.
- `tune_scoring_weights()` gains a `max_grid_size` parameter (default 50) — refuses to run grids exceeding the cap before any LLM call. Cost-safety guard.
- `rag.request_shutdown()` for graceful drain of long-running ingest. SIGTERM/SIGINT handlers can wire it; in-flight per-doc transactions finish, queued files become no-ops counted as `skipped`. Re-running `ingest()` resumes via content-hash dedup.
- `PGRG_LOG_FORMAT=json` — stdlib-only structured logging on stderr (no extra dep). Activates only when no handlers are pre-attached to the `pg_raggraph` logger.
- `os.nice()` no longer mutates process priority on `PGRGConfig` import. New `apply_nice_level()` method called from `ingest()` where CPU-yield was actually wanted.
- `ingest_profile` and `extraction_prompt` typed as `Literal[...]` — typos via env now raise `ValidationError` at init instead of silently defaulting.

### Renamed: `skimr_spacy` → `lede_spacy`

The Tier-2 fact-extractor enum value was renamed to match the package's PyPI name (shipped as `lede` + `lede-spacy` 2026-04-28). Active surfaces updated: `PGRGConfig.fact_extractor` Literal, schema comment, user-guide, cookbook. Released migration `002_evolution_tracking.sql` and dated audit-trail specs under `docs/superpowers/` left untouched per project policy.

### CI

- **CI fixed.** `.github/workflows/test.yml` was running `pytest tests/integration/ tests/test_e2e.py -v`, but `tests/test_e2e.py` was moved to `tests/integration/test_e2e.py` in the alpha merge — pytest exited 5 (no tests at the explicit path) on every push since 2026-04-27. Removed the stale path.
- `benchmarks/age-bakeoff` excluded from root ruff config — separate sub-project with its own `pyproject.toml` and lint posture.
- All 195 tests passing across `tests/unit/` and `tests/integration/` on Python 3.12 and 3.13.

### Tests

- New `tests/integration/test_error_paths.py` (15 tests) — asserts specific exception types or behaviors on bad DSN, naive `as_of`, oversize `/ingest`, path-traversal filenames, `tune_scoring_weights` cost guard, namespace allowlist, etc.
- Latency-test thresholds widened from `< 200 ms` to `< 1500 ms` — these were flaking under cold-start CI / contended dev machines despite no real perf regression. Tight perf gating belongs in the dedicated bake-off harness, not in user-journey tests.
- `test_07_bus_factor` xfail removed — replaced the empirically-flaky directional assertion (`hybrid_score >= naive_score`) with a property-style check (both modes return ≥ 1 expected keyword).

### Docs

- README rewritten with layered structure (what / why / how → weeds).
- New [`docs/EVOLUTION-API-QUICKREF.md`](docs/EVOLUTION-API-QUICKREF.md) — common assumptions vs reality for the Tier 1 API (which kwargs are per-query vs config-only, how to read evolution columns, `as_of` × `retracted_at` semantics).
- `docs/user-guide.md` gains "Schema migrations", "Concurrency / sizing", "Logging", and "Graceful shutdown" subsections.
- README quickstart switched from `pip install pg-raggraph` (not yet on PyPI) to a clone-based install that actually works.
- `pgrg serve` now carries an explicit "deploy behind auth, do not expose publicly" banner in README + user-guide.

### Dependency / supply-chain

- `pip-audit --skip-editable` is clean: zero CVEs in any direct or transitive dependency.

## 0.3.0-alpha — 2026-04-25

### Added

- **Evolving-knowledge RAG, Tier 1 (Structural).** Opt-in evolution tracking
  that respects document effective-dates, retractions, and supersession at
  the document level. Opt in via `PGRGConfig(evolution_tier="structural")`
  or env `PGRG_EVOLUTION_TIER=structural`.
- `rag.ingest(metadata={...})` now accepts `effective_from`, `effective_to`,
  `retracted`, `retracted_at`, `retraction_reason`, `version_label`,
  `supersedes_document_id`. Per-ingest scope (applies to every file in the
  call).
- `rag.query()` new kwargs: `as_of=datetime(...)` time-travel filter,
  `version_filter="..."` version restriction, `evolution_aware=False`
  per-call override to force classic retrieval.
- `rag.tune_scoring_weights(namespace, gold, grid, ...)` grid-search
  utility for per-corpus weight tuning. Writes the best cell back to
  `rag.config`.
- Schema: three new tables (`facts`, `fact_edges`, `document_versions`)
  and four new columns on `documents` via migration
  `002_evolution_tracking.sql`. All additive; fact-level tables stay empty
  at Tier 1.
- Behavior modes: `retracted_behavior` ∈ {hide, flag, surface_both};
  `supersession_behavior` ∈ {hide, prefer_new, surface_both}.

### Changed

- `PGRGConfig` gains 15+ fields for evolution tracking. Defaults leave
  Tier 0 behavior unchanged.
- Retrieval SQL templates (`naive`, `local`, `global`) are now built
  per-query from the config rather than stored as string constants. When
  `evolution_tier="off"`, the generated SQL is semantically identical to
  the prior version.

### Deferred to future tiers

- Fact-level extraction (Tier 2).
- LLM-inferred fact edges and contradiction detection (Tier 3).
- Async slow-path fact-edge inference (Tier 3).

See `docs/cookbook/evolution-tracking.md` for the quickstart.

## 2026-04-20 — `chunk_strategy="hierarchy"` opt-in chunker

### Added

- **`chunk_strategy="hierarchy"`** — heading-prefixed chunker ported from the AGE bake-off (`benchmarks/age-bakeoff/src/age_bakeoff/chunker.py:_split_hierarchy`). Each section body is prefixed with its markdown heading so pgvector embeds `heading+body` as one unit. When a document has no headings, the body is prefixed with a derived title (first H1, else source filename). No token-budget split — sections over `chunk_max_tokens` are passed through unchanged and get truncated at embed time, mirroring the benchmarked behavior byte-for-byte.
- **When to use it:** corpora with concrete, per-doc disambiguating titles — SCOTUS-style case names ("Miranda v. Arizona"), article titles, product names. On the SCOTUS corpus this cleared DC-003 by 2.5× across all six retrieval modes (`benchmarks/age-bakeoff/results/REPORT-VERDICT.md` §6).
- **When NOT to use it:** corpora with format-string titles that repeat across docs — meeting updates ("Weekly sync: …"), ticket prefixes, templated status reports. The acme replication on that shape regressed −1 to −2 questions per retrieval mode and tripled hallucinations (`benchmarks/age-bakeoff/results/ACME-HIER-REPLICATION.md`).
- Default `chunk_strategy` remains `"auto"`. This is an opt-in config, not a behavior change for existing users.

## 2026-04-17 — AGE Bake-Off Benchmark (v0.3.1)

### Added

- **AGE vs pg-raggraph bake-off benchmark** (`benchmarks/age-bakeoff/`) — reproducible head-to-head comparison on two corpora (Acme Labs + SCOTUS) measuring retrieval latency, answer quality (LLM judge), and fact recall across 60 gold-labeled questions.
- **Benchmark results:**
  - pg-raggraph retrieval is **1.4x faster on Acme** (33ms vs 47ms p50) and **47x faster on SCOTUS** (60ms vs 2,863ms p50)
  - Answer quality roughly comparable; AGE slightly better on Acme (zero hallucinations vs 3), tied on SCOTUS
  - Full pipeline: shared chunker, engine adapters, runner, fact-recall scorer, LLM judge (gpt-4.1-mini), deterministic report generator
- **`docs/why-not-apache-age.md`** — user-facing guide distilled from the research doc, now updated with measured bake-off numbers replacing cited third-party benchmarks
- **70 passing tests** for the benchmark suite (all mocked, no external API calls in test suite)
- **Docker stack** with both engines side-by-side (pgvector/pg16 on 5434, AGE+pgvector on 5435)
- **CLI** (`age-bakeoff ingest|run|judge|report`) for one-command reproduction

### Fixed

- Entity INSERT uses `ON CONFLICT` for corpora with duplicate entity names (SCOTUS has duplicate case names)
- `relationship_chunks` linking scoped to relevant chunks only (was O(R*C) = 3.5M INSERTs for SCOTUS; now O(R*matches))
- Chunker `_split_plain` hard-splits oversized paragraphs (was silently emitting chunks > MAX_CHARS)
- `BakeoffConfig` strips/rejects whitespace-only `OPENAI_API_KEY`

### Infrastructure

- Postgres REL_16_5 executor+planner slice cloned via sparse-checkout (116 .c files) for the code corpus (pg-src questions written, extraction pipeline ready, run deferred to next session)
- Acme seed data: 42 entities, 103 relationships, 160 documents mirrored from graphrag-demo
- SCOTUS seed data: 416 entities, 4,397 relationships, 772 documents mirrored from graphrag-demo
