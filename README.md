# pg-raggraph

> **PostgreSQL-native GraphRAG.** Knowledge-graph retrieval with vector search, BM25, and graph traversal — all in a single SQL query. No Neo4j. No Pinecone. No Apache AGE. Just the PostgreSQL you already run.

```bash
pip install pg-raggraph
pgrg devmem ingest ./my-repo/
pgrg devmem ask "who owns the authentication service?"
```

**Real benchmark on 909-doc real-world codebase:**

| Mode | Avg Top Score | Latency | vs Naive |
|------|:-------------:|:-------:|:--------:|
| naive (vector+BM25) | 0.602 | 109ms | baseline |
| **naive_boost** ⭐ | **0.716** | **107ms** | **+18.9% accuracy** |
| **smart** (default) | **0.716** | 127ms | **+18.9%** at routing |
| local (graph traversal) | 0.614 | 423ms | +1.9% |
| hybrid (local+global) | 0.614 | 482ms | +1.9% |

**Graph boost gives you +18.9% accuracy at the same latency as plain vector search.** That's the win.

---

## How It Works

```mermaid
flowchart LR
    A[Your Docs] -->|chunk| B[Chunks]
    B -->|embed| C[pgvector]
    B -->|extract entities| D[LLM]
    D -->|resolve w/ pg_trgm| E[Entity Graph]
    E -->|CTE traversal| F[Knowledge Graph]
    C --> G[Query Engine]
    F --> G
    G -->|smart routing| H[Results]
```

1. **Ingest** documents → structure-aware chunking → batched embeddings → LLM entity extraction (parallel) → pg_trgm + vector entity resolution → one transaction per doc
2. **Store** everything in PostgreSQL: chunks, embeddings, entities, relationships, full-text index
3. **Query** with 6 retrieval modes. The default (`smart`) picks the right strategy per query based on confidence

---

## Retrieval Modes Explained

```mermaid
flowchart TD
    Q[User Query] --> N[Run naive: vector + BM25]
    N --> C{Top score?}
    C -->|≥ 0.7 high conf| SHIP[Return as-is<br/>~85ms]
    C -->|0.4-0.7 medium| BOOST[Apply graph boost:<br/>re-rank by 1-hop neighbors<br/>~90ms]
    C -->|< 0.4 low| EXPAND[Escalate to local mode:<br/>seed→expand→rank<br/>~220ms]
    SHIP --> R[Results]
    BOOST --> R
    EXPAND --> R
```

### All 6 Modes

| Mode | What it does | When to use | Typical Latency |
|------|--------------|-------------|-----------------|
| **`smart`** ⭐ | Routes between naive/boost/expand based on confidence | **Default. Always.** | 85-220ms |
| `naive` | Vector similarity + BM25 full-text search | Fastest. Simple factual questions. | ~85ms |
| `naive_boost` | Naive + cheap 1-hop graph re-rank of top-K | Best single-mode: +18.9% accuracy, same speed | ~90ms |
| `local` | Seed entities via vector → graph traversal N hops → rank chunks | When you need chunks connected via graph edges | ~220ms |
| `global` | Search by relationships → find chunks connected to them | Entity-relationship questions | ~150ms |
| `hybrid` | local + global merged | Most exhaustive (and slowest) | ~450ms |

**TL;DR:** Use `smart` (the default). If you want to manually pin it, use `naive_boost`.

---

## Quick Start (under 5 minutes)

### 1. Start PostgreSQL
```bash
git clone https://github.com/yonk-tools/pg-raggraph.git
cd pg-raggraph
docker compose up -d   # PostgreSQL 16 + pgvector + pg_trgm on port 5434
```

### 2. Install & set your LLM
```bash
pip install pg-raggraph

# Option A: OpenAI (fastest, pay-as-you-go)
export PGRG_LLM_BASE_URL=https://api.openai.com/v1
export PGRG_LLM_API_KEY=sk-...
export PGRG_LLM_MODEL=gpt-4o-mini

# Option B: Ollama (free, local)
ollama pull llama3.2 && ollama serve
```

### 3. Initialize the schema
```bash
pgrg init
```

### 4. Pick your flavor

#### A. General RAG
```bash
pgrg ingest ./docs/
pgrg query "what does this codebase do?"
```

#### B. **Developer knowledge base** (recommended)
```bash
pgrg devmem init
pgrg devmem ingest ./my-repo/ -p aggressive
pgrg devmem ask "who owns the auth service?"
```

Devmem uses a dev-tuned extraction prompt that extracts `person`, `service`, `library`, `file`, `commit`, `incident`, `ADR` entity types and uses code-aware chunking for Python/JS/TS/Go/Rust.

### 5. Query with the Python SDK
```python
import asyncio
from pg_raggraph import GraphRAG

async def main():
    async with GraphRAG("postgresql://localhost:5434/pg_raggraph") as rag:
        await rag.ingest(["./docs/"])

        # Default is smart mode
        result = await rag.query("How does auth work?")

        print(f"Mode chosen: {result.query_mode}")     # e.g. smart[boosted]
        print(f"Confidence:  {result.confidence}")      # high / medium / low
        print(f"Latency:     {result.latency_ms:.0f}ms")

        for chunk in result.chunks[:3]:
            print(f"\n[{chunk.score:.3f}] {chunk.document_source}")
            print(chunk.content[:200])

asyncio.run(main())
```

---

## Architecture

```mermaid
graph TB
    subgraph "pg-raggraph (Python, <1.5K LOC)"
        CLI[pgrg CLI]
        API[FastAPI server]
        SDK[GraphRAG SDK]
        CLI --> SDK
        API --> SDK
        SDK --> ING[Ingestion Pipeline]
        SDK --> RET[Retrieval Engine]
        ING --> CHK[Chunker<br/>markdown/code/text]
        ING --> EMB[fastembed<br/>local 384-dim]
        ING --> EXT[LLM Extractor<br/>httpx+OpenAI API]
        ING --> RES[Entity Resolver<br/>pg_trgm + vector]
        RET --> SM[Smart Router]
        SM --> NV[Naive Query<br/>vector+BM25]
        SM --> GB[Graph Boost<br/>1-hop re-rank]
        SM --> LC[Local Mode<br/>recursive CTE]
    end

    subgraph "PostgreSQL 16"
        PGV[pgvector HNSW]
        PGT[pg_trgm GIN]
        FTS[tsvector full-text]
        TBL[(Tables:<br/>documents<br/>chunks<br/>entities<br/>relationships<br/>entity_chunks<br/>relationship_chunks)]
    end

    NV --> PGV
    NV --> FTS
    GB --> TBL
    LC --> TBL
    RES --> PGT
    RES --> PGV
```

**One extension** (`pgvector`) + **one built-in** (`pg_trgm`). Works on AWS RDS, Supabase, Neon, GCP Cloud SQL, Azure, self-hosted — anywhere modern PostgreSQL runs.

---

## Schema

```mermaid
erDiagram
    documents ||--o{ chunks : contains
    chunks ||--o{ entity_chunks : links
    chunks ||--o{ relationship_chunks : links
    entities ||--o{ entity_chunks : tagged
    entities ||--o{ relationships : source
    entities ||--o{ relationships : target
    relationships ||--o{ relationship_chunks : evidence

    documents {
        bigint id PK
        text namespace
        text content_hash
        text source_path
        jsonb metadata
    }
    chunks {
        bigint id PK
        bigint document_id FK
        text content
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
```

6 data tables + 2 meta tables. Auto-migrates on first connect.

---

## What It Does Well

- ✅ **+18.9% accuracy** on real-world dev corpus (909 docs)
- ✅ **Sub-100ms retrieval** for most queries
- ✅ **~5s/doc ingestion** (parallelized, with OpenAI gpt-4o-mini)
- ✅ **Works on any managed PostgreSQL** (RDS, Supabase, Neon, Cloud SQL)
- ✅ **Local embeddings by default** — no API keys to start
- ✅ **Single SQL query hybrid retrieval** — vector + BM25 + graph in one round-trip
- ✅ **115 passing tests** — unit + integration + real-LLM E2E + server
- ✅ **Throttle profiles** — `conservative`/`balanced`/`aggressive`/`max`
- ✅ **`rag.ask()` + `/ask` endpoint** — grounded LLM answers with source citations
- ✅ **MCP server** — `pgrg mcp-serve` for Claude Desktop, Cursor, Zed
- ✅ **FastAPI server + web UI** — `pgrg serve` or `pgrg demo`
- ✅ **Schema migrations** — per-filename tracking, applied on every connect
- ✅ **Incremental re-ingest** — changed files atomically replace stale docs

## What It Doesn't Do (yet)

- ❌ **No LangChain/LlamaIndex adapters** — planned, not built
- ❌ **No community detection** — Leiden clustering optional extra, not wired in by default
- ❌ **No streaming answers** — LLM answer generation is single-shot, not streamed

**See [ASSESSMENT.md](ASSESSMENT.md) for the full no-BS evaluation.**

---

## Configuration

All settings via environment variables (prefix `PGRG_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `PGRG_DSN` | `postgresql://postgres:postgres@localhost:5434/pg_raggraph` | Database connection |
| `PGRG_NAMESPACE` | `default` | Data isolation namespace |
| `PGRG_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Local embedding model |
| `PGRG_EMBEDDING_DIM` | `384` | Vector dimensions |
| `PGRG_LLM_BASE_URL` | `http://localhost:11434/v1` | LLM endpoint (OpenAI-compatible) |
| `PGRG_LLM_MODEL` | `llama3.2` | LLM model name |
| `PGRG_LLM_API_KEY` | `""` | API key (empty for Ollama) |
| `PGRG_EXTRACTION_PROMPT` | `default` | `default` or `dev` (code-tuned) |
| `PGRG_CHUNK_STRATEGY` | `auto` | `auto` or `hierarchy`. Use `hierarchy` only when per-doc titles are concrete disambiguators (case names, article titles); it regresses on format-string titles like meeting updates. See [user-guide](docs/user-guide.md#chunking) and [bake-off evidence](benchmarks/age-bakeoff/results/ACME-HIER-REPLICATION.md). |
| `PGRG_INGEST_PROFILE` | `balanced` | `conservative` / `balanced` / `aggressive` / `max` |
| `PGRG_MAX_HOPS` | `2` | Graph traversal depth |
| `PGRG_TOP_K` | `10` | Results per query |
| `PGRG_BOOST_CONFIDENCE_THRESHOLD` | `0.7` | Above: ship naive, below: boost |
| `PGRG_EXPAND_CONFIDENCE_THRESHOLD` | `0.4` | Below: escalate to graph expansion |

---

## CLI Reference

### Core commands
```bash
pgrg init                         # Create schema, verify connection
pgrg ingest PATH... [-n NS] [-p PROFILE]  # Ingest files/directories
pgrg query "question" [-m MODE] [-n NS]   # Query (default mode: smart)
pgrg status [-n NS]               # Show graph statistics
pgrg delete -n NS                 # Delete namespace data
pgrg serve -p 8080                # Launch FastAPI + web UI
pgrg demo                         # Auto-ingest + launch demo
pgrg -v ingest ./docs/            # Verbose mode
```

### Developer knowledge base
```bash
pgrg devmem init                                 # Initialize devmem namespace
pgrg devmem ingest ./repo/ [-p PROFILE] [-n NS]  # Ingest code + docs
pgrg devmem ask "question" [-m MODE] [-n NS]     # Query with dev defaults
pgrg devmem status [-n NS]                       # Show devmem stats
```

### Throttle profiles
```bash
pgrg ingest ./docs/ -p conservative  # ~1 core   (shared servers, laptops)
pgrg ingest ./docs/ -p balanced      # ~3 cores  (default)
pgrg ingest ./docs/ -p aggressive    # ~6 cores  (dedicated dev box)
pgrg ingest ./docs/ -p max           # 20+ cores (batch jobs only)
```

---

## Documentation

- **[docs/user-guide.md](docs/user-guide.md)** — Full user guide with all modes
- **[docs/devmem-guide.md](docs/devmem-guide.md)** — Developer knowledge base walkthrough
- **[docs/FINDINGS.md](docs/FINDINGS.md)** — Engineering findings with evidence
- **[docs/blog-what-we-learned.md](docs/blog-what-we-learned.md)** — Narrative blog
- **[ASSESSMENT.md](ASSESSMENT.md)** — No-BS project assessment
- **[benchmarks/FINAL_RESULTS.md](benchmarks/FINAL_RESULTS.md)** — Cross-corpus benchmark data
- **[benchmarks/pg-agents-results.md](benchmarks/pg-agents-results.md)** — 909-doc real-world validation
- **[research/main-research.md](research/main-research.md)** — Architecture rationale
- **[research/competition-comparison.md](research/competition-comparison.md)** — vs LightRAG, Neo4j, Zep

---

## Why Not Apache AGE?

We evaluated AGE (PostgreSQL's graph extension) before writing a line of code. We rejected it for four reasons:

1. **Cloud killed.** AGE requires `shared_preload_libraries` — only Azure supports it among managed providers. No RDS, Supabase, Neon, or Cloud SQL.
2. **Can't combine with pgvector in a single query.** AGE Cypher and pgvector live in different worlds. The killer GraphRAG operation requires two round-trips with AGE, one query with recursive CTEs.
3. **Slower for GraphRAG patterns.** Benchmarks show recursive CTEs are 2-40x faster than AGE for 1-3 hop traversals — the typical GraphRAG pattern.
4. **Production disaster.** LightRAG Issue #2255: 17-hour migration with AGE caused by a query plan estimating 49 **billion** intermediate rows for a 681K-row join. Closed `NOT_PLANNED`.

Our architecture: adjacency tables + recursive CTEs + pgvector + BM25 in standard SQL. Works everywhere PostgreSQL runs.

See [research/apache-age-evaluation.md](research/apache-age-evaluation.md) for the full analysis.

---

## Competitors

| | pg-raggraph | LightRAG | Neo4j GraphRAG | Zep |
|---|:---:|:---:|:---:|:---:|
| PG-native | ✅ | AGE adapter (Azure only) | ❌ | ❌ |
| Single-query hybrid | ✅ | ❌ | ❌ | ❌ |
| Works on RDS/Supabase/Neon | ✅ | ❌ | N/A | N/A |
| License | MIT | MIT | Apache 2.0 | Apache 2.0 |
| Pricing | Free | Free | $65+/mo Aura | $1.25/1K msgs |
| Stars | new | 33K+ | 2K+ | 24.8K |
| Directed relationships | ✅ | ❌ (undirected) | ✅ | ✅ |
| Local embeddings default | ✅ | ✅ | ❌ | ❌ |

See [research/competition-comparison.md](research/competition-comparison.md) for the full feature matrix.

---

## Requirements

- Python 3.12+
- PostgreSQL 16+ with `pgvector` and `pg_trgm` extensions
- (Recommended) OpenAI-compatible LLM for entity extraction

## License

MIT

---

*Built with honest benchmarks and real data. See [ASSESSMENT.md](ASSESSMENT.md) for the unvarnished evaluation.*
