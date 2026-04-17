# Changelog

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
