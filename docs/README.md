# pg-raggraph documentation

## Start here

- **[../README.md](../README.md)** — Project overview, quickstart, real-corpus benchmarks, and the "raggraph not graphrag" framing.
- **[../ASSESSMENT.md](../ASSESSMENT.md)** — No-BS project evaluation: what works, what's rough, what's missing.

## User guides

- **[user-guide.md](user-guide.md)** — Full user guide: installation, configuration, all 6 retrieval modes, evolution-tracking API, REST/MCP servers, schema overview, troubleshooting.
- **[Config-Reference.md](Config-Reference.md)** — Every tunable knob with What / Default / Pros / Cons / When-to-use / When-NOT-to-use. Includes `rerank_*`, `short_answer`, `top_k`, smart-mode thresholds, resolution weights, ingest profiles, evolution-tier toggles.
- **[USE-CASES.md](USE-CASES.md)** — Decision matrix: classic GraphRAG vs evolving knowledge. Corpus shape → recommended config.
- **[EVOLUTION-API-QUICKREF.md](EVOLUTION-API-QUICKREF.md)** — Common assumptions vs reality for the Tier 1 API (which kwargs are per-query vs config-only, schema column locations, `as_of` × `retracted_at` semantics).
- **[modes.md](modes.md)** — All 6 retrieval modes explained with diagrams, SQL, and benchmark numbers.
- **[devmem-guide.md](devmem-guide.md)** — Developer knowledge base walkthrough (`pgrg devmem`).
- **[chunkshop-user-guide.md](chunkshop-user-guide.md)** — User guide for Chunkshop Pattern D chunkers, Pattern C table imports, `ingest-chunkshop-table`, and code-edge graph imports.
- **[cookbook/evolution-tracking.md](cookbook/evolution-tracking.md)** — Tier 1 quickstart for `effective_from` / `retracted` / `version_label`.
- **[cookbook/sales-crm-ingestion.md](cookbook/sales-crm-ingestion.md)** — Worked example: ingest a sales CRM (call notes / orders / customers / products) end-to-end. Two ingest patterns (disk-based, in-memory), real-run output with entity counts and queries, per-mode comparison.
- **[cookbook/chunkshop-integration.md](cookbook/chunkshop-integration.md)** — How to use the [chunkshop](https://github.com/yonk-labs/chunkshop) sibling library (optional but recommended) for chunking and metadata extraction. Patterns D (chunker-only via `chunk_strategy="chunkshop:*"`) and C (full chunkshop pipeline + bridge).

## Worked walkthroughs (blog series — `blogs/`)

- **[blogs/00-what-we-learned-building-graphrag.md](blogs/00-what-we-learned-building-graphrag.md)** — Project-overview narrative: what surprised us building a PG-native GraphRAG, why "graph wins on everything" turns out to be wrong, where graph actually pays.
- **[blogs/01-intro-classic-vs-evolving.md](blogs/01-intro-classic-vs-evolving.md)** — Series intro: two retrieval workloads, one Postgres database, when each one applies.
- **[blogs/02-path-a-versioned-python-docs.md](blogs/02-path-a-versioned-python-docs.md)** — Walkthrough: ingest Python 3.10/3.11/3.12 docs, query with `version_filter`, see the 13/13 perfect filter purity.
- **[blogs/03-path-b-medical-retractions.md](blogs/03-path-b-medical-retractions.md)** — Walkthrough: ingest PubMed HRT abstracts, demonstrate `retracted_behavior="hide"` and `as_of` time-travel.

## Engineering deep-dive

- **[FINDINGS.md](FINDINGS.md)** — Engineering findings with evidence from real benchmarks.

## Bake-off + benchmarks

- **[../benchmarks/age-bakeoff/results/REPORT-VERDICT.md](../benchmarks/age-bakeoff/results/REPORT-VERDICT.md)** — Head-to-head pg-raggraph vs Apache AGE on SCOTUS.
- **[../benchmarks/age-bakeoff/README.md](../benchmarks/age-bakeoff/README.md)** — How to reproduce the bake-off.
- **[../benchmarks/python-versioned-docs/results.md](../benchmarks/python-versioned-docs/results.md)** — Path A real-corpus result: 13/13 (100%) `version_filter` purity.
- **[../benchmarks/medical-hrt/results.md](../benchmarks/medical-hrt/results.md)** — Path B real-corpus result: 5/5 retraction-aware + 5/5 time-travel.
- **[../benchmarks/pg-agents-results.md](../benchmarks/pg-agents-results.md)** — 909-doc real-world dev codebase: +18.9% accuracy from graph boost.
- **[../benchmarks/FINAL_RESULTS.md](../benchmarks/FINAL_RESULTS.md)** — Cross-corpus results (NTSB, SEC, PG docs, SCOTUS).
- **[../benchmarks/DATASETS.md](../benchmarks/DATASETS.md)** — What corpora we test against and why.

## Research documents

- **[../research/apache-age-evaluation.md](../research/apache-age-evaluation.md)** — Canonical AGE evaluation including methodology / fairness disclosure for the bake-off.
- **[../research/main-research.md](../research/main-research.md)** — Architecture rationale and schema reference.
- **[../research/competition-comparison.md](../research/competition-comparison.md)** — Feature matrix vs LightRAG, Neo4j, Zep.
- **[../research/lightrag.md](../research/lightrag.md)** — LightRAG (33K stars) + its PG backend issues.
- **[../research/postgres-graph-rag.md](../research/postgres-graph-rag.md)** — h4gen's prototype deep-dive.
- **[../research/graphrag-psql.md](../research/graphrag-psql.md)** — jimysancho's LightRAG bridge analysis.

## For contributors & AI agents

- **[../CLAUDE.md](../CLAUDE.md)** — Architecture, conventions, development commands (consumed by AI coding assistants).
- **[../CONTRIBUTING.md](../CONTRIBUTING.md)** — How to contribute.
- **[../CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md)** — Community guidelines.
- **[../SECURITY.md](../SECURITY.md)** — Security disclosure process.
- **[../CHANGELOG.md](../CHANGELOG.md)** — Release history.

## Audit trail

- **[archive/](archive/)** — Dated session reports, internal strategy decisions, design specs, and implementation plans. Useful for "how did we get here?" questions; not user-facing documentation. See [archive/README.md](archive/README.md) for the inventory.

---

## Quick links by intent

| I want to … | See |
|---|---|
| Install and run in 5 minutes | [README — Quickstart](../README.md#quickstart--5-minutes-works-cold) |
| Understand the 6 query modes | [modes.md](modes.md) |
| Pick the right workload (classic vs evolving) | [USE-CASES.md](USE-CASES.md) |
| Walk a versioned-docs example | [blogs/02-path-a-versioned-python-docs.md](blogs/02-path-a-versioned-python-docs.md) |
| Walk a retraction-aware example | [blogs/03-path-b-medical-retractions.md](blogs/03-path-b-medical-retractions.md) |
| Avoid common Tier 1 API gotchas | [EVOLUTION-API-QUICKREF.md](EVOLUTION-API-QUICKREF.md) |
| Build a developer knowledge base | [devmem-guide.md](devmem-guide.md) |
| Read the unvarnished assessment | [../ASSESSMENT.md](../ASSESSMENT.md) |
| Compare vs LightRAG / Neo4j / Zep | [../research/competition-comparison.md](../research/competition-comparison.md) |
| Understand why we rejected Apache AGE | [../research/apache-age-evaluation.md](../research/apache-age-evaluation.md) |
| Read the project-overview narrative | [blogs/00-what-we-learned-building-graphrag.md](blogs/00-what-we-learned-building-graphrag.md) |
| See the schema ERD | [user-guide.md → Schema overview](user-guide.md#schema-overview) |
| Reproduce the bake-off vs Apache AGE | [../benchmarks/age-bakeoff/results/REPORT-VERDICT.md](../benchmarks/age-bakeoff/results/REPORT-VERDICT.md) |
