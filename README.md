# pg-raggraph

> **PostgreSQL-native GraphRAG.** Vector search, full-text search, and knowledge-graph traversal — all in a single SQL query. No Neo4j. No Pinecone. No Apache AGE. Just the Postgres you already run.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Tests](https://img.shields.io/badge/tests-195%20passing-brightgreen)](#tests-and-benchmarks) [![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)](pyproject.toml) [![Status: alpha](https://img.shields.io/badge/status-alpha%20(0.3.0a0)-orange)]()

---

## What this is

pg-raggraph is a Python library for **GraphRAG on plain PostgreSQL**. You point it at a directory of documents, it ingests them — chunks, embeddings, entities, relationships, full-text index — and you get back a query API that combines vector similarity, BM25, and graph traversal. All retrieval happens in one round-trip to Postgres.

It is also a **full toolkit** around that library: a CLI (`pgrg`), an optional FastAPI server with a web UI, and an MCP server for Claude Desktop / Cursor / Zed.

Two retrieval workloads are first-class:

- **Classic GraphRAG** — static corpora, code Q&A, technical docs, multi-hop entity reasoning. Validated at **+18.9% accuracy lift** over plain vector search on a real 909-doc dev codebase.
- **Evolving knowledge** — corpora where the right answer depends on *time*, *version*, or *retraction status*. Validated on Python 3.10/3.11/3.12 docs (**13/13 perfect version-filter purity**) and PubMed HRT retractions (**15/15 perfect on retraction-aware + time-travel queries**).

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

## Quickstart — 5 minutes, works cold

This is verified to reproduce on a fresh clone. Every command is copy-pasteable.

```bash
# 1. Clone (pg-raggraph is alpha and not yet on PyPI)
git clone https://github.com/yonk-labs/pg_raggraph
cd pg_raggraph

# 2. Install Python deps (uv recommended; falls back to pip if you must)
uv sync

# 3. Start a local Postgres with pgvector + pg_trgm pre-installed
docker compose up -d postgres

# 4. Pick an LLM endpoint (skip if you only want pure vector RAG)
#    Option A — OpenAI:
export PGRG_LLM_BASE_URL=https://api.openai.com/v1
export PGRG_LLM_API_KEY=sk-...   # your key
export PGRG_LLM_MODEL=gpt-4o-mini

#    Option B — local Ollama (free):
# ollama pull llama3.2 && ollama serve   # leave running in another shell
# (PGRG defaults to Ollama at http://localhost:11434/v1, so no env needed)

# 5. Ingest a directory and ask questions
uv run pgrg devmem ingest ./my-repo/
uv run pgrg devmem ask "who owns the authentication service?"
```

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

That's the whole loop. From `git clone` to a grounded answer in five minutes.

> **One thing to know about `pgrg serve`** — the bundled FastAPI web UI is for **local development and demos only**. It ships without authentication, rate limiting, or upload size caps. **Do not expose it directly to the public internet.** For production, put it behind a reverse proxy that adds auth, TLS, and rate limits — or embed `create_app()` in your own FastAPI application. See [`docs/user-guide.md#production-deployment`](docs/user-guide.md#production-deployment) for the recommended setup.

## Tests and benchmarks

Real numbers from real corpora. No cherry-picking.

**Classic GraphRAG** — `pg-agents` real dev codebase (909 docs, 17K entities, 38K relationships):

| Mode | Avg top score | Latency p50 | vs naive |
|------|:-:|:-:|:-:|
| naive (vector + BM25) | 0.602 | 109 ms | baseline |
| **`naive_boost`** ⭐ | **0.716** | **107 ms** | **+18.9%** |
| **`smart`** (default) | **0.716** | 127 ms | **+18.9%** at routing |
| local (graph traversal) | 0.614 | 423 ms | +1.9% |
| hybrid (local + global) | 0.614 | 482 ms | +1.9% |

**Evolving knowledge — versioned docs** ([`benchmarks/python-versioned-docs/`](benchmarks/python-versioned-docs/)):

12 docs (Python 3.10 / 3.11 / 3.12), 1364 chunks, 15 hand-written gold questions.

| Threshold | Result | Pass? |
|---|---|:-:|
| ≥ 80% of `version_filter`-tagged Qs return top-5 chunks ONLY from matching version | **100% (13/13)** | ✅ |
| ≥ 1 unfiltered_target Q has expected version in top-3 | 1/2 | ✅ |

**Evolving knowledge — medical retractions** ([`benchmarks/medical-hrt/`](benchmarks/medical-hrt/)):

48 PubMed abstracts on HRT + cardiovascular outcomes (1998–2025), 7 epistemically-retracted (WHI 2002 superseded the prior consensus), 15 hand-written gold questions.

| Threshold | Result | Pass? |
|---|---|:-:|
| ≥ 4/5 retraction_aware Qs return top-5 with **zero** retracted in `retracted_behavior="hide"` mode | **5/5** | ✅ |
| ≥ 1/5 time-travel Qs (`as_of=2001-12-31`) return ≥1 pre-2002 paper in top-5 | **5/5** | ✅ |

**Versus Apache AGE** — SCOTUS bake-off (772 docs, 30 questions × 3 runs × 6 modes per engine):

| Axis | pg-raggraph | Apache AGE |
|---|:-:|:-:|
| Accuracy (fully_correct/30) | 17–18 | 17–18 (tie) |
| Retrieval p50 latency | **32–73 ms** | 3,079–3,906 ms (**42–111× slower**) |
| Cloud compatibility | RDS, Supabase, Neon, Cloud SQL, Azure, self-host | Azure only |

Full bake-off report: [`benchmarks/age-bakeoff/results/REPORT-VERDICT.md`](benchmarks/age-bakeoff/results/REPORT-VERDICT.md).

**Test suite:** 195 passing tests across `tests/unit/` and `tests/integration/`, including a 15-test error-path suite that asserts specific exception types on bad DSNs, naive `as_of`, oversize `/ingest`, path traversal, etc. CI runs the full suite against pgvector containers on Python 3.12 and 3.13.

## Where to go next

```
       ┌──────────────────────────────────────────────────┐
       │  I want to …                                     │
       ├──────────────────────────────────────────────────┤
       │  Pick the right workload         → USE-CASES.md  │
       │  Walk a worked example           → blog series   │
       │  Get the full API surface        → user-guide.md │
       │  Tier-1 evolving-knowledge       → cookbook      │
       │  Avoid common API gotchas        → API-QUICKREF  │
       │  Read the architecture decisions → research/     │
       │  See the unvarnished critique    → ASSESSMENT.md │
       └──────────────────────────────────────────────────┘
```

| Document | What's inside |
|---|---|
| [`docs/USE-CASES.md`](docs/USE-CASES.md) | Decision matrix: classic GraphRAG vs evolving knowledge. Corpus shape → recommended config. |
| [`docs/blog/01-intro-classic-vs-evolving.md`](docs/blog/01-intro-classic-vs-evolving.md) | Series intro: two workloads, one Postgres database, when each one applies. |
| [`docs/blog/02-path-a-versioned-python-docs.md`](docs/blog/02-path-a-versioned-python-docs.md) | Walkthrough: ingest Python 3.10/3.11/3.12 docs, query with `version_filter`. |
| [`docs/blog/03-path-b-medical-retractions.md`](docs/blog/03-path-b-medical-retractions.md) | Walkthrough: ingest PubMed HRT abstracts, demonstrate `retracted_behavior` and `as_of`. |
| [`docs/cookbook/evolution-tracking.md`](docs/cookbook/evolution-tracking.md) | Tier 1 quickstart — `effective_from`, `retracted`, `version_label` ingest + query patterns. |
| [`docs/EVOLUTION-API-QUICKREF.md`](docs/EVOLUTION-API-QUICKREF.md) | Common assumptions vs reality for the Tier 1 API (which kwargs are per-query vs config-only, schema column locations, semantics of `as_of` × `retracted_at`). |
| [`docs/user-guide.md`](docs/user-guide.md) | Full user guide. Installation, all 6 modes, configuration, REST API, production deployment, troubleshooting. |
| [`docs/devmem-guide.md`](docs/devmem-guide.md) | `pgrg devmem` — the developer-knowledge-base flavor with code-aware chunking + dev-tuned extraction. |
| [`research/`](research/) | Architecture rationale, vs-AGE evaluation, competitor analyses (LightRAG, Neo4j, Zep). |
| [`ASSESSMENT.md`](ASSESSMENT.md) | No-BS project evaluation. Strengths, gaps, where you should and shouldn't use it. |
| [`benchmarks/`](benchmarks/) | Every benchmark corpus + runner + results document. Re-runnable from clone. |

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

```mermaid
flowchart TD
    Q[User query] --> N[Run naive: vector + BM25]
    N --> C{Top score?}
    C -->|≥ 0.7 high conf| SHIP[Return as-is<br/>~85 ms]
    C -->|0.4-0.7 medium| BOOST[Apply graph boost:<br/>re-rank top-K<br/>~90 ms]
    C -->|< 0.4 low| EXPAND[Escalate to local mode:<br/>seed → expand → rank<br/>~220 ms]
    SHIP --> R[Results]
    BOOST --> R
    EXPAND --> R
```

| Mode | What it does | When to reach for it | Typical latency |
|------|--------------|---------------------|-----------------|
| **`smart`** ⭐ | Routes between naive / boost / expand based on confidence | **Default. Almost always.** | 85–220 ms |
| `naive` | Vector similarity + BM25 over chunks | Fastest. Simple factual questions. | ~85 ms |
| `naive_boost` | Naive + cheap 1-hop graph re-rank | Best single-mode: +18.9% accuracy at ~same speed | ~90 ms |
| `local` | Seed via vector → recursive CTE traversal → rank chunks | When the answer chains across docs via entities | ~220 ms |
| `global` | Search by relationship types → fetch evidence chunks | Entity-relationship questions | ~150 ms |
| `hybrid` | local + global merged | Most exhaustive (and slowest) | ~450 ms |

## Schema

```mermaid
erDiagram
    documents ||--o{ chunks : contains
    documents ||--o{ document_versions : "has version metadata"
    chunks ||--o{ entity_chunks : links
    chunks ||--o{ relationship_chunks : links
    entities ||--o{ entity_chunks : tagged
    entities ||--o{ relationships : "is source"
    entities ||--o{ relationships : "is target"
    relationships ||--o{ relationship_chunks : evidence
    documents {
        bigint id PK
        text namespace
        text content_hash
        text source_path
        timestamptz effective_from
        timestamptz effective_to
        bool retracted
        text version_label
        jsonb metadata
    }
    chunks {
        bigint id PK
        bigint document_id FK
        text content
        text embedded_content
        vector embedding
        tsvector search_vector
    }
    entities {
        bigint id PK
        text namespace
        text name
        text entity_type
        text description
        vector embedding
    }
    relationships {
        bigint id PK
        text namespace
        bigint src_id FK
        bigint dst_id FK
        text rel_type
        float weight
    }
    document_versions {
        bigint id PK
        bigint document_id FK
        text version_label
        timestamptz retracted_at
        text retraction_reason
        bigint supersedes_document_id FK
    }
```

Plus `facts` and `fact_edges` (empty at Tier 1; populated by Tier 2/3 fact extraction). Migrations are forward-only and applied automatically on first `rag.connect()` — see [`docs/user-guide.md#schema-migrations`](docs/user-guide.md#schema-migrations) for the rollback story.

## Configuration

All settings via environment variables prefixed `PGRG_`. Same names work as kwargs to `GraphRAG(...)`.

| Variable | Default | What it does |
|----------|---------|--------------|
| `PGRG_DSN` | `postgresql://postgres:postgres@localhost:5434/pg_raggraph` | Database connection. **Refuses to start if `PGRG_ENV=production` and DSN unchanged.** |
| `PGRG_NAMESPACE` | `default` | Data isolation key — pass to every method to scope by tenant / project. |
| `PGRG_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Local embedding model. 384-dim, ~30 MB, downloaded on first use. |
| `PGRG_EMBEDDING_PROVIDER` | `local` | `local` (fastembed), `openai`, or `ollama`. |
| `PGRG_LLM_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible LLM endpoint. Set to `https://api.openai.com/v1` for OpenAI proper. |
| `PGRG_LLM_MODEL` | `llama3.2` | LLM model name. |
| `PGRG_LLM_API_KEY` | `""` | Bearer token — empty for Ollama. |
| `PGRG_EXTRACTION_PROMPT` | `default` | `default` (general) or `dev` (code-tuned: person/service/library/file/commit/incident/ADR). |
| `PGRG_INGEST_PROFILE` | `balanced` | `conservative` / `balanced` / `aggressive` / `max` — CPU-yield + concurrency knobs. |
| `PGRG_CHUNK_STRATEGY` | `auto` | `auto` (markdown/code/text autodetect) or `hierarchy` (heading-prefixed chunks; opt-in — wins on concrete-title corpora, regresses on meeting-format titles, see [bake-off evidence](benchmarks/age-bakeoff/results/ACME-HIER-REPLICATION.md)). |
| `PGRG_TOP_K` | `10` | Chunks returned per query. |
| `PGRG_MAX_HOPS` | `2` | Recursive-CTE traversal depth for `local`/`global`/`hybrid`. |
| `PGRG_BOOST_CONFIDENCE_THRESHOLD` | `0.7` | Above: ship `naive` result; between: apply graph boost. |
| `PGRG_EXPAND_CONFIDENCE_THRESHOLD` | `0.4` | Below: escalate to graph expansion. |
| `PGRG_EVOLUTION_TIER` | `off` | `off` / `structural` / `fact_aware` / `full`. Tier 1 (`structural`) is the only currently shipping; rest are roadmap. |
| `PGRG_RETRACTED_BEHAVIOR` | `flag` | `hide` / `flag` / `surface_both`. **Config-only**, not a per-query kwarg — see [`docs/EVOLUTION-API-QUICKREF.md`](docs/EVOLUTION-API-QUICKREF.md). |
| `PGRG_LOG_FORMAT` | (unset) | Set to `json` for stdlib-only structured logging on stderr (Datadog / ELK / Loki friendly). |
| `PGRG_SERVER_API_KEY` | (unset) | When set, enables Bearer auth on the FastAPI server. |
| `PGRG_SERVER_ALLOWED_ORIGINS` | (unset) | Comma-separated Origin allowlist for state-changing methods. When unset, only loopback Origins are accepted on POST/PUT/DELETE/PATCH. |
| `PGRG_SERVER_MAX_UPLOAD_MB` | `100` | Hard cap on `/ingest` upload size; 413 on exceed. |

Full table including evolution-tracking weights and entity-resolution thresholds: [`docs/user-guide.md#configuration`](docs/user-guide.md#configuration).

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
pgrg serve --port 8080                   # FastAPI + web UI (local/demo only)
pgrg demo                                # Auto-ingest sample data + launch UI
pgrg mcp-serve                           # MCP stdio server for Claude Desktop / Cursor / Zed

# Developer-knowledge-base flavor (code-aware chunking + dev extraction prompt)
pgrg devmem ingest ./repo/ -p aggressive
pgrg devmem ask "who owns the auth service?"
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

1. **Cloud killed.** AGE requires `shared_preload_libraries` — only Azure supports it among managed providers. No RDS, Supabase, Neon, or Cloud SQL.
2. **Can't combine with pgvector in a single query.** AGE Cypher and pgvector live in different worlds. The killer GraphRAG operation needs two round-trips with AGE; one query with recursive CTEs.
3. **Slower for GraphRAG patterns.** Bake-off measurements: AGE is **42–111× slower** on retrieval than recursive CTEs for the typical 1-3 hop pattern.
4. **Production disaster.** LightRAG Issue #2255: 17-hour migration with AGE caused by a query plan estimating 49 **billion** intermediate rows for a 681K-row join. Closed `NOT_PLANNED`.

Full analysis: [`research/apache-age-evaluation.md`](research/apache-age-evaluation.md). Bake-off verdict: [`benchmarks/age-bakeoff/results/REPORT-VERDICT.md`](benchmarks/age-bakeoff/results/REPORT-VERDICT.md).

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

*Built with honest benchmarks and real corpora. Real numbers throughout this README come from `benchmarks/` runs that ship with the repo — re-runnable from clone. The unvarnished evaluation is in [`ASSESSMENT.md`](ASSESSMENT.md).*
