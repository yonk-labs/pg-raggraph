# Changelog

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
