# pg-raggraph User Guide

> The fastest, simplest way to add knowledge-graph-powered RAG to any app — backed by the PostgreSQL you already run.

> **Picking a workload:** see [`USE-CASES.md`](USE-CASES.md) for the
> classic-vs-evolving decision matrix and benchmark numbers.

## Contents
- [When to Use pg-raggraph](#when-to-use)
- [Installation](#installation)
- [First Steps](#first-steps)
- [Query Modes Explained](#query-modes-explained)
- [When to Use Each Mode](#when-to-use-each-mode)
- [Evolution Tracking (Tier 1, alpha)](#evolution-tracking-tier-1-alpha)
- [Configuration](#configuration)
- [Ingesting Documents](#ingesting-documents)
- [Chunkshop Integration](#chunkshop-integration)
- [Python SDK](#python-sdk)
- [REST API](#rest-api)
  - [Production deployment](#production-deployment)
- [Web UI](#web-ui)
- [Troubleshooting](#troubleshooting)

---

## When to Use

**Use pg-raggraph if:**
- You already use PostgreSQL and want to avoid adding Neo4j/Pinecone/Qdrant
- You need multi-hop reasoning ("Who owns the service that caused the outage?")
- You want hybrid retrieval: vector + BM25 + graph in a single SQL query
- You need to work on managed PG (RDS, Supabase, Neon, GCP Cloud SQL)
- You want a small, auditable codebase (<1,500 LOC core)

**Don't use pg-raggraph if:**
- You need temporal knowledge graphs (use Zep/Graphiti)
- You need community detection / hierarchical summaries (use MS GraphRAG)
- You just need simple vector search (use pgvector directly)
- You need billion-node graphs (use Neo4j or TigerGraph)

---

## Installation

### Prerequisites
- Python 3.12+
- PostgreSQL 16+ with pgvector and pg_trgm extensions
- (Recommended) An OpenAI-compatible LLM for entity extraction

### 1. Start PostgreSQL

If you don't already have one, use the included docker-compose:
```bash
docker compose up -d
```

This starts PostgreSQL 16 with pgvector + pg_trgm pre-installed on **port 5434**.

> **Why port 5434?** The default Postgres port (5432) is frequently
> already in use on developer machines (Homebrew Postgres, host Postgres,
> a parallel Docker container, etc.). pg-raggraph picks 5434 to stay out
> of the way. If you want a different port, override
> `PGRG_DSN=postgresql://postgres:postgres@localhost:YOUR_PORT/pg_raggraph`
> (or set the matching `ports:` mapping in `docker-compose.yml`).

### 2. Install pg-raggraph

```bash
pip install pg-raggraph              # Core SDK + CLI
pip install pg-raggraph[server]      # + FastAPI web server
pip install pg-raggraph[demo]        # + everything needed for pgrg demo
```

### 3. Setup an LLM (for entity extraction)

**Option A: Ollama (local, free)**
```bash
ollama pull llama3.2
ollama serve  # Default: http://localhost:11434
```

pg-raggraph defaults to Ollama at `http://localhost:11434/v1`.

**Option B: OpenAI**
```bash
export PGRG_LLM_BASE_URL=https://api.openai.com/v1
export PGRG_LLM_API_KEY=sk-your-key
export PGRG_LLM_MODEL=gpt-4o-mini
```

**Option C: Any OpenAI-compatible server (vLLM, LM Studio, LocalAI, etc.)**
```bash
export PGRG_LLM_BASE_URL=http://your-server:8000/v1
export PGRG_LLM_MODEL=your-model-name
```

**No LLM?** That's OK. pg-raggraph will still ingest documents and chunks (naive mode works), but you'll miss the graph features.

### Logging

Default Python logging is unstructured text. For log aggregators (Datadog, ELK, Loki, Splunk), set:

```bash
export PGRG_LOG_FORMAT=json
export PGRG_LOG_LEVEL=INFO   # optional; default INFO
```

JSON lines are emitted on stderr with shape: `{"ts","level","logger","msg",...}`. The formatter is stdlib-only (no extra dep). Anything in `logger.info("...", extra={"x": 1})` is merged at the top level. If the caller has already attached handlers to the `pg_raggraph` logger, that wins — the env-driven formatter only kicks in when no handlers are present.

### Graceful shutdown for long ingest jobs

The `ingest()` loop checks a cooperative shutdown event at the per-file boundary. Wire your signal handler to `rag.request_shutdown()` to drain cleanly without aborting in-flight per-document transactions:

```python
import asyncio, signal
from pg_raggraph import GraphRAG

async def main():
    rag = GraphRAG(...)
    await rag.connect()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, rag.request_shutdown)
    await rag.ingest(["./big_corpus/"])

asyncio.run(main())
```

Already-running per-file transactions finish; queued files become no-ops counted as `skipped`. Re-running `ingest()` on the same paths picks up where it left off (content-hash dedup).

### Schema overview

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

Plus `facts` and `fact_edges` (empty at Tier 1; populated by Tier 2/3 fact extraction). The schema is auto-bootstrapped on first `rag.connect()` under a per-project Postgres advisory lock.

### Schema migrations

pg-raggraph manages its own schema. On first connect, it bootstraps the base schema and applies any pending numbered migrations from
`src/pg_raggraph/sql/migrations/` automatically (under a per-project Postgres advisory lock so multiple workers don't race).

> **Forward-only by design.** Migrations are append-only — there are no `down.sql` files. To roll back a schema change, restore from your Postgres backup or run manual SQL. The library will not undo a migration for you. If you maintain a multi-environment deployment, gate any version bump that introduces a migration on a backup-then-deploy procedure.

If you need to apply migrations explicitly (rather than at first connect), run `pgrg init` against the target database; it's idempotent.

### Concurrency / sizing

pg-raggraph exposes three knobs that affect how hard it pushes the database, the embedder, and the LLM. Defaults are conservative and safe; raise them when you have headroom.

| Knob | Default | What to raise to | Notes |
|------|---------|------------------|-------|
| `pool_max` (connection-pool ceiling) | 10 | 25–50 for the FastAPI server under sustained load | Each concurrent web request needs at least one DB connection; the ingest pipeline can need several. |
| `doc_concurrency` (parallel docs during ingest) | 2 | 4 (`aggressive` profile) or 8 (`max`) on a dedicated machine | Higher values + many CPU-bound chunks → contention with the embedder; benchmark on your hardware. |
| `extract_concurrency` (parallel LLM calls during ingest) | 8 | 16+ if your LLM endpoint is rate-tolerant | Bounded by `httpx.Limits(max_connections=20)` in `extraction.py`; raising both is what you want. |

Quick recipes:

- **Library inside a single web worker (typical SaaS sidecar):** stick with defaults; the in-process pool of 10 is plenty.
- **`pgrg serve` behind a reverse proxy with N concurrent users:** set `PGRG_POOL_MAX=N+5` and add a few extras for ingest jobs.
- **Batch ingest a large corpus on a dedicated host:** set `PGRG_INGEST_PROFILE=aggressive` (or `max`) and watch the LLM endpoint's throughput.

You can override any single knob with `PGRG_<NAME>=...` even when an `INGEST_PROFILE` is set; explicit env wins over the profile.

---

## First Steps

```bash
# 1. Create the schema
pgrg init

# 2. Ingest your documents
pgrg ingest ./my-docs/

# 3. Ask a question
pgrg query "What is my authentication stack?"

# 4. See stats
pgrg status

# 5. Launch the web UI
pgrg serve
# Visit http://localhost:8080
```

That's it. You now have a searchable knowledge graph.

---

## Chunkshop Integration

pg-raggraph now supports two Chunkshop integration paths:

- **Chunker-only:** set `chunk_strategy="chunkshop:<strategy>"` and keep pg-raggraph in charge of embedding, extraction, and graph storage.
- **Full pipeline bridge:** let Chunkshop write chunks and embeddings to a Postgres sink table, then import them with `pgrg ingest-chunkshop-table` or `pg_raggraph.chunkshop_bridge`.

For the full guide, including code-aware strategies, table schemas, CLI examples, SDK helpers, code-edge imports, and troubleshooting, see [`chunkshop-user-guide.md`](chunkshop-user-guide.md).

Quick CLI example:

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

Quick SDK example:

```python
from pg_raggraph import GraphRAG
from pg_raggraph.chunkshop_bridge import fetch_records_from_table

records = fetch_records_from_table(
    dsn,
    schema="chunkshop_docs",
    table="chunks",
    skip_llm=True,
)

rag = GraphRAG(dsn=dsn, namespace="docs_graph")
await rag.connect()
await rag.ingest_records(records, namespace="docs_graph")
```

After importing code edges (`--with-code-edges`), query the call graph by symbol:

```bash
pgrg code-impact pkg.module.func -n code_graph --depth 2   # callers + callees, with evidence
```

`await rag.code_impact("pkg.module.func", depth=2)` returns the same as a `CodeImpact` dataclass. See [`chunkshop-user-guide.md`](chunkshop-user-guide.md#querying-the-code-graph-code-impact).

---

## Changing the embedding model / dimension

The vector column dimension is fixed at first bootstrap from `embedding_dim`. To move an existing database to a new embedding model online — without a parallel DB or full downtime — use the expand/contract migration:

```bash
pgrg migrate-embeddings prepare --model BAAI/bge-base-en-v1.5 --dim 768
pgrg migrate-embeddings backfill        # online, resumable
pgrg migrate-embeddings build-index     # CONCURRENTLY
pgrg migrate-embeddings status          # confirm readiness
# stop app, then:
pgrg migrate-embeddings cutover         # brief lock
# restart with PGRG_EMBEDDING_DIM=768 / PGRG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
pgrg migrate-embeddings finalize        # drop the old column after validation
```

A startup guard refuses to connect if `embedding_dim` no longer matches the live column, so a forgotten config change fails fast. Full runbook: [`cookbook/changing-embedding-dimensions.md`](cookbook/changing-embedding-dimensions.md).

---

## Query Modes Explained

pg-raggraph offers **four query modes** that trade off speed, context breadth, and graph understanding:

### Naive Mode (Vector + BM25)
```bash
pgrg query "..." -m naive
```
- **How it works:** Embeds your question, does vector similarity + BM25 full-text search on chunks directly
- **No graph traversal** — just finds chunks that look similar
- **Fastest** — typically <20ms
- **Best for:** Direct factual questions, keyword searches, single-document answers

### Local Mode (Graph-Expanded)
```bash
pgrg query "..." -m local
```
- **How it works:** Finds seed entities via vector similarity, then expands N hops through relationships, then ranks resulting chunks
- **Graph-aware** — follows entity connections
- **Slower than naive** — typically 20-50ms
- **Best for:** Entity-centric questions ("What does Jake Morrison own?"), multi-hop reasoning

### Global Mode (Relationship-Centric)
```bash
pgrg query "..." -m global
```
- **How it works:** Searches relationships by vector similarity, then gathers chunks connected to those relationships
- **Relationship-focused** — finds how things are connected
- **Best for:** "How is X related to Y?", thematic questions

### Hybrid Mode (Local + Global)
```bash
pgrg query "..." -m hybrid
```
- **How it works:** Runs local and global in parallel, deduplicates, and re-ranks
- **Most context** — broadest coverage
- **Slowest** — typically 30-60ms
- **Best for:** When you're not sure which mode to use, exploratory questions

### Naive + Boost Mode
```bash
pgrg query "..." -m naive_boost
```
- **How it works:** Naive retrieval, then a cheap 1-hop graph re-rank that
  boosts chunks whose entities are connected to the seed entities
- **Middle ground** — almost as fast as naive, picks up graph signal
- **Best for:** Most questions — faster than hybrid, picks up graph context

### Smart Mode (Default) ⭐
```bash
pgrg query "..." -m smart   # this is the default
```
- **How it works:** Runs naive first, routes based on confidence:
  - **High confidence** (top score ≥ 0.7): return naive as-is (fastest path)
  - **Medium confidence** (0.4–0.7): apply cheap graph boost
  - **Low confidence** (< 0.4): escalate to full hybrid
- **Adaptive** — pays the graph cost only when needed
- **Best for:** Production default. Handles easy questions fast and hard ones correctly.

Smart mode reports which path it took in `result.query_mode`:
- `smart[naive]` — vector was confident, shipped as-is
- `smart[boosted]` — applied 1-hop graph re-rank
- `smart[expanded]` — escalated to full graph expansion

Configure the thresholds via env vars:
```bash
export PGRG_BOOST_CONFIDENCE_THRESHOLD=0.7   # above this: no graph
export PGRG_EXPAND_CONFIDENCE_THRESHOLD=0.4  # below this: full graph expansion
```

---

## When to Use Each Mode

Based on our benchmarks across real corpora (technical docs, financial filings, incident reports):

| Query Type | Best Mode | Why |
|-----------|-----------|-----|
| "What is X?" (definition) | **naive** | Direct text match is usually sufficient |
| "How do I do X?" (tutorial) | **naive** | Steps are usually in one document |
| "Who owns/manages X?" | **local** | Follows ownership relationships |
| "What depends on X?" | **local** or **hybrid** | Needs dependency graph |
| "How are X and Y related?" | **global** | Searches relationship descriptions |
| "What caused incident X?" | **hybrid** | Needs to connect incident → cause → fix chain |
| "I'm not sure" | **hybrid** | Safest default |
| "I need fastest response" | **naive** | ~2x faster than hybrid |

**Important honest finding:** On technical documentation where concepts are self-contained (e.g., PostgreSQL docs), naive mode often ties or beats graph modes. Graph modes shine when answers require connecting information across multiple documents.

---

## Evolution Tracking (Tier 1, alpha)

`v0.3.0a0` introduces **opt-in evolution tracking** — retrieval that respects when documents
were effective, which were retracted, and which supersede earlier versions. Zero LLM cost
at this tier; everything is metadata-driven.

### Turn it on

```python
from datetime import datetime, timezone
from pg_raggraph import GraphRAG

rag = GraphRAG(
    dsn=DSN,
    namespace="medical",
    evolution_tier="structural",   # off | structural | fact_aware | full
)
```

### Supply evolution metadata at ingest

```python
await rag.ingest(
    ["paper_1992_hrt.md"],
    namespace="medical",
    metadata={
        "effective_from":     datetime(1992, 6, 1, tzinfo=timezone.utc),
        "retracted":          True,
        "retracted_at":       datetime(2002, 7, 17, tzinfo=timezone.utc),
        "retraction_reason":  "WHI 2002 RCT invalidated findings",
    },
)
```

Supported metadata keys: `effective_from`, `effective_to`, `retracted`, `retracted_at`,
`retraction_reason`, `version_label`, `supersedes_document_id`.

### Query semantics

```python
# Default behavior (retracted_behavior="flag"): retracted docs returned + annotated
result = await rag.query("Is HRT cardioprotective?", namespace="medical")

# Filter retracted docs out
rag.config.retracted_behavior = "hide"
result = await rag.query("...", namespace="medical")

# Time-travel — datetimes MUST be timezone-aware
result = await rag.query(
    "What was the refund window?",
    namespace="policy",
    as_of=datetime(2023, 6, 1, tzinfo=timezone.utc),
)

# Version-scoped
result = await rag.query("How do I use StrEnum?", version_filter="Python 3.12")

# Per-call override: classic retrieval ignoring evolution
result = await rag.query("...", evolution_aware=False)
```

### Tune scoring weights per corpus

```python
report = await rag.tune_scoring_weights(
    namespace="medical",
    gold=[
        {"question": "...", "expected_substring": "..."},
        ...
    ],
    grid={
        "w_sem":            [0.3, 0.5, 0.7],
        "w_recent":         [0.0, 0.1, 0.3],
        "w_supersession":   [0.0, 0.1, 0.3],
    },
    mode="naive",
    write_back=True,  # updates rag.config to the best cell
)
print(report["best"])
```

`tune_scoring_weights` Cartesian-products the grid, scores each cell by case-insensitive
substring match against gold, and snapshots/restores config so a mid-grid exception leaves
your config untouched. Unknown weight names raise `ValueError`.

### Behavior modes

| Mode | `retracted_behavior` | `supersession_behavior` |
|---|---|---|
| `hide` | Filter out via WHERE clause + score multiplier | Filter out via NOT EXISTS |
| `flag` (default for retraction) | Return at natural rank, caller marks them | n/a |
| `prefer_new` | n/a | Score penalty (additive bonus to non-superseded docs) |
| `surface_both` (default for supersession) | Return both | Return both |

Both `retracted_behavior` and `supersession_behavior` are also per-call kwargs on `query()` / `ask()` for multi-tenant servers that need a different policy per request. See [`docs/cookbook/per-call-kwargs.md`](cookbook/per-call-kwargs.md) for the full list (also includes `memory_tier`, `retrieval_strategy`, `as_of`, `version_filter`, `evolution_aware`).

### Per-fact temporal columns on `relationships` (migration 006)

The same four temporal fields (`effective_from`, `effective_to`, `retracted`, `retracted_at`) that exist on `documents` ALSO exist as typed columns on the `relationships` table as of migration 006 (2026-05-20). `RelationshipResult` surfaces them on the read side. Populated by:

- The chunkshop SP-A bridge automatically for `kind='fact'` rows (see [`docs/cookbook/chunkshop-integration.md`](cookbook/chunkshop-integration.md) → Pattern M).
- Manual `known_relationships` dicts in `ingest_records()` — pass the same four optional keys.

Columns are queryable today. Default scoring does not yet consume them (Tier 3 follow-up).

### What's NOT in Tier 1

- Fact-level extraction into the `facts` table (Tier 2 — still a follow-up). NOTE: `fact_extractor="lede_spacy"` is implemented and builds a deterministic LLM-free graph (NER entities + co-occurrence `RELATED_TO` edges, no LLM/network); it does **not** populate the `facts` table yet. Requires `pip install 'pg-raggraph[lede_spacy]'` + `python -m spacy download en_core_web_sm`.
- LLM-inferred supersession / contradiction (Tier 3)
- Async slow-path fact-edge inference (Tier 3)

See `docs/cookbook/evolution-tracking.md` for the quickstart and
`docs/archive/superpowers/specs/2026-04-22-evolving-knowledge-rag-design.md` for the full four-tier
roadmap (dated audit-trail design spec).

### What's tested

Tier 1 ships with **34 evolution-specific integration tests** across the
core evolution-tracking, medical-HRT, Python-versioned-docs, living-
knowledge, and per-fact-temporal-relationships suites — plus 3 synthetic-
fixture corpora (medical retraction, software versioning, policy
effective-dates). The fixtures are small (2–4 docs each), purpose-built
to exercise the metadata code paths. A real-world retraction-corpus
benchmark (PubMed HRT) **did land** after this section was first
written — see `benchmarks/medical-hrt/` for 48 abstracts × 15 gold
questions × 5/5 retraction-aware + 5/5 time-travel passes. Tier 2
ambitions are tracked in the roadmap.

---

## Configuration

All settings configurable via environment variables (prefix `PGRG_`):

### Database
```bash
export PGRG_DSN=postgresql://user:pass@host:5432/db
export PGRG_POOL_MIN=2        # Min connections
export PGRG_POOL_MAX=10       # Max connections
```

### Namespace (multi-tenancy)
```bash
export PGRG_NAMESPACE=project-x
```
Or pass per-command: `pgrg query "..." -n project-x`

### Embedding Model
```bash
# Local embeddings (default — no API key needed)
export PGRG_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5  # 384 dim, ~65MB
export PGRG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5   # 768 dim, better quality
export PGRG_EMBEDDING_DIM=768                        # Must match model!

# API-based embeddings
export PGRG_EMBEDDING_PROVIDER=openai
export PGRG_EMBEDDING_MODEL=text-embedding-3-small
export PGRG_EMBEDDING_DIM=1536
```

**Warning:** Changing embedding dimension after initial ingestion requires dropping and recreating vector tables. Set this before first `pgrg init`.

### LLM
```bash
export PGRG_LLM_BASE_URL=http://localhost:11434/v1
export PGRG_LLM_MODEL=llama3.2
export PGRG_LLM_API_KEY=   # Empty for local, set for cloud APIs
```

### Chunking
```bash
export PGRG_CHUNK_STRATEGY=auto      # auto | hierarchy
export PGRG_CHUNK_MAX_TOKENS=512     # Max tokens per chunk (auto strategy)
export PGRG_CHUNK_OVERLAP_TOKENS=50  # Overlap between chunks (auto strategy)
```

#### `auto` (default)
Detects markdown / code / prose from the source path and content, then chunks by structure with a token budget. Markdown splits on headings; code splits on `def`/`class`/`func` boundaries; plain text splits on sentence boundaries. Hard-splits oversized chunks to respect `chunk_max_tokens`.

#### `hierarchy` (opt-in)
Heading-prefixed chunker ported from the AGE bake-off. Each section body is prefixed with its markdown heading (or a derived title — first H1, else filename stem) so the embedder sees `heading + body` as one unit. **Does not enforce a token budget** — oversized sections pass through unchanged and get truncated at embed time, mirroring the benchmarked behavior.

**Use `hierarchy` when** your corpus has concrete, disambiguating per-document titles: case names, article titles, product names, Wikipedia-shaped pages. On the SCOTUS benchmark this cleared the ship threshold by 2.5× across all six retrieval modes.

**Do NOT use `hierarchy` when** your titles are format strings that repeat across documents: meeting updates ("Weekly sync: …"), ticket-prefix subjects, templated status reports. On such corpora the title prefix homogenizes embeddings and slightly regresses accuracy while raising hallucinations. See [`benchmarks/age-bakeoff/results/ACME-HIER-REPLICATION.md`](../benchmarks/age-bakeoff/results/ACME-HIER-REPLICATION.md) for the data.

### Retrieval
```bash
export PGRG_MAX_HOPS=2                # Graph traversal depth
export PGRG_TOP_K=10                  # Results per query
export PGRG_SIMILARITY_THRESHOLD=0.3  # Minimum similarity score
export PGRG_RETRIEVAL_STRATEGY=weighted        # weighted | pre_filter | vector_first
export PGRG_RETRIEVAL_OVERSAMPLE_FACTOR=10     # vector_first candidate sizing
```

`retrieval_strategy` controls the SQL shape of vector + metadata queries. The default `weighted` works everywhere; `pre_filter` is fastest when you have selective indexed predicates; `vector_first` is fastest for broad/no-predicate queries on single-namespace HNSW-eligible corpora. See [`docs/cookbook/retrieval-strategy.md`](cookbook/retrieval-strategy.md). Also available as a per-call kwarg.

### Metadata indexes (JSONB)
```bash
export PGRG_METADATA_INDEXES=tag,priority           # btree per-key on chunks.metadata
export PGRG_METADATA_INDEXES_GIN=true               # GIN on full chunks.metadata
export PGRG_DOCUMENT_METADATA_INDEXES=salesperson,product   # btree per-key on documents.metadata
export PGRG_DOCUMENT_METADATA_INDEXES_GIN=true              # GIN on full documents.metadata
```

Three index kinds (btree per-key / GIN whole-JSONB / typed generated columns) × two tables (`chunks` / `documents`). Auto-created at `connect()` time, idempotent. For production retrofit against live tables, use `rag.apply_metadata_indexes_concurrently()` instead (runs `CREATE INDEX CONCURRENTLY`). The full picture (including the runtime `recommend_metadata_indexes()` / `add_metadata_index()` / `list_metadata_indexes()` API and the chunks-vs-documents two-table model) is in [`docs/cookbook/metadata-indexes.md`](cookbook/metadata-indexes.md).

### Entity Resolution
```bash
export PGRG_RESOLUTION_THRESHOLD=0.85  # When to merge similar entities
export PGRG_TRGM_WEIGHT=0.4            # Trigram similarity weight
export PGRG_VEC_WEIGHT=0.6             # Vector similarity weight
```

### Ingestion Throttling

Ingestion is parallelized to saturate your LLM throughput. Control how aggressively
pg-raggraph uses your system with **profiles**:

```bash
export PGRG_INGEST_PROFILE=balanced  # default: safe for shared servers
```

| Profile | Docs | LLM calls | Embed batch | CPU usage | When to use |
|---------|------|-----------|-------------|-----------|-------------|
| `conservative` | 1 | 4 | 8 | ~1 core | Laptops, shared servers, production apps |
| `balanced` (default) | 2 | 8 | 16 | ~2-3 cores | Standard dev machines |
| `aggressive` | 4 | 16 | 32 | ~6 cores | Dedicated machines, CI runners |
| `max` | 8 | 32 | 64 | ~20+ cores | One-off batch jobs only |

Individual overrides work too:
```bash
export PGRG_DOC_CONCURRENCY=3        # override docs parallelism
export PGRG_EXTRACT_CONCURRENCY=12   # override LLM concurrency
export PGRG_EMBED_BATCH_SIZE=24      # override embed batch
export PGRG_NICE_LEVEL=10            # lower process priority (nice level 0-19)
```

From the CLI:
```bash
pgrg ingest ./docs/ -p aggressive           # use aggressive profile
pgrg ingest ./docs/ -p conservative --nice 10  # gentle + low priority
```

**Rule of thumb:** the parallelism you can use is limited by your LLM throughput.
Local LLMs (Ollama, vLLM on one GPU) saturate around 16 concurrent requests.
OpenAI API can handle 32+ concurrent requests easily.

---

## Ingesting Documents

### Supported Formats
- **Markdown** (`.md`) — heading-aware chunking
- **Text** (`.txt`) — sentence-aware chunking
- **Python** (`.py`) — function/class boundary chunking
- **JavaScript/TypeScript** (`.js`, `.ts`) — basic chunking
- **Other** — treated as plain text

### Via CLI
```bash
# Single file
pgrg ingest ./readme.md

# Directory (recursive)
pgrg ingest ./docs/

# Multiple paths
pgrg ingest ./readme.md ./docs/ ./src/

# With namespace
pgrg ingest ./docs/ -n production

# With verbose progress
pgrg -v ingest ./large-corpus/
```

### Via SDK
```python
from pg_raggraph import GraphRAG

async with GraphRAG() as rag:
    # Simple ingest
    await rag.ingest(["./docs/"])

    # With progress callback
    async def progress(msg):
        print(f"[progress] {msg}")

    await rag.ingest(
        ["./docs/"],
        namespace="production",
        on_progress=progress,
    )
```

### Dedup (Content Hash)
pg-raggraph automatically skips documents that haven't changed. You can safely re-run `pgrg ingest` on the same directory — unchanged files are skipped (based on SHA-256 content hash).

### What Happens During Ingest
1. Files are scanned and chunked based on structure (markdown headings, sentences, etc.)
2. Each chunk is embedded using local fastembed (no API call needed)
3. LLM extracts entities and relationships from each chunk
4. Entities are resolved against existing ones (pg_trgm fuzzy + vector similarity)
5. Everything is stored in PostgreSQL with content hashes for dedup

### Deferred extraction (background drain)

Step 3 above — LLM/lede entity + relationship extraction — is the slow leg.
On lede_spacy MHR, synchronous extraction costs ~1063 ms/doc; with an LLM
extractor it's much worse. Most queries — `naive` (vector + BM25) — don't
even need the graph.

`defer_extraction=True` decouples extraction from `ingest()`:

```python
# Producer: returns in ~18 ms/doc — chunks + embeddings only.
await rag.ingest_records(records, namespace="crm", defer_extraction=True)
# Doc is immediately naive-queryable. Graph fills in later.
```

A worker drains the queue out-of-band:

```bash
# One-shot (cron-friendly): exits 0 when queue is empty
pgrg --db $PGRG_DSN extract --namespace crm --once

# Long-running daemon: SIGTERM-graceful, emits metrics per iteration
pgrg --db $PGRG_DSN extract --namespace crm --daemon --poll-interval 1.0
```

Headline numbers (MHR, lede_spacy, 40 docs): **59.8× faster
time-to-queryable** (0.44s vs 26.27s); the deferred path's total
wall-time (B+C = 15.56s) is *also* faster than synchronous (26.27s)
because the synchronous path holds per-doc transactions open across
extraction.

The full guide — three architectural patterns (sync / cron / always-on
daemon), worked FastAPI end-to-end example, multi-worker safety
invariants, operator playbook — is at
**[cookbook/background-extraction.md](cookbook/background-extraction.md)**.

### Ingesting from a database (CRM / ERP / app schema)

The patterns above cover files on disk. For pulling rows out of a Postgres database (or any SQL source), see the worked end-to-end cookbook:

- **[cookbook/sales-crm-ingestion.md](cookbook/sales-crm-ingestion.md)** — synthetic sales-CRM schema (customers / orders / products / call notes) ingested into pg-raggraph. Covers document grain, frontmatter shape, two ingest patterns (Pattern A: disk-based; Pattern B: in-memory via `ingest_records()` — preferred for same-database pipelines), pinning known graph edges from foreign keys at ingest time, and a per-mode query comparison. Ships with `samples/sales-crm-demo-small.sql` (788 KB) and `-medium.sql` (2.4 MB) so you can `psql -f` and follow along verbatim.
- **[cookbook/chunkshop-integration.md](cookbook/chunkshop-integration.md)** — Pattern C: run [chunkshop](https://github.com/yonk-labs/chunkshop) into a pgvector table, then point pg-raggraph at it for the entity/relationship graph layer.

---

## Python SDK

### Basic Usage
```python
import asyncio
from pg_raggraph import GraphRAG

async def main():
    async with GraphRAG("postgresql://localhost:5434/pg_raggraph") as rag:
        # Ingest
        await rag.ingest(["./docs/"])

        # Query
        result = await rag.query(
            "What is the authentication flow?",
            mode="hybrid",
        )

        # Process results
        for chunk in result.chunks:
            print(f"[{chunk.score:.2f}] {chunk.document_source}")
            print(chunk.content[:200])

        # See connected entities
        for entity in result.entities:
            print(f"  {entity.name} ({entity.entity_type})")

        # Stats
        stats = await rag.status()
        print(f"\n{stats['documents']} docs, {stats['entities']} entities")

asyncio.run(main())
```

### Configuration Override
```python
from pg_raggraph import GraphRAG, PGRGConfig

rag = GraphRAG(
    dsn="postgresql://other-db/mydb",
    namespace="project-x",
    embedding_model="BAAI/bge-base-en-v1.5",
    embedding_dim=768,
    llm_base_url="https://api.openai.com/v1",
    llm_model="gpt-4o-mini",
    llm_api_key="sk-...",
    max_hops=3,
    top_k=20,
)
```

### QueryResult Structure
```python
result = await rag.query("...")

result.chunks          # list[ChunkResult]
result.entities        # list[EntityResult] - related entities
result.relationships   # list[RelationshipResult] - connections
result.query_mode      # str: "naive" | "local" | "global" | "hybrid"
result.latency_ms      # float: how long the query took
```

---

## REST API

> **The bundled server is for local development and demos.** It ships without authentication, rate limiting, upload size limits, or CORS configuration. Do not expose `pgrg serve` directly to the public internet. For production, run it behind a reverse proxy (nginx, Caddy, Cloudflare, Traefik) that adds auth, TLS, and rate limits — or embed `create_app()` in your own FastAPI application that supplies those middlewares. See [Production deployment](#production-deployment) below.

### Launch Server
```bash
pgrg serve --port 8080
# Or from code:
# from pg_raggraph.server import create_app
# app = create_app(dsn=...)
```

### Endpoints

**POST /query** — Ask a question
```bash
curl -X POST http://localhost:8080/query \
  -F "question=How does authentication work?" \
  -F "mode=hybrid" \
  -F "namespace=default"
```

**POST /ingest** — Upload files
```bash
curl -X POST http://localhost:8080/ingest \
  -F "files=@doc1.md" \
  -F "files=@doc2.md" \
  -F "namespace=default"
```

**GET /status** — Graph stats
```bash
curl http://localhost:8080/status
```

**GET /graph?namespace=default** — Nodes & edges for visualization
```bash
curl http://localhost:8080/graph
```

**GET /health** — Health check (includes DB connectivity)
```bash
curl http://localhost:8080/health
# {"status":"ok","db":"connected"}
```

### Production deployment

`pgrg serve` is a reference server for development, demos, and single-user local use. It intentionally does not bundle:

- Authentication
- Rate limiting
- Upload size caps on `/ingest`
- MIME-type validation on `/ingest`
- CORS policy

If you want to deploy it for external users, put a reverse proxy in front that adds those. The recommended pattern:

```
Client → (Cloudflare / nginx / Caddy / Traefik) → pgrg serve → Postgres
          ↑
          handles: TLS, auth, rate limit, upload caps, access logs
```

Minimum proxy-side checks for any public deployment:

- Enforce auth (API key, OAuth, basic auth, or whatever your stack uses).
- Cap `POST /ingest` request bodies to a sensible limit (10-100 MB).
- Rate-limit `POST /ingest` and `POST /query` separately.
- Access-log every request with the authenticated caller.
- Terminate TLS; don't run `pgrg serve` on HTTP over a public IP.

For multi-tenant deployments, always pass `namespace` on every request from the proxy layer — the server does not enforce tenant boundaries on its own.

Alternatively, embed `create_app()` in your own FastAPI app so you can wire your existing middleware (auth, rate-limit, CORS) into the pg-raggraph endpoints directly.

---

## Web UI

```bash
pgrg serve
# Or: pgrg demo  (ingests bundled sample corpus + opens browser)
```

Visit `http://localhost:8080`:
- **Chat panel** — ask questions in natural language
- **Graph visualization** — see entities and relationships (vis-network)
- **Provenance** — each answer shows which chunks contributed

The UI is a single HTML file (~200 lines, htmx + vis-network from CDN). No build step, no node_modules.

---

## Troubleshooting

### "Cannot connect to PostgreSQL"
```
Error: Cannot connect to PostgreSQL at postgresql://...
```
Check: Is `docker compose ps` showing the postgres container? Is the port correct (default 5434)? Does `PGRG_DSN` point to the right database?

### "0 entities extracted"
The LLM isn't running. Either:
1. Start Ollama: `ollama serve`
2. Set `PGRG_LLM_BASE_URL` to a reachable endpoint
3. Accept vector-only RAG (set `-m naive` on queries)

### Ingestion is slow
LLM extraction dominates ingestion time. For a 10KB document:
- Local fastembed embedding: <1s
- LLM entity extraction: 2-5s per chunk
- A 50-chunk document takes 2-5 minutes

Speed it up by:
- Using a faster LLM (GPT-4o-mini vs local 7B model)
- Increasing parallelism (future work)
- Reducing chunk count (larger `chunk_max_tokens`)

### "Path not found"
```
Error: Path not found: ./docs/
```
The path doesn't exist or is mistyped. Check with `ls`.

### Queries return 0 chunks
Possible causes:
1. Namespace mismatch — you ingested into one namespace, querying another
2. Empty namespace — run `pgrg status` to check counts
3. Query is too specific — try broader wording

### Results are inconsistent between runs
LLM extraction is non-deterministic. Run the ingest with a lower temperature or use deterministic mode if your LLM supports it. The entity resolution will merge most duplicates over time.

---

## Further Reading

- [README.md](../README.md) — quick start
- [PROJECT.md](../PROJECT.md) — project goals and values
- [research/main-research.md](../research/main-research.md) — architecture rationale
- [research/competition-comparison.md](../research/competition-comparison.md) — vs LightRAG, Neo4j, Zep
