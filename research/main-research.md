# pg-raggraph — Distilled Research Reference

> Production-quality GraphRAG in a single PostgreSQL instance. No graph DB. No vector DB. No AGE.

---

## The Problem

Vector-only RAG fails on multi-hop questions ("Who owns this service?" "What's the escalation path?"). GraphRAG solves this but currently requires 2-3 databases (PG + Neo4j + vector store) with sync headaches, or accepting LightRAG's AGE backend disasters. No production-quality PG-first library exists.

## Our Approach

**Adjacency tables + recursive CTEs + pgvector + pg_trgm.** Standard SQL. Works on every managed PG provider.

---

## Competitive Landscape (What Exists)

| Project | Stars | PG-Native? | Status | Verdict |
|---------|-------|------------|--------|---------|
| **LightRAG** | 33K | Storage adapter (AGE) | Active | Best algorithm (dual-level retrieval). PG backend broken — 17hr migrations, 3-5min queries on 3.5K nodes. AGE issues closed NOT_PLANNED. |
| **MS GraphRAG** | 20K | No | Active | Origin algorithm. $33K indexing, no incremental updates, no PG backend. |
| **Graphiti** | 24.8K | No (Neo4j/FalkorDB) | Active | Temporal knowledge graphs for agents. Different niche. |
| **postgres-graph-rag** | 16 | Yes (CTEs) | Stale 4mo | Validates our approach. No chunk storage, no entity resolution, 75% features vaporware. |
| **graphrag-psql** | 15 | No (NetworkX files) | Abandoned 18mo | Graph isn't in PG despite the name. eval() security hole. Good semantic chunking. |
| **Neo4j Aura** | Commercial | No | Active | $65+/mo. GPL/commercial license. Deepest graph+RAG but separate DB. |
| **Zep** | Commercial | No (Neo4j) | Active | $1.25/1K msgs. Managed temporal GraphRAG. SOC 2/HIPAA. |

## Why Not Apache AGE

Evaluated extensively (`research/apache-age-evaluation.md`). Rejected because:
1. **Cloud killed.** Only Azure supports it. No RDS, Supabase, Neon, GCP.
2. **Can't combine with pgvector.** Cypher and vector similarity can't share a single query. CTEs can.
3. **Slower for GraphRAG patterns.** 2-40x slower than CTEs for 1-3 hop traversals.
4. **Documented disasters.** LightRAG #2255: 49B estimated rows, 17hr migration for 407K edges.

---

## Key Innovations to Adopt

### From LightRAG: Dual-Level Retrieval
The killer feature behind 33K stars. Instead of community summaries (MS GraphRAG's expensive approach):
- LLM extracts **low-level keywords** (entity names) and **high-level keywords** (themes) from the query
- Low-level → entity vector search → graph traversal for precise facts
- High-level → relationship vector search → broader topic retrieval
- **6,000x cheaper** retrieval than MS GraphRAG (~100 tokens vs ~610K tokens per query)

### From postgres-graph-rag: Recursive CTE Traversal
Bidirectional, cycle-safe, namespace-scoped graph traversal in pure SQL:
```sql
WITH RECURSIVE graph_walk AS (
    SELECT id, 0 AS depth, ARRAY[id] AS path
    FROM entities WHERE id = ANY(seed_ids)
    UNION ALL
    SELECT e2.id, gw.depth + 1, gw.path || e2.id
    FROM graph_walk gw
    JOIN relationships r ON (r.src_id = gw.id OR r.dst_id = gw.id)
    JOIN entities e2 ON e2.id = CASE
        WHEN r.src_id = gw.id THEN r.dst_id ELSE r.src_id END
    WHERE gw.depth < 3 AND e2.id != ALL(gw.path)
)
SELECT DISTINCT id FROM graph_walk;
```

### From graphrag-psql: Semantic Chunking
Embedding-similarity grouping instead of naive character splitting. Respects sentence boundaries, token budgets, and semantic coherence. Worth adopting.

### From Obsidian RAG Research: Compiled Knowledge + Provenance
- **Graph-boosted search:** 1.2x similarity boost for entities connected via graph edges
- **Provenance tagging:** `extracted` / `inferred` / `ambiguous` per fact
- **Delta tracking:** Content hash manifest to only process new/changed documents
- **LLM Wiki pattern:** Pre-synthesized summaries stored in DB, not computed at query time

---

## Schema Design (Reference)

```sql
-- Documents: source tracking + lifecycle
CREATE TABLE documents (
    id BIGSERIAL PRIMARY KEY,
    namespace TEXT NOT NULL,
    content_hash TEXT NOT NULL,          -- delta tracking
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(namespace, content_hash)
);

-- Chunks: preserve source text + embeddings
CREATE TABLE chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT REFERENCES documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding vector(1536),
    token_count INTEGER,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Entities: graph nodes with embeddings
CREATE TABLE entities (
    id BIGSERIAL PRIMARY KEY,
    namespace TEXT NOT NULL,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    description TEXT,
    embedding vector(1536),
    community_id INTEGER,               -- Leiden clustering result
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(namespace, name)             -- entity resolution target
);

-- Relationships: graph edges (directed)
CREATE TABLE relationships (
    id BIGSERIAL PRIMARY KEY,
    namespace TEXT NOT NULL,
    src_id BIGINT REFERENCES entities(id) ON DELETE CASCADE,
    dst_id BIGINT REFERENCES entities(id) ON DELETE CASCADE,
    rel_type TEXT NOT NULL,
    weight FLOAT DEFAULT 1.0,
    description TEXT,
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Provenance: link entities/relationships back to source chunks
CREATE TABLE entity_chunks (
    entity_id BIGINT REFERENCES entities(id) ON DELETE CASCADE,
    chunk_id BIGINT REFERENCES chunks(id) ON DELETE CASCADE,
    confidence FLOAT DEFAULT 1.0,       -- extraction confidence
    provenance TEXT DEFAULT 'extracted', -- extracted | inferred | ambiguous
    PRIMARY KEY (entity_id, chunk_id)
);

CREATE TABLE relationship_chunks (
    relationship_id BIGINT REFERENCES relationships(id) ON DELETE CASCADE,
    chunk_id BIGINT REFERENCES chunks(id) ON DELETE CASCADE,
    confidence FLOAT DEFAULT 1.0,
    provenance TEXT DEFAULT 'extracted',
    PRIMARY KEY (relationship_id, chunk_id)
);
```

**Indexes (critical for performance):**
```sql
CREATE INDEX idx_rel_src ON relationships(src_id);
CREATE INDEX idx_rel_dst ON relationships(dst_id);
CREATE INDEX idx_rel_src_type ON relationships(src_id, rel_type);
CREATE INDEX idx_entity_ns_name ON entities(namespace, name);
CREATE INDEX idx_entity_type ON entities(entity_type);
CREATE INDEX idx_entity_community ON entities(community_id);
CREATE INDEX idx_chunk_doc ON chunks(document_id);
CREATE INDEX idx_doc_ns_hash ON documents(namespace, content_hash);

-- Vector indexes (HNSW for speed)
CREATE INDEX idx_entity_embed ON entities USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_chunk_embed ON chunks USING hnsw (embedding vector_cosine_ops);

-- Trigram index for entity resolution
CREATE INDEX idx_entity_name_trgm ON entities USING gin (name gin_trgm_ops);
```

---

## Hybrid Retrieval: The Core Differentiator

Single SQL query combining graph traversal + vector similarity (impossible with AGE):

```sql
-- Seed: find entities similar to query embedding
WITH seeds AS (
    SELECT id, 1 - (embedding <=> $1::vector) AS similarity
    FROM entities
    WHERE namespace = $2
    ORDER BY embedding <=> $1::vector
    LIMIT $3  -- top_k seeds
),
-- Expand: walk the graph N hops from seeds
neighborhood AS (
    SELECT id, 0 AS depth FROM seeds
    UNION ALL
    SELECT e2.id, n.depth + 1
    FROM neighborhood n
    JOIN relationships r ON (r.src_id = n.id OR r.dst_id = n.id)
    JOIN entities e2 ON e2.id = CASE
        WHEN r.src_id = n.id THEN r.dst_id ELSE r.src_id END
    WHERE n.depth < $4  -- max_hops
),
-- Collect chunks linked to neighborhood entities
relevant_chunks AS (
    SELECT DISTINCT c.id, c.content, c.embedding
    FROM chunks c
    JOIN entity_chunks ec ON ec.chunk_id = c.id
    WHERE ec.entity_id IN (SELECT DISTINCT id FROM neighborhood)
)
-- Rank by vector similarity to query
SELECT content, 1 - (embedding <=> $1::vector) AS score
FROM relevant_chunks
ORDER BY embedding <=> $1::vector
LIMIT $5;  -- top results
```

---

## Pipeline Architecture

```
Document Input
    ↓
[1] Semantic Chunking (embedding similarity, sentence-aware, token budgets)
    ↓
[2] Content Hash Check → skip if already ingested (delta tracking)
    ↓
[3] Embed Chunks (pgvector)
    ↓
[4] Entity/Relationship Extraction (LLM structured output — never eval())
    ↓
[5] Entity Resolution (pg_trgm fuzzy + vector cosine dedup, configurable threshold)
    ↓
[6] Bulk Upsert (executemany / COPY — not loops of individual INSERTs)
    ↓
[7] COMMIT (single transaction — ACID across all tables)
```

**Query modes (from LightRAG):**
- `local` — entity-centric: seed entities → graph traversal → chunk retrieval
- `global` — topic-centric: high-level keywords → relationship search → chunk ranking
- `hybrid` — local + global combined
- `naive` — vector-only chunk search (standard RAG fallback)

---

## Mistakes to Avoid (Learned from Competitors)

| Mistake | Who Made It | Our Fix |
|---------|-------------|---------|
| No chunk storage | postgres-graph-rag | `chunks` table with embeddings + `entity_chunks` provenance join |
| Graph in files, not PG | graphrag-psql (NetworkX) | All traversal via recursive CTEs in PostgreSQL |
| eval() on LLM output | graphrag-psql | Pydantic structured output only |
| Fake batch ops (loops) | postgres-graph-rag | True bulk via `executemany()` or `COPY` |
| Apache AGE dependency | LightRAG | Recursive CTEs — no extension beyond pgvector |
| No entity resolution | postgres-graph-rag | pg_trgm fuzzy + vector cosine at ingestion time |
| No document lifecycle | both PG attempts | `documents` table with cascade deletes |
| Undirected graph only | LightRAG, graphrag-psql | Directed `relationships` table (src_id → dst_id) |
| No vector indexes | graphrag-psql | HNSW indexes from day one |
| Hardcoded LLM provider | graphrag-psql | Pluggable provider interface (OpenAI, Ollama, Anthropic) |
| Full re-index on change | MS GraphRAG | Content hash delta tracking, incremental merge |
| No similarity threshold | postgres-graph-rag | Configurable cutoff for vector search + entity resolution |

---

## Feature Priority

### P0 — Must Ship
- Entity extraction (LLM structured output)
- Entity resolution (pg_trgm + vector dedup)
- Chunk storage with provenance
- Hybrid retrieval (CTE + pgvector, single query)
- Incremental ingestion (content hash)
- Async Python API (psycopg3)
- Pluggable LLM providers
- Document lifecycle (add/update/delete + cascade)

### P1 — Should Ship
- BM25 full-text search (tsvector/tsquery)
- Dual-level keyword extraction (LightRAG's approach)
- Multiple query modes (local/global/hybrid/naive)
- Community detection (Leiden in Python, results in PG)
- Docker compose dev setup
- True bulk operations

### P2 — Differentiators
- Compiled knowledge layer (pre-synthesized summaries with provenance)
- Graph-boosted search scoring (1.2x similarity for linked entities)
- MCP server (expose as agent tools)
- LlamaIndex PropertyGraphStore interface

---

## Detailed Research Index

| Document | Location | Covers |
|----------|----------|--------|
| LightRAG deep-dive | `research/lightrag.md` | Why 33K stars, dual-level retrieval, PG backend failures |
| postgres-graph-rag deep-dive | `research/postgres-graph-rag.md` | CTE approach, schema, shipped vs vaporware |
| graphrag-psql deep-dive | `research/graphrag-psql.md` | NetworkX graph, semantic chunking, security issues |
| Apache AGE evaluation | `research/apache-age-evaluation.md` | AGE vs CTEs decision matrix, benchmarks, cloud compat |
| Full research report | `skill-output/research-and-design/Research-Report-pg-raggraph.md` | OSS/commercial landscape, workflows, feature matrix |
| Research summary | `skill-output/research-and-design/Research-Summary-pg-raggraph.md` | Go/no-go brief |
| Research base | `skill-output/research-base/RB-*.md` | Market context, community signals, external docs |
