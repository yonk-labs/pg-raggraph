# pg-raggraph — Project Definition

## One-Liner

The fastest, simplest way to add knowledge-graph-powered RAG to any app — backed by the PostgreSQL you already run.

---

## Core Values (in order)

1. **Dead simple.** If it takes more than 5 minutes to go from `pip install` to first query, we failed. If a developer needs to read more than one page of docs to get started, we failed.
2. **Fast.** Sub-100ms retrieval. No round-trip waste. Single-query hybrid retrieval (graph + vector + text in one SQL statement). Local embeddings by default so there's no API latency tax on ingestion.
3. **Accurate.** Hybrid search (vector + graph + BM25). Structure-aware chunking (markdown sections, not blind character splits). Metadata extraction. Entity resolution that actually works. The graph should make answers measurably better than vector-only RAG.
4. **Light on tokens.** LLM calls are the expensive part. Minimize them. Local embeddings by default. Efficient entity extraction prompts. Cache everything cacheable. Never re-process unchanged documents.
5. **Small.** This is a library, not a platform. Tight scope. Few dependencies. Easy to audit. A single developer should be able to read the entire codebase in an afternoon.

---

## What It Is

A Python library + CLI + API server that turns PostgreSQL into a complete GraphRAG engine:

```bash
# Install
pip install pg-raggraph

# Ingest
pgrg ingest ./docs/ --db postgresql://localhost/mydb

# Query
pgrg query "Who owns the authentication service?"

# Or from Python
from pg_raggraph import GraphRAG
rag = GraphRAG("postgresql://localhost/mydb")
await rag.ingest("./docs/")
result = await rag.query("Who owns the authentication service?")
```

That's it. No Neo4j. No Pinecone. No config files. One database you already have.

---

## Access Layers

### SDK (Python library)
The core. Everything else is built on this.
```python
from pg_raggraph import GraphRAG

rag = GraphRAG(dsn="postgresql://localhost/mydb")
await rag.ingest(paths=["./docs/"], namespace="project-x")
result = await rag.query("How does auth work?", mode="hybrid")
```

### CLI
For humans and scripts. Wraps the SDK.
```bash
pgrg init --db postgresql://localhost/mydb
pgrg ingest ./docs/ --namespace project-x
pgrg query "How does auth work?"
pgrg status                    # ingested docs, entity count, graph stats
pgrg delete --namespace project-x
```

### API Server
FastAPI. For web UIs, microservices, and non-Python clients.
```bash
pgrg serve --port 8080
# POST /ingest, POST /query, GET /status, DELETE /namespace
```

### Web UI
Minimal. Ships with the API server. For non-technical users to:
- Upload documents (drag & drop)
- Ask questions (chat interface)
- Browse the knowledge graph (simple visualization)
- See provenance (which document said what)

Not a product. Not a platform. A developer tool's demo UI.

### AI Assistant Integrations
Baked-in, zero-config plugins for:
- **Claude Code** — skills that let Claude query and ingest your knowledge graph
- **Codex CLI** — tool definitions for OpenAI's agent
- **OpenClaw** — compatible tool interface
- **MCP Server** — universal protocol; any MCP-compatible agent can use it

```bash
pgrg mcp-serve   # Expose as MCP server — Claude, Cursor, etc. connect instantly
```

### Framework Adapters
Thin wrappers so pg-raggraph works inside existing pipelines:
- **LangChain/LangGraph** — custom Retriever + Tool
- **LlamaIndex** — PropertyGraphStore + QueryEngine implementation
- **Haystack** — DocumentStore adapter

These are adapters, not dependencies. pg-raggraph has zero dependency on any framework.

---

## Non-Negotiable Requirements

### Speed
- **Retrieval:** <100ms for hybrid queries (graph + vector) on graphs up to 100K entities
- **Ingestion:** Process 1,000 documents in minutes, not hours. Parallelized extraction. Bulk SQL operations.
- **Embeddings:** Local by default (sentence-transformers). No API call required for embeddings unless user opts in to OpenAI/Cohere/etc.

### Accuracy
- **Hybrid search:** Vector similarity + graph traversal + BM25 full-text — combined, not separate
- **Structure-aware chunking:** Markdown → split on headings/sections. Code → respect function boundaries. Plain text → semantic similarity grouping with sentence awareness.
- **Metadata extraction:** Pull title, headings, file path, dates, tags from documents automatically. Store as filterable JSONB.
- **Entity resolution:** pg_trgm fuzzy matching + vector cosine similarity at ingestion time. "OpenAI" and "Open AI" and "openai" merge into one node. Configurable threshold.
- **Directed relationships:** "A employs B" ≠ "B employs A". The graph preserves direction.

### Token Efficiency
- **Local embeddings by default.** Zero LLM API calls for embedding generation.
- **Content hash dedup.** Never re-process an unchanged document.
- **LLM cache.** Cache extraction results. Same chunk → same entities, no repeat API call.
- **Efficient extraction prompts.** Minimal token footprint. Structured output (Pydantic), not free-form parsing.
- **Batch extraction.** Group chunks to reduce per-call overhead.

### Simplicity
- **Zero config to start.** Sensible defaults for everything. Override what you want.
- **One extension dependency.** pgvector. That's it. pg_trgm is built into PostgreSQL.
- **Auto-migration.** Schema creates itself on first run. No Alembic. No manual SQL.
- **Namespace isolation.** Multiple projects in one database. No collision.

---

## The Demo (Wow Factor)

A single command that takes someone from zero to "holy shit" in under 2 minutes:

```bash
# 1. Start PostgreSQL (if they don't have one)
docker compose up -d

# 2. Install
pip install pg-raggraph

# 3. Ingest the pg-raggraph repo's own docs + research as a demo corpus
pgrg demo

# 4. Open browser
# → Web UI at localhost:8080
# → Chat with the knowledge graph
# → See the graph visualization
# → Ask: "What are the differences between LightRAG and Microsoft GraphRAG?"
# → Get an answer with provenance links, entity connections, and source citations
```

The demo should:
- Work offline (local embeddings, local LLM via Ollama if available, or fall back to a small bundled model)
- Show the graph visually (entities as nodes, relationships as edges)
- Show provenance ("This answer came from these 3 chunks in these 2 documents")
- Be faster than anything they've seen (sub-second responses)
- Show something vector-only RAG can't do (multi-hop question that requires graph traversal)

---

## Ideal End State

A developer who needs GraphRAG adds one dependency (`pg-raggraph`) to their existing PostgreSQL-backed app. They call `ingest()` and `query()`. It works. It's fast. It's accurate. They never think about graph databases, vector stores, or retrieval infrastructure again.

A non-technical user opens the web UI, drags in their documents, and asks questions in natural language. They get accurate answers with citations. They can see how concepts connect.

An AI assistant (Claude, Codex, Cursor) has pg-raggraph as a tool. It queries the knowledge graph to ground its responses in the user's actual data. No setup required beyond `pgrg mcp-serve`.

The library is small enough that one person can maintain it. The code is clear enough that anyone can fork and extend it. The PostgreSQL schema is simple enough to query directly with SQL if the library isn't enough.

---

## What It Is NOT

- **Not a platform.** No user accounts, no billing, no SaaS.
- **Not an LLM framework.** No prompt chains, no agent loops, no orchestration. Just retrieval.
- **Not a graph database.** No general-purpose Cypher, no SPARQL, no graph analytics beyond what RAG needs.
- **Not a vector database.** pgvector does the heavy lifting. We orchestrate.
- **Not opinionated about LLMs.** Works with OpenAI, Anthropic, Ollama, llama.cpp, whatever. Bring your own model.
- **Not trying to replace LangChain/LlamaIndex.** Integrates with them. Does one thing well.

---

## Success Metrics

- **Time to first query:** Under 5 minutes from `pip install`
- **Retrieval latency:** p95 < 100ms for graphs up to 100K entities
- **Accuracy:** Measurably better than vector-only RAG on multi-hop questions (benchmark with GraphRAG-Bench)
- **Lines of code:** Under 5,000 for the core library (excluding tests, adapters, UI)
- **Dependencies:** Under 10 runtime dependencies (excluding optional framework adapters)
- **Token cost:** <50% of LightRAG's token usage for equivalent ingestion
