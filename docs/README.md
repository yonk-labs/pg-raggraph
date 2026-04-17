# pg-raggraph Documentation

## Start Here

- **[../README.md](../README.md)** — Quick start, architecture, benchmarks
- **[../ASSESSMENT.md](../ASSESSMENT.md)** — No-BS project evaluation (what works, what's rough, what's missing)

## User Guides

- **[user-guide.md](user-guide.md)** — Full user guide: installation, configuration, CLI, SDK, API, troubleshooting
- **[modes.md](modes.md)** — All 6 retrieval modes explained with mermaid diagrams, SQL, and benchmark numbers ⭐
- **[devmem-guide.md](devmem-guide.md)** — Developer knowledge base walkthrough (`pgrg devmem`)

## Engineering Deep-Dive

- **[FINDINGS.md](FINDINGS.md)** — 6 engineering findings with evidence from real benchmarks
- **[why-not-apache-age.md](why-not-apache-age.md)** — Why pg-raggraph uses adjacency tables + recursive CTEs instead of Apache AGE
- **[blog-what-we-learned.md](blog-what-we-learned.md)** — Narrative blog of the project journey
- **[smart-mode-plan.md](smart-mode-plan.md)** — Original implementation plan for smart mode

## AGE Bake-Off

- **[../benchmarks/age-bakeoff/results/REPORT.md](../benchmarks/age-bakeoff/results/REPORT.md)** — Head-to-head results: pg-raggraph 1.4–47× faster retrieval, comparable answer quality
- **[../benchmarks/age-bakeoff/README.md](../benchmarks/age-bakeoff/README.md)** — How to reproduce the benchmark

## Benchmarks

- **[../benchmarks/FINAL_RESULTS.md](../benchmarks/FINAL_RESULTS.md)** — Cross-corpus results (NTSB, SEC, PG docs, SCOTUS)
- **[../benchmarks/pg-agents-results.md](../benchmarks/pg-agents-results.md)** — 909-doc real-world validation with graph boost wins
- **[../benchmarks/DATASETS.md](../benchmarks/DATASETS.md)** — What corpora we test against and why

## Research Documents

- **[../research/main-research.md](../research/main-research.md)** — Architecture rationale and schema reference
- **[../research/competition-comparison.md](../research/competition-comparison.md)** — Feature matrix vs LightRAG, Neo4j, Zep
- **[../research/lightrag.md](../research/lightrag.md)** — Why LightRAG has 33K stars + its PG backend issues
- **[../research/postgres-graph-rag.md](../research/postgres-graph-rag.md)** — h4gen's prototype deep-dive
- **[../research/graphrag-psql.md](../research/graphrag-psql.md)** — jimysancho's LightRAG bridge analysis
- **[../research/apache-age-evaluation.md](../research/apache-age-evaluation.md)** — Why we rejected Apache AGE

## For Contributors & AI Agents

- **[../CLAUDE.md](../CLAUDE.md)** — Architecture, conventions, development commands (for AI coding assistants)
- **[../PROJECT.md](../PROJECT.md)** — Project goals, values, non-negotiable requirements

---

## Quick Links by Question

| I want to... | See |
|--------------|-----|
| Install and run pg-raggraph in 5 minutes | [README → Quick Start](../README.md#quick-start-under-5-minutes) |
| Understand the 6 query modes | [modes.md](modes.md) ⭐ |
| Know when graph mode actually helps | [pg-agents-results.md](../benchmarks/pg-agents-results.md) |
| See honest benchmark data | [FINAL_RESULTS.md](../benchmarks/FINAL_RESULTS.md) |
| Build a developer knowledge base | [devmem-guide.md](devmem-guide.md) |
| Read the no-BS assessment | [ASSESSMENT.md](../ASSESSMENT.md) |
| Compare against LightRAG / Neo4j / Zep | [competition-comparison.md](../research/competition-comparison.md) |
| Understand why we rejected Apache AGE | [why-not-apache-age.md](why-not-apache-age.md) (short) · [apache-age-evaluation.md](../research/apache-age-evaluation.md) (deep) |
| Read the story of what we learned | [blog-what-we-learned.md](blog-what-we-learned.md) |
| See the schema ERD and architecture diagrams | [README](../README.md#architecture) |
