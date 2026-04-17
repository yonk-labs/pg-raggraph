# AGE Bake-Off — TODO

## Priority: High

### Research: Improve answer quality scores
Both engines score 17-37% "fully correct" on the LLM judge. That's a RAG quality ceiling, not a graph-engine problem, but it undermines the benchmark's value if most answers are wrong. Investigate:
- Are the gold answers too strict? (LLM judge rubric may penalize correct-but-differently-worded answers)
- Is the retrieved context actually relevant? Check fact-recall scores and cross-reference with judge verdicts
- Is `top_k=10` too low for the SCOTUS corpus (4K+ relationships, many relevant chunks)?
- Would a re-ranking step (BM25 or cross-encoder) improve retrieval quality for both engines?
- Compare pg-raggraph's `hybrid` vs `local` vs `smart` mode — which produces the best chunks?
- Consider adding a "retrieval quality" metric (chunk relevance independent of answer generation)

### Missing features/functions not tested
- **pg-raggraph `smart` mode routing** — currently using `hybrid` mode only; smart mode's confidence-triggered escalation (naive → boost → full hybrid) was not benchmarked
- **pg-raggraph `local` and `global` modes** — each may perform differently on different corpus types
- **BM25 full-text search contribution** — pg-raggraph's retrieval fuses vector + BM25 + graph; the benchmark doesn't isolate which signal matters most
- **Entity resolution quality** — both engines receive pre-resolved entities; pg-raggraph's built-in fuzzy entity resolution (pg_trgm) was not exercised
- **Incremental ingest** — benchmark does full wipe + re-ingest; pg-raggraph's content-hash dedup was not tested
- **Multi-namespace isolation** — benchmark uses a single namespace; multi-tenant behavior was not tested
- **Concurrent query performance** — all queries are sequential; no load testing
- **Large-document ingestion** — SCOTUS is the biggest corpus (816 chunks) but still modest; did not test at 10K+ chunk scale
- **AGE index tuning** — AGE was run with default indexes only (per AGE docs). Manual BTREE/GIN index tuning could improve AGE's numbers — if it does, that finding should be reported honestly

## Priority: Medium

### Complete the pg-src corpus run
- LLM extraction pass needed (~$1-2 OpenAI cost, cached after first run)
- 30 questions already written (6 bridging, grounded in executor/planner source)
- This is the "code corpus" showcase — the bridging questions here are the strongest test of graph traversal value
- Run: `export OPENAI_API_KEY=... && cd benchmarks/age-bakeoff && uv run age-bakeoff run -c pg-src && uv run age-bakeoff judge -c pg-src && uv run age-bakeoff report`

### Write README.md for the benchmark
- Reproduction instructions (already in plan Task 10.1)
- How to swap models, add corpora, interpret results

### Write ARCHITECTURE.md
- Fairness mechanisms documented
- Known asymmetries between engines (retrieval strategies differ, bypassed pg-raggraph's extractor, etc.)
- What the report measures vs what it doesn't

### Update docs/why-not-apache-age.md
- ~~Replace cited third-party benchmarks with measured numbers~~ DONE (47x on SCOTUS)
- Add link to the full REPORT.md from the "See Also" section

### DC-003 / DC-004 / DC-FINAL drift checkpoints
- Re-read mission brief, verify all SC-XXX have evidence
- The "Where AGE wins" section in REPORT.md needs a quality finding for Acme (AGE had 0 hallucinations vs 3)

## Priority: Low

### Per-question-class breakdown in report
- The report generator has the code but the current output doesn't break down by factual/single_hop/semantic/multi_hop_bridging
- This is the key metric for the "does graph traversal help for bridging questions?" thesis

### Fact recall metric
- Implement and report deterministic fact recall (string match of required_facts against retrieved chunks)
- Currently the report only shows LLM judge verdicts

### Cost tracking integration
- `CostTracker` exists but isn't wired into the runner/judge CLI commands
- Track actual OpenAI spend per run and embed in REPORT.md

### Clean-state reproduction dry-run
- Follow README from a fresh git clone, verify everything works without tribal knowledge
