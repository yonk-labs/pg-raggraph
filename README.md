# pg-raggraph

> **PostgreSQL-native GraphRAG.** Vector search, full-text search, and knowledge-graph traversal — all in a single SQL query. No Neo4j. No Pinecone. No Apache AGE. Just the Postgres you already run.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Tests](https://github.com/yonk-labs/pg-raggraph/actions/workflows/test.yml/badge.svg)](https://github.com/yonk-labs/pg-raggraph/actions/workflows/test.yml) [![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)](pyproject.toml) [![PyPI](https://img.shields.io/pypi/v/pg-raggraph)](https://pypi.org/project/pg-raggraph/) [![Status: alpha](https://img.shields.io/badge/status-alpha-orange)]()

---

## What this is

pg-raggraph is a Python library for **GraphRAG on plain PostgreSQL**. You point it at a directory of documents, it ingests them — chunks, embeddings, entities, relationships, full-text index — and you get back a query API that combines vector similarity, BM25, and graph traversal. All retrieval happens in one round-trip to Postgres.

It is also a **full toolkit** around that library: a CLI (`pgrg`), an optional FastAPI server with a web UI, and an MCP server for Claude Desktop / Cursor / Zed.

Two retrieval workloads are first-class:

- **Classic GraphRAG** — static corpora, code Q&A, technical docs, multi-hop entity reasoning. On a real 486-doc dev codebase, 1-hop graph boost improved the top retrieved chunk's score by **+19.3%** over plain vector+BM25 at the same latency ([source](benchmarks/pg-agents-results.md)) — a retrieval-quality proxy, not graded answer accuracy. On gold-labeled multi-hop QA (MuSiQue, LLM-judged), graph traversal (`local`) beats pure vector by **+4–5pp** end-to-end, stable across two judges ([source](benchmarks/ab-gate/RESULTS.md)).
- **Evolving knowledge** — corpora where the right answer depends on *time*, *version*, or *retraction status*. Validated on Python 3.10/3.11/3.12 docs (**13/13 version-filter purity**, with one honest unfiltered-query miss — see below) and PubMed HRT retractions (**10/10 graded checks**: 5/5 retraction-aware + 5/5 time-travel; 5 background smoke checks also pass).

Two ingest patterns are also first-class:

- **Synchronous** (the default) — `ingest()` returns when the graph is built. Right for batch loads and small/fast extractors.
- **Deferred + background drain** — pass `defer_extraction=True` and `ingest_records()` returns in chunk + embed time only (**~18 ms/doc**, 59× faster than synchronous extract on lede_spacy MHR — measured with a warm embedding cache and a deterministic no-LLM extractor; first-run cold ingest will be slower, see the [methodology](docs/cookbook/background-extraction.md#benchmark)). A `pgrg extract` worker (cron-driven or always-on daemon) backfills entities/relationships out-of-band. Multi-worker safe by construction. For code KBs (`chunk_strategy="chunkshop:symbol_aware"`), `pgrg backfill-code-graph` rebuilds the `CALLS`/`INHERITS`/`IMPLEMENTS` call graph out-of-band too — so fast code-KB ingest no longer trades away the graph (#81). See [`docs/cookbook/background-extraction.md`](docs/cookbook/background-extraction.md).

## Why it exists

Most GraphRAG today means stitching together two or three databases:

- A vector DB (Pinecone, Weaviate, Qdrant) for semantic search.
- A graph DB (Neo4j) for relationship traversal.
- An orchestrator on top — LangChain, LlamaIndex, or hand-rolled.

That's three deploy targets, three connection pools, three sets of credentials, three failure modes, three vendors to negotiate with. And the killer GraphRAG operation — *"find chunks similar to X, then expand via the entity graph"* — needs at least two round-trips, often more, because vector and graph live in different worlds.

pg-raggraph proves you don't need any of that. PostgreSQL already has:

- **pgvector** — vector similarity search with HNSW or IVFFlat indexes.
- **pg_trgm** — trigram fuzzy matching, perfect for entity resolution.
- **Recursive CTEs** — fast, well-indexed graph traversal that the planner understands.
- **`tsvector` + `to_tsquery`** — production-grade full-text search with BM25-equivalent ranking.

Combine them in one SQL query and you have a complete GraphRAG stack. One ACID-compliant database. One backup story. One thing to monitor. Works on **every managed Postgres** — AWS RDS, Supabase, Neon, GCP Cloud SQL, Azure, self-hosted — anywhere modern PostgreSQL runs.

The thesis is decided by benchmark, not opinion. See *Tests and benchmarks* below.

## Wait — isn't it called *graphrag*, not *raggraph*?

The name flip is deliberate. Most "GraphRAG" systems lead with the graph: docs get converted to entities and relationships up front, the graph **is** the corpus, and retrieval is graph-walks looking for relevant subgraphs. That's the Microsoft GraphRAG / LightRAG / Neo4j-GraphRAG model.

That model misreads what most corpora actually are. Documentation, technical articles, code, support tickets, papers, chat logs — none of these start out as graphs. They're prose. They answer most questions through plain semantic similarity. Forcing them through an entity-extraction pipeline first, then querying the resulting graph, adds latency, LLM cost, and information loss without buying you much for the bulk of queries.

pg-raggraph inverts the order. **The graph is an enhancer, not the main attraction.** A query starts as RAG — vector similarity + BM25 — and the graph layer kicks in only when retrieval needs help: re-ranking the top-K via 1-hop entity connectivity (`naive_boost`), or expanding to chunks reachable through entity relationships when the seed retrieval is weak (`local` / `hybrid`). **Graph helps finish the story, not start it.**

This isn't aesthetic preference. The [bake-off](benchmarks/age-bakeoff/results/REPORT-VERDICT.md) confirms it: on clean technical corpora, graph-only retrieval modes don't beat plain vector + BM25. They earn their cost when the chunker is weak, when the corpus has cross-document entity reasoning, or when you need explainability and provenance trails. Calling it "raggraph" rather than "graphrag" reflects that ordering: RAG first, graph second, and only when it pays.

## Quickstart — 5 minutes, works cold

Every command is copy-pasteable. You need a running Postgres 16+ with the
`pgvector` and `pg_trgm` extensions; the `docker compose` step below sets
one up locally if you don't have one.

```bash
# 1. Install from PyPI
pip install pg-raggraph              # core SDK + CLI
# or, with the bundled FastAPI server + web UI:
pip install 'pg-raggraph[server]'

# 2. Start a local Postgres with pgvector + pg_trgm pre-installed
#    (skip if you already have a Postgres with the extensions)
curl -sLo docker-compose.yml https://raw.githubusercontent.com/yonk-labs/pg-raggraph/main/docker-compose.yml
docker compose up -d postgres

# 3. Pick an LLM endpoint (skip if you only want pure vector RAG)
#    Option A — OpenAI:
export PGRG_LLM_BASE_URL=https://api.openai.com/v1
export PGRG_LLM_API_KEY=sk-...   # your key
export PGRG_LLM_MODEL=gpt-4o-mini

#    Option B — local Ollama (free):
# ollama pull llama3.2 && ollama serve   # leave running in another shell
# (PGRG defaults to Ollama at http://localhost:11434/v1, so no env needed)

# 4. Ingest a directory and ask questions
pgrg devmem ingest ./my-repo/
pgrg devmem ask "who owns the authentication service?"
```

Prefer to run from source? `git clone https://github.com/yonk-labs/pg-raggraph
&& cd pg-raggraph && uv sync` works the same way; substitute `uv run pgrg` for
`pgrg` in the commands above.

If your LLM endpoint is up and your repo has docs/code, you'll see something like:

```
Found 12 files to process.
[1/12] README.md: 8 entities, 14 rels
[2/12] auth/service.py: 5 entities, 11 rels
...
Done: 12 ingested, 0 skipped. 87 entities, 156 relationships.

Answer: The authentication service is owned by the platform team.
Sarah Chen leads platform; auth.py was last touched by alex@acme.com
in commit 4f2c8a1 ("rotate JWT signing key").

Sources:
  [0.79] auth/README.md
  [0.71] team/platform.md
  [0.68] commits/4f2c8a1.md
```

That's the whole loop. From `pip install` to a grounded answer in five minutes.

> **One thing to know about `pgrg serve`** — the bundled FastAPI web UI is for **local development and demos only**. It binds `127.0.0.1` by default, so it's only reachable from your machine. Exposing it (`--host 0.0.0.0`) requires `PGRG_SERVER_API_KEY` to be set — the server refuses a non-loopback bind without auth, because the API allows ingest, query, and delete. **Do not expose it directly to the public internet.** For production, put it behind a reverse proxy that adds TLS and rate limits — or embed `create_app()` in your own FastAPI application. See [`docs/user-guide.md#production-deployment`](docs/user-guide.md#production-deployment) for the recommended setup.

## MCP server

Connect pg-raggraph to Claude Desktop, Cursor, Zed, or any MCP-compatible
client via `pgrg mcp-serve`. The server returns a tuned tool-selection
playbook in its MCP `initialize` response, so agents pick the right tool
on the first try instead of grepping the filesystem. When you ingest
with `defer_extraction=True`, a per-file staleness banner warns the
agent which documents have fresh chunks but still-pending graph
extraction, and `pgrg_status` reports a `graph_ready` boolean so agents
can tell when background extraction has drained. Its status summary also
carries a `degraded` count — docs that are ready but had per-chunk
extraction failures (partial graph; doesn't block readiness).

See [`docs/user-guide.md`](docs/user-guide.md#mcp-server) for the full
tool list and the `PGRG_MCP_INGEST_ROOTS` allow-list.

## Tests and benchmarks

Real numbers from real corpora — the wins and the losses. Every number below traces to a results file in [`benchmarks/`](benchmarks/).

**Classic GraphRAG** — `pg-agents` real dev codebase (486 docs, 17,437 entities, 38,195 relationships; 15 queries). The metric is **average score of the best retrieved chunk** — a retrieval-quality proxy; no answers were generated or graded in this run. Source: [`benchmarks/pg-agents-results.md`](benchmarks/pg-agents-results.md).

| Mode | Avg top score | Avg latency | vs naive |
|------|:-:|:-:|:-:|
| naive (vector + BM25) | 0.593 | 85 ms | baseline |
| **`naive_boost`** ⭐ | **0.708** | **82 ms** | **+19.3%** |
| **`smart`** (default) | **0.708** | 91 ms | **+19.3%** at routing |
| local (graph traversal) | 0.607 | 220 ms | +2.4% |
| hybrid (local + global) | 0.607 | 282 ms | +2.4% |

Caveats, stated up front:

- The pg-agents corpus is a private codebase — this suite is **not** re-runnable from clone. The evolving-knowledge and bake-off suites below ship download scripts/fixtures and are.
- The top-score lift did **not** transfer to gold-labeled QA: on the SCOTUS legal corpus (LLM-judged), naive/naive_boost moved judged accuracy by at most +3.3pp (+1 question of 30 — within the ±3.3pp-per-question noise floor). Details: [`benchmarks/age-bakeoff/SESSION-HANDOFF.md`](benchmarks/age-bakeoff/SESSION-HANDOFF.md).
- Historical docs cite other snapshots of this growing corpus (356 and 909 docs) with slightly different aggregate lifts; `benchmarks/pg-agents-results.md` is the canonical source.

**Where graph genuinely wins** — MuSiQue multi-hop QA over a real LLM-extracted knowledge graph (9,809 typed edges, 100 compositional 2/3/4-hop questions, dual LLM judges): `local` (recursive traversal) beats pure vector by **+4–5pp** end-to-end, stable across two judges and two answer-generation runs. Retrieval recall stays flat (~58–59% in every mode) — the lift comes from better answer context, not from surfacing more gold paragraphs. Source: [`benchmarks/ab-gate/RESULTS.md`](benchmarks/ab-gate/RESULTS.md).

**Where graph does not win** (kept on purpose):

- **SEC 10-Q gold QnA** — ~47% accuracy across ALL modes; the ceiling is financial-table chunking, not retrieval mode ([`benchmarks/FINAL_RESULTS.md`](benchmarks/FINAL_RESULTS.md)).
- **NTSB aviation reports** — self-contained narratives; graph modes add no measurable lift over naive ([`benchmarks/FINAL_RESULTS.md`](benchmarks/FINAL_RESULTS.md)).
- **MuSiQue raw EM/F1** — verbose generative answers tank exact-match scoring (27% of EM=0 answers were judged fully correct by both LLM judges); the judge and support-recall columns are the meaningful signal ([`benchmarks/FINAL_RESULTS.md`](benchmarks/FINAL_RESULTS.md)).

**Evolving knowledge — versioned docs** ([`benchmarks/python-versioned-docs/`](benchmarks/python-versioned-docs/)):

12 docs (Python 3.10 / 3.11 / 3.12), 1364 chunks, 15 hand-written gold questions.

| Threshold | Result | Pass? |
|---|---|:-:|
| ≥ 80% of `version_filter`-tagged Qs return top-5 chunks ONLY from matching version | **100% (13/13)** | ✅ |
| ≥ 1 unfiltered_target Q has expected version in top-3 | 1/2 | ✅ |

Overall 14/15. The honest miss: an *unfiltered* query about a Python 3.12-only feature (PEP 695 `type` aliases) drifted to 3.10/3.11 chunks, because the older `TypeAlias` terminology has stronger surface overlap. That failure mode is exactly what `version_filter` exists for ([`results.md`](benchmarks/python-versioned-docs/results.md)).

**Evolving knowledge — medical retractions** ([`benchmarks/medical-hrt/`](benchmarks/medical-hrt/)):

48 PubMed abstracts on HRT + cardiovascular outcomes (1998–2025), 7 epistemically-retracted (WHI 2002 superseded the prior consensus), 15 hand-written gold questions: 5 retraction-aware + 5 time-travel (graded below) + 5 background questions (smoke checks that only assert results are returned).

| Threshold | Result | Pass? |
|---|---|:-:|
| ≥ 4/5 retraction_aware Qs return top-5 with **zero** retracted in `retracted_behavior="hide"` mode | **5/5** | ✅ |
| ≥ 1/5 time-travel Qs (`as_of=2001-12-31`) return ≥1 pre-2002 paper in top-5 | **5/5** | ✅ |

**Versus Apache AGE** — SCOTUS bake-off (772 docs, 30 questions × 3 runs × 6 modes per engine):

| Axis | pg-raggraph | Apache AGE |
|---|:-:|:-:|
| Accuracy (fully_correct/30, LLM-judged) | 17–18 | 17–18 (tie) |
| Retrieval p50, graph-assisted modes¹ | **32–73 ms** | 3,079–3,906 ms |
| Cloud compatibility | RDS, Supabase, Neon, Cloud SQL, Azure, self-host | Azure only |

¹ Measured end-to-end through each engine's adapter on our bake-off harness (`hybrid`/`local`/`global`/`naive_boost`/`smart`), a 42–101× p50 differential on this corpus. The naive-mode differential is excluded: both engines execute the same pgvector query in that mode, so it can only reflect adapter overhead (audit pending). Judged accuracy carries error bars — ±1 question = ±3.3pp, and judge choice alone swings scores by ~3–20pp on these corpora. Don't read this as a blanket "faster than AGE" claim: at small scale, raw AGE SQL can outrun pg-raggraph's Python API. A reproducible head-to-head against Microsoft's HorizonDB GraphRAG accelerator, on Microsoft's own corpus, is in progress.

Full bake-off report: [`benchmarks/age-bakeoff/results/REPORT-VERDICT.md`](benchmarks/age-bakeoff/results/REPORT-VERDICT.md).

**Test suite:** 887 tests as of 0.5.0a19 (523 unit + 364 integration) across `tests/unit/` and `tests/integration/`, including a dedicated error-path suite that asserts specific exception types on bad DSNs, naive `as_of`, oversize `/ingest`, path traversal, etc. CI runs the full suite against pgvector containers on Python 3.12 and 3.13.

## Where to go next

```
       ┌──────────────────────────────────────────────────┐
       │  I want to …                                     │
       ├──────────────────────────────────────────────────┤
       │  Pick the right workload         → USE-CASES.md  │
       │  Walk a worked example           → blog series   │
       │  Get the full API surface        → user-guide.md │
       │  Tier-1 evolving-knowledge       → cookbook      │
       │  Decouple ingest from extraction → cookbook      │
       │  Avoid common API gotchas        → API-QUICKREF  │
       │  Read the architecture decisions → research/     │
       │  See the unvarnished critique    → ASSESSMENT.md │
       └──────────────────────────────────────────────────┘
```

| Document | What's inside |
|---|---|
| [`docs/USE-CASES.md`](docs/USE-CASES.md) | Decision matrix: classic GraphRAG vs evolving knowledge. Corpus shape → recommended config. |
| [`docs/blogs/01-intro-classic-vs-evolving.md`](docs/blogs/01-intro-classic-vs-evolving.md) | Series intro: two workloads, one Postgres database, when each one applies. |
| [`docs/blogs/02-path-a-versioned-python-docs.md`](docs/blogs/02-path-a-versioned-python-docs.md) | Walkthrough: ingest Python 3.10/3.11/3.12 docs, query with `version_filter`. |
| [`docs/blogs/03-path-b-medical-retractions.md`](docs/blogs/03-path-b-medical-retractions.md) | Walkthrough: ingest PubMed HRT abstracts, demonstrate `retracted_behavior` and `as_of`. |
| [`docs/cookbook/evolution-tracking.md`](docs/cookbook/evolution-tracking.md) | Tier 1 quickstart — `effective_from`, `retracted`, `version_label` ingest + query patterns. |
| [`docs/EVOLUTION-API-QUICKREF.md`](docs/EVOLUTION-API-QUICKREF.md) | Common assumptions vs reality for the Tier 1 API (which kwargs are per-query vs config-only, schema column locations, semantics of `as_of` × `retracted_at`). |
| [`docs/cookbook/per-call-kwargs.md`](docs/cookbook/per-call-kwargs.md) | Per-call overrides on `query()`/`ask()` — `retracted_behavior`, `supersession_behavior`, `memory_tier`, `retrieval_strategy`, `as_of`, `version_filter`, `evolution_aware`. Multi-tenant-safe (no config mutation). |
| [`docs/cookbook/retrieval-strategy.md`](docs/cookbook/retrieval-strategy.md) | Three SQL shapes for metadata + vector queries — `weighted` (default), `pre_filter`, `vector_first`. When to pick which; recall-shortfall metric. |
| [`docs/cookbook/metadata-indexes.md`](docs/cookbook/metadata-indexes.md) | Btree / GIN / generated-column indexes on `chunks.metadata` and `documents.metadata`. Runtime API (`recommend_metadata_indexes()`, `apply_metadata_indexes_concurrently()`). |
| [`docs/cookbook/changing-embedding-dimensions.md`](docs/cookbook/changing-embedding-dimensions.md) | Move a live database to a new embedding model/dimension online via the `pgrg migrate-embeddings` expand/contract column swap — no parallel DB, brief cutover, startup dim-guard. |
| [`docs/cookbook/background-extraction.md`](docs/cookbook/background-extraction.md) | Decouple LLM/lede extraction from ingest: `defer_extraction=True` + `pgrg extract` (CLI / `--daemon`). Architectural patterns (sync vs cron vs daemon), end-to-end FastAPI walkthrough, multi-worker safety invariants, 60× time-to-queryable benchmark. |
| [`docs/cookbook/typed-graph-join.md`](docs/cookbook/typed-graph-join.md) | Typed traversal + dependent conjunctive joins: `find_entities()` (fuzzy anchor binding), `traverse()` (typed/directed walks), `graph_join()` (bind-then-intersect join questions) — one SQL round-trip, full provenance. |
| [`docs/user-guide.md`](docs/user-guide.md) | Full user guide. Installation, all 6 modes, configuration, REST API, production deployment, troubleshooting. |
| [`docs/devmem-guide.md`](docs/devmem-guide.md) | `pgrg devmem` — the developer-knowledge-base flavor with code-aware chunking + dev-tuned extraction. |
| [`docs/chunkshop-user-guide.md`](docs/chunkshop-user-guide.md) | Chunkshop integration guide: chunker-only strategies, Postgres table bridge, CLI import, code-edge graph import, and the `code-impact` symbol-graph query. |
| [`research/`](research/) | Architecture rationale, vs-AGE evaluation, competitor analyses (LightRAG, Neo4j, Zep). |
| [`ASSESSMENT.md`](ASSESSMENT.md) | No-BS project evaluation. Strengths, gaps, where you should and shouldn't use it. |
| [`benchmarks/`](benchmarks/) | Every benchmark runner + results document. The evolving-knowledge and bake-off suites are re-runnable from clone; the pg-agents corpus is private and is not. |

---

# The weeds

Below this line is the reference material — architecture, the retrieval-mode menu, every environment variable, the schema, and the prior-art rebuttals. Read on if you want to go deep; skip if you just want to get something working.

## Architecture

```mermaid
graph TB
    subgraph PGRG["pg-raggraph (Python, ~4K LOC core)"]
        CLI[pgrg CLI]
        API[FastAPI server]
        MCP[MCP server]
        SDK[GraphRAG SDK]
        CLI --> SDK
        API --> SDK
        MCP --> SDK
        SDK --> ING[Ingestion Pipeline]
        SDK --> RET[Retrieval Engine]
        ING --> CHK[Chunker<br/>markdown / code / text]
        ING --> EMB[fastembed<br/>local 384-dim]
        ING --> EXT[LLM extractor<br/>OpenAI-compatible]
        ING --> RES[Entity resolver<br/>pg_trgm + vector]
        RET --> SM[Smart Router]
        SM --> NV[naive: vector + BM25]
        SM --> GB[graph boost: 1-hop re-rank]
        SM --> LC[local / global / hybrid:<br/>recursive CTEs]
    end
    subgraph PG["PostgreSQL 16+"]
        PGV[pgvector HNSW]
        PGT[pg_trgm GIN]
        FTS[tsvector full-text]
        TBL[(documents · chunks ·<br/>entities · relationships ·<br/>document_versions ·<br/>facts · fact_edges)]
    end
    NV --> PGV
    NV --> FTS
    GB --> TBL
    LC --> TBL
    RES --> PGT
    RES --> PGV
```

**Two extensions** — `pgvector` (vector search) and `pg_trgm` (built into Postgres in most builds). Auto-bootstrapped schema. Migrations applied on first connect under a per-project advisory lock. Everything else is plain SQL.

## Retrieval modes

`smart` (the default) routes between three strategies based on confidence: ship-as-is when the naive top score is high, apply a cheap graph boost when medium, escalate to graph expansion when low. Manually pin to a specific mode with `mode="..."` if you know your access pattern.

| Mode | What it does | Typical latency |
|------|--------------|:-:|
| **`smart`** ⭐ | Routes between naive / boost / expand based on confidence | 85–220 ms |
| `naive` | Vector similarity + BM25 | ~85 ms |
| `naive_boost` | Naive + 1-hop graph re-rank | ~90 ms |
| `local` | Seed → recursive CTE traversal → rank | ~220 ms |
| `global` | Relationship-centric retrieval | ~150 ms |
| `hybrid` | local + global merged | ~450 ms |

Need a *join*, not a search? `rag.graph_join(...)` executes typed, anchor-seeded dependent joins over the entity graph ("restaurant in Maria's city that serves what she craves") in one SQL statement, with full edge/chunk provenance — see [`docs/cookbook/typed-graph-join.md`](docs/cookbook/typed-graph-join.md).

Full deep-dive with selection guidance and per-mode SQL: [`docs/modes.md`](docs/modes.md). Schema diagram + ER relationships: [`docs/user-guide.md#schema-overview`](docs/user-guide.md#schema-overview).

## Configuration (essentials)

All settings via env vars prefixed `PGRG_` (also work as kwargs to `GraphRAG(...)`). The most-used ones:

| Variable | Default | What it does |
|----------|---------|--------------|
| `PGRG_DSN` | `postgresql://postgres:postgres@localhost:5434/pg_raggraph` | Database connection. Refuses to start if `PGRG_ENV=production` and DSN unchanged. |
| `PGRG_NAMESPACE` | `default` | Data isolation key. |
| `PGRG_LLM_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible LLM endpoint. |
| `PGRG_LLM_API_KEY` | `""` | Bearer token (empty for Ollama). |
| `PGRG_EVOLUTION_TIER` | `off` | `off` / `structural` (Tier 1 evolution-aware). |
| `PGRG_INGEST_PROFILE` | `balanced` | `conservative` / `balanced` / `aggressive` / `max`. |
| `PGRG_LOG_FORMAT` | (unset) | Set to `json` for structured logging (Datadog / ELK / Loki). |
| `PGRG_SERVER_API_KEY` | (unset) | Enables Bearer auth on the FastAPI server. |

Full reference (~25 vars including evolution scoring weights, entity-resolution thresholds, server upload caps, Origin allowlists): [`docs/user-guide.md#configuration`](docs/user-guide.md#configuration).

## CLI reference

```bash
# Core
pgrg init                                # Bootstrap schema, verify connection
pgrg ingest PATH... [-n NS] [-p PROFILE] # Ingest files / directories
pgrg query "question" [-m MODE] [-n NS]  # Query (default: smart mode)
pgrg ask "question" [-m MODE] [-n NS]    # Query + grounded LLM answer
pgrg status [-n NS]                      # Graph statistics
pgrg delete -n NS                        # Delete a namespace's data

# Servers
pgrg serve --port 8080                   # FastAPI + web UI (binds 127.0.0.1; --host needs PGRG_SERVER_API_KEY)
pgrg demo                                # Auto-ingest sample data + launch UI
pgrg mcp-serve                           # MCP stdio server for Claude Desktop / Cursor / Zed

# Developer-knowledge-base flavor (code-aware chunking + dev extraction prompt)
pgrg devmem ingest ./repo/ -p aggressive
pgrg devmem ask "who owns the auth service?"

# Chunkshop bridge (import a chunkshop Postgres sink + its code_edges)
pgrg ingest-chunkshop-table --schema S --table T [-n NS] [--with-code-edges] [--skip-llm]
pgrg code-impact pkg.module.func [-n NS] [--depth N] [--json]   # callers/callees of a code symbol

# Change the embedding model/dimension on a live DB (online, no parallel DB)
pgrg migrate-embeddings prepare --model BAAI/bge-base-en-v1.5 --dim 768
pgrg migrate-embeddings backfill            # online, resumable
pgrg migrate-embeddings build-index         # CONCURRENTLY
pgrg migrate-embeddings status              # readiness
pgrg migrate-embeddings cutover             # brief lock; then restart with new PGRG_EMBEDDING_DIM/MODEL
pgrg migrate-embeddings finalize            # drop the old column after validation
```

Throttle profiles tune CPU-yield + parallel ingest knobs:

| Profile | doc_concurrency | extract_concurrency | embed_batch_size | Use case |
|---|:-:|:-:|:-:|---|
| `conservative` | 1 | 4 | 8 | Shared servers, laptops on battery |
| `balanced` | 2 | 8 | 16 | Default — most dev machines |
| `aggressive` | 4 | 16 | 32 | Dedicated dev box |
| `max` | 8 | 32 | 64 | One-off batch jobs on a beefy machine |

## Why not Apache AGE?

We evaluated AGE (PostgreSQL's graph extension) before writing a line of code. We rejected it for four reasons:

1. **Cloud killed.** AGE requires `shared_preload_libraries` — only Azure supports it among major managed providers. No RDS, Supabase, Neon, or Cloud SQL. This alone is dispositive for a library targeting "the Postgres you already run."
2. **Awkward pgvector composition, and a Cypher subset.** AGE's `cypher()` calls *can* be composed with pgvector in a single SQL statement — [Microsoft's HorizonDB GraphRAG doc](https://learn.microsoft.com/en-us/azure/horizondb/ai/graph-rag) shows the CTE pattern, and we've run it on stock AGE 1.5.0. But it's undocumented outside Azure's fork, requires agtype casting at every boundary, and Azure's own seed SQL doesn't run unmodified on stock AGE. Per Microsoft's same doc, AGE implements a subset of openCypher (no `MERGE ... ON CREATE SET`, no `EXISTS` subqueries, no `datetime()`), graph maintenance is manual with no CDC sync, and variable-length paths beyond 3–4 hops "can produce exponential path expansion." Recursive CTEs are plain SQL: no casts, no fork, no subset.
3. **Slower on our GraphRAG harness.** In the SCOTUS bake-off, AGE's graph-assisted retrieval measured 42–101× slower p50 than recursive CTEs, end-to-end through each engine's adapter (naive-mode differential excluded pending an adapter audit; not a blanket claim — see the benchmarks section above).
4. **Production disaster.** LightRAG Issue #2255: 17-hour migration with AGE caused by a query plan estimating 49 **billion** intermediate rows for a 681K-row join. Closed `NOT_PLANNED`.

Full analysis: [`research/apache-age-evaluation.md`](research/apache-age-evaluation.md). Bake-off verdict: [`benchmarks/age-bakeoff/results/REPORT-VERDICT.md`](benchmarks/age-bakeoff/results/REPORT-VERDICT.md).

## What about PostgreSQL 19's native graph queries (SQL/PGQ)?

PostgreSQL 19 (Beta 1 shipped June 2026, GA expected ~Sept/Oct 2026) adds **SQL/PGQ**: native property-graph pattern matching (`CREATE PROPERTY GRAPH` + `GRAPH_TABLE`), the ISO SQL:2023 standard. (It's *not* GraphQL; that's an unrelated API layer from extensions like `pg_graphql`.)

This is good news, and it's our thesis. SQL/PGQ rewrites graph patterns into **ordinary relational joins over your existing tables**, with no new engine, and crucially it's **in core** (no `shared_preload_libraries`), so it'll run on RDS / Supabase / Neon. It's the cloud-friendly, in-core answer Apache AGE never managed to be.

It does **not** replace pg-raggraph:

1. **Fixed-depth only.** The initial release has no variable-length path traversal, which is exactly what our recursive-CTE `local` mode does (vector-seeded, 1..N hops, in one query). That's deferred to a future Postgres release.
2. **It's a query syntax, not a GraphRAG pipeline.** SQL/PGQ assumes you *already have* the graph. pg-raggraph is what builds it: entity/relationship extraction, entity resolution, hybrid retrieval, confidence routing, provenance, incremental updates.
3. **Version floor.** SQL/PGQ needs PG19; pg-raggraph runs on **PG16+** today, on every managed provider.

They stack rather than compete. Our `entities`/`relationships` schema maps 1:1 onto `CREATE PROPERTY GRAPH`, so an optional property-graph view (and SQL/PGQ-backed fixed-depth paths gated behind a PG19 capability check) is on the roadmap. Full take: [the blog](docs/blogs/05-postgres-19-graph-queries-and-pg-raggraph.md).

## Comparison

| | pg-raggraph | LightRAG | Neo4j GraphRAG | Zep |
|---|:-:|:-:|:-:|:-:|
| PostgreSQL-native | ✅ | AGE adapter (Azure only) | ❌ | ❌ |
| Single-query hybrid retrieval | ✅ | ❌ | ❌ | ❌ |
| Works on RDS / Supabase / Neon | ✅ | ❌ | n/a | n/a |
| License | MIT | MIT | Apache 2.0 | Apache 2.0 |
| Pricing | free | free | $65+/mo Aura | $1.25/1K msgs |
| Local embeddings by default | ✅ | ✅ | ❌ | ❌ |
| Directed relationships | ✅ | ❌ (undirected) | ✅ | ✅ |
| Time-aware / retraction-aware | ✅ Tier 1 | ❌ | ❌ | partial |
| Stars | new | 33K+ | 2K+ | 24.8K |

Full feature matrix: [`research/competition-comparison.md`](research/competition-comparison.md).

## Requirements

- Python 3.12+
- PostgreSQL 16+ with `pgvector` and `pg_trgm` extensions
- (Recommended) An OpenAI-compatible LLM endpoint for entity extraction. Without one, ingest still works as pure-vector RAG and graph features stay empty.

## License

MIT. See [`LICENSE`](LICENSE).

---

*Real numbers throughout this README come from results files in [`benchmarks/`](benchmarks/) — wins and losses both. The python-versioned-docs, medical-hrt, and AGE bake-off suites ship download scripts/fixtures and are re-runnable from clone; the pg-agents corpus is private and is not. The project's self-evaluation is in [`ASSESSMENT.md`](ASSESSMENT.md).*
