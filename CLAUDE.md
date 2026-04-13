# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**pg-raggraph** is a PostgreSQL-native GraphRAG library. It implements knowledge graph construction, entity extraction, and hybrid retrieval (vector similarity + graph traversal) using PostgreSQL as the single backing store — no separate graph database or vector database required.

**Core thesis:** pgvector (vector search) + adjacency tables + recursive CTEs (graph traversal) + PostgreSQL full-text search (BM25) = a complete GraphRAG stack in one ACID-compliant database. No graph database extensions required.

## Architecture

### PostgreSQL Extensions Required
- **pgvector** — vector similarity search (HNSW/IVFFlat indexes)
- **pg_trgm** — trigram fuzzy matching for entity resolution

### Why NOT Apache AGE
We evaluated AGE extensively (see `research/apache-age-evaluation.md`) and decided against it:
- **Cloud compatibility** — AGE requires `shared_preload_libraries` (PG restart). Only Azure supports it among managed providers. No AWS RDS, no GCP Cloud SQL, no Supabase, no Neon. This kills adoption.
- **No pgvector integration** — AGE Cypher and pgvector cannot combine in a single query. The core GraphRAG operation (graph traversal + vector similarity) requires two round-trips with AGE but one query with recursive CTEs.
- **Performance** — Recursive CTEs are 2-40x faster for 1-3 hop traversals, which is the typical GraphRAG pattern. AGE defaults to sequential scans and has produced catastrophic query plans (LightRAG issue #2255: 49 billion estimated rows, 17-hour migration).
- **Proven alternative** — postgres-graph-rag already validates that adjacency tables + recursive CTEs + pgvector is sufficient for full GraphRAG.

Our graph approach: **adjacency tables** (`entities` + `relationships`) with proper indexes, **recursive CTEs** for multi-hop traversal, all composable with pgvector in unified SQL queries.

### Design Principles
- **PostgreSQL-first** — not a storage adapter bolted onto another framework. SQL is the first-class query interface.
- **Single database** — all data (documents, chunks, entities, relationships, embeddings, community summaries, provenance metadata) lives in one PostgreSQL instance.
- **Async Python** — native async with connection pooling (asyncpg or psycopg3 async).
- **Incremental updates** — graph updates on document change without full re-indexing. Track ingested documents via content hashes.
- **Pluggable LLM providers** — entity extraction and embedding generation work with any provider (OpenAI, Anthropic, Ollama, etc.).

### Key Subsystems
1. **Ingestion pipeline** — document chunking → embedding generation → entity/relationship extraction (LLM, parallel via asyncio semaphores) → entity resolution (pg_trgm fuzzy + vector dedup) → graph storage in a single per-document transaction
2. **Graph store** — adjacency tables (`entities` + `relationships`) with JSONB properties, recursive CTEs for multi-hop traversal, proper indexes on src_id/dst_id for fast joins
3. **Hybrid retrieval** — combines pgvector cosine similarity with recursive CTE graph traversal and BM25 (`to_tsquery` with OR semantics) full-text search in unified SQL queries
4. **Smart mode** (default) — confidence-triggered routing. Runs naive first; ships if confidence ≥ 0.7, applies cheap 1-hop graph boost if 0.4-0.7, escalates to full hybrid if < 0.4
5. **Chunking** — auto-detects markdown (heading-aware), code (function/class boundaries for Python/JS/TS/Go/Rust), or plain text (sentence-aware). Hard token-split fallback prevents oversized chunks from overflowing LLM context
6. **Ingestion profiles** — `conservative` / `balanced` (default) / `aggressive` / `max` control `doc_concurrency` and `extract_concurrency` for CPU budget
7. **`pgrg devmem`** — convenience CLI for developer knowledge bases with dev-tuned extraction prompt (person/service/library/file/commit/incident/ADR entities) and code-aware chunking

### Prior Art to Reference
Detailed research docs are in `research/`:
- **LightRAG** (33K stars) — dual-level retrieval is the key innovation to adopt; PG backend is a storage adapter with AGE issues. See `research/lightrag.md`
- **postgres-graph-rag** (h4gen) — validates recursive CTEs + pgvector approach; but no chunk storage, no entity resolution, ~500 LOC weekend prototype. See `research/postgres-graph-rag.md`
- **graphrag-psql** (jimysancho) — graph is actually in NetworkX files, not PG; good semantic chunking; eval() security hole. See `research/graphrag-psql.md`
- **Apache AGE** — evaluated and rejected as a dependency. See `research/apache-age-evaluation.md`
- **nano-graphrag** — ~1100 LOC, cleanest code to understand GraphRAG internals
- **LlamaIndex PropertyGraphStore interface** — the abstraction to implement for framework interoperability
- Research base available at `skill-output/research-base/` with competitive landscape and market context

## Development

### Tech Stack
- **Language:** Python 3.12+
- **Database:** PostgreSQL 16+ with pgvector and pg_trgm extensions
- **Package manager:** uv
- **Testing:** pytest with pytest-asyncio
- **Linting:** ruff

### Commands
```bash
# Environment setup
uv sync                          # Install dependencies
uv run pytest                    # Run all tests
uv run pytest tests/unit/        # Unit tests only (no DB required)
uv run pytest tests/integration/ # Integration tests (requires running PG)
uv run pytest -k "test_name"     # Run a single test
uv run ruff check .              # Lint
uv run ruff format .             # Format

# Database (Docker)
docker compose up -d postgres    # Start PostgreSQL with extensions
docker compose down              # Stop database
```

### Database Setup
Tests and local development use a Docker PostgreSQL instance with pgvector and pg_trgm pre-installed. Connection string defaults to `postgresql://postgres:postgres@localhost:5432/pg_raggraph`.

### Project Layout
```
src/pg_raggraph/        # Main package
  core/                 # Extraction, chunking, embedding interfaces
  graph/                # Adjacency table graph store, recursive CTE traversal
  vector/               # pgvector store, similarity search
  retrieval/            # Hybrid retrieval combining graph + vector + BM25
  community/            # Leiden clustering, community summaries
  knowledge/            # Compiled knowledge layer, provenance tracking
tests/
  unit/                 # No database required
  integration/          # Requires running PostgreSQL
```

## Conventions

- All database operations are async. Use connection pools, never single connections.
- Entity resolution happens at ingestion time, not query time.
- Every extracted fact carries provenance metadata: source document, chunk, extraction confidence, `extracted` vs `inferred` vs `ambiguous` classification.
- Graph schema uses JSONB metadata columns for extensibility — avoid ALTER TABLE migrations for new metadata fields.
- Namespace-aware design throughout — support multi-tenant isolation via PostgreSQL schemas or namespace columns.
