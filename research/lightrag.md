# LightRAG (HKUDS)

> "Simple and Fast Retrieval-Augmented Generation"

**Repo:** [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG)
**License:** MIT | **Stars:** 33K+ | **Forks:** 4.7K+ | **PyPI:** `lightrag-hku`
**Paper:** [arXiv 2410.05779](https://arxiv.org/abs/2410.05779) — EMNLP 2025 Findings
**Status:** Very active development, frequent releases, Discord community

---

## Why It Has Momentum

### The Problem It Solves

Microsoft GraphRAG (April 2024) introduced graph-based RAG but came with three deal-breakers:

1. **Absurd query-time cost** — ~610,000 tokens per query across multiple API calls for community summary scanning
2. **Full graph reconstruction on data changes** — Leiden community hierarchy must be entirely rebuilt
3. **Architectural heaviness** — bottom-up community summarization is complex and fragile

LightRAG (October 2024) attacks all three directly.

### The Key Innovation: Dual-Level Retrieval

Instead of pre-computing community summaries, LightRAG extracts entities and relationships directly, indexes them into vector databases, and retrieves via keyword-to-entity/relation matching combined with vector similarity. The dual levels:

1. **Low-level retrieval** — specific entities and their direct relationships. Query asks about "PostgreSQL" → retrieve the entity node and its immediate edges. Precise factual answers.

2. **High-level retrieval** — broader topics and themes. Retrieve clusters of related entities and relationships that collectively address a thematic question, **without pre-computed community summaries**.

The mechanism: an LLM analyzes the user query and produces both low-level keywords (entity names, technical terms) and high-level keywords (themes, concepts). These match against entity and relationship vector indexes simultaneously.

### Cost Comparison vs Microsoft GraphRAG

| Phase | GraphRAG | LightRAG | Difference |
|-------|----------|----------|------------|
| Retrieval tokens per query | ~610,000 | <100 | **~6,000x cheaper** |
| API calls per query | Multiple (proportional to communities) | Single | Orders of magnitude fewer |
| Indexing cost (32K words, GPT-4o) | ~$6-7 | Similar | Comparable |
| Incremental update | Full community rebuild | Merge new entities/relations | Dramatically cheaper |
| Query latency | ~120ms | ~80ms | ~30% faster |

### Benchmark Results

Evaluated across agriculture, CS, legal, and mixed domains (LLM-as-judge):
- vs NaiveRAG: **60-84.8% win rate** across domains
- vs GraphRAG: **Comparable or superior**, 48-54.8% advantage range
- Legal domain strongest: 83.6% comprehensiveness win rate vs NaiveRAG
- Consistently outperforms NaiveRAG, RQ-RAG, HyDE, and GraphRAG

**Caveat:** Independent evaluation (arXiv 2506.06331) found more nuanced results — fast-graphrag was most efficient, LightRAG second, and NaiveRAG performed nearly as well on some tasks. GraphRAG retained up to 10% accuracy advantage on relational QA requiring deep multi-hop reasoning.

### Why Developers Choose It

1. `pip install lightrag-hku` and go — defaults work out of the box
2. JSON + NanoVectorDB + NetworkX for zero-infrastructure prototyping
3. Swap to PG/Neo4j/Milvus for production without code changes
4. Web UI included (React 19, knowledge graph visualization)
5. Multiple LLM providers (OpenAI, Ollama, Azure, Gemini, Bedrock, Anthropic)
6. Docker compose single-command deployment
7. Academic credibility (EMNLP 2025) + massive community (33K stars)

---

## Architecture Deep-Dive

### Document Processing Pipeline

```
Document Input
    ↓
[1] Chunking — chunk_token_size=1200, overlap=100, TikToken tokenizer
    MD5 hash IDs with "chunk-" prefix
    ↓
[2] Entity/Relation Extraction — LLM extracts structured records
    Entity: [entity_label, name, type, description]
    Relation: [relation_label, source, target, keywords, description]
    Includes relationship_strength scoring
    ↓
[3] Deduplication & Merge — _merge_nodes_then_upsert(), _merge_edges_then_upsert()
    Merges duplicate entities across chunks/documents
    LLM re-summarizes merged descriptions
    ↓
[4] Graph Construction — Nodes (entities) + Edges (relations) into graph storage
    ↓
[5] Vector Indexing — Entities, relations, and chunks embedded into vector storage
    ↓
[6] KV Storage — Full docs, text chunks, LLM response cache, entity/relation metadata
```

Pipeline runs async with `max_parallel_insert` (default 2, max 10). Document status tracking (PENDING → PROCESSING → PROCESSED/FAILED) enables checkpoint recovery.

### Query Modes

| Mode | Retrieval Strategy |
|------|-------------------|
| `naive` | Vector-only chunk retrieval (standard RAG) |
| `local` | Low-level entity-focused retrieval |
| `global` | High-level topic-focused retrieval |
| `hybrid` | Local + global combined |
| `mix` | Knowledge graph + vector retrieval (recommended with reranker) |

### How It Differs From GraphRAG's Community Summarization

| Aspect | Microsoft GraphRAG | LightRAG |
|--------|-------------------|----------|
| Graph structure | Hierarchical communities via Leiden | Flat entity-relation graph |
| Summarization | Bottom-up summaries at each hierarchy level | Per-entity and per-relation descriptions only |
| Global queries | Scan all community summaries (expensive) | High-level keyword matching + graph traversal |
| Update cost | Rebuild community hierarchy | Merge new nodes/edges |
| Index size | Large (summaries at every community level) | Smaller (entity/relation descriptions + vectors) |
| Retrieval | Map-reduce across communities | Single vector query + graph hop |

### Storage Abstraction Layer

Four storage types with pluggable backends:

```
StorageNameSpace (ABC)
  ├── BaseKVStorage        → JsonKV | PG | Redis | MongoDB
  ├── BaseVectorStorage    → NanoVectorDB | PG | Milvus | Qdrant | Faiss | Chroma
  ├── BaseGraphStorage     → NetworkX | PG (AGE) | Neo4j | Memgraph | MongoDB
  └── DocStatusStorage     → JsonDocStatus | PG | MongoDB
```

Backends selected via string identifiers in a `STORAGES` registry. Adding a new backend = implement abstract methods + register.

---

## PostgreSQL Backend Details

### How PG is Used as "All-in-One"

PostgreSQL serves triple duty:
- **KV Store:** JSONB storage in `LIGHTRAG_KV` table
- **Vector DB:** pgvector for embedding storage and similarity search
- **Graph DB:** Apache AGE for Cypher-based graph queries

### Required Extensions

1. **pgvector** — vector similarity search (HNSW, IVFFLAT indexes)
2. **Apache AGE** — Cypher graph queries within PostgreSQL

### PG Tables Created

| Table | Purpose |
|-------|---------|
| `LIGHTRAG_KV` | Key-value pairs (JSONB) |
| `LIGHTRAG_VDB_CHUNKS` | Chunk embeddings |
| `LIGHTRAG_VDB_ENTITY` | Entity embeddings |
| `LIGHTRAG_VDB_RELATION` | Relation embeddings |
| `LIGHTRAG_DOC_STATUS` | Document processing state |
| `LIGHTRAG_DOC_FULL` | Full document content |
| `LIGHTRAG_DOC_CHUNKS` | Document chunks |
| `LIGHTRAG_FULL_ENTITIES` | Denormalized entity records |
| `LIGHTRAG_FULL_RELATIONS` | Denormalized relation records |
| `LIGHTRAG_LLM_CACHE` | LLM response cache |
| AGE graph: `chunk_entity_relation` | Knowledge graph (vertices + edges) |

11 tables + 1 AGE graph. Indexes: composite `(workspace, id)`, HNSW with m=16 ef=64 for vectors, pagination indexes.

### Known PG Backend Issues

**Issue #2255 — Migration Performance Catastrophe:**
- Upgrade from v1.4.9.1 to v1.4.9.4 caused **17+ hours of downtime**
- Root cause: `get_all_edges()` Cypher query via AGE generated a nested loop join with **49+ billion estimated intermediate rows**
- Database: 407K edges, 342K vertices
- EXPLAIN showed 251 trillion cost units with sequential scans
- **Issue closed as NOT_PLANNED**

**Issue #1277 — AGE Query Performance:**
- With just 3,500 nodes and 4,500 edges, query retrieval took **3-5 minutes**
- Users consistently report Neo4j delivers superior performance vs AGE

**Issue #1927 — Workspace Isolation:**
- Per-instance workspace isolation problems with PostgreSQL storages

**Issue #2122 — Intermittent Failures:**
- Document upload fails intermittently with `PGGraphQueryException` during entity merging

**Embedding Model Lock-in:**
- Vector dimension defined at table creation. Changing models = drop and recreate tables. No migration path.

---

## What Makes It Innovative (Summary)

1. **6,000x cheaper retrieval** than GraphRAG by eliminating community summary scanning
2. **Incremental updates** without graph reconstruction — merge new entities/relations
3. **Dual-level keyword extraction** separates entity-specific from topic-level retrieval
4. **Clean storage abstraction** — prototype with files, deploy with databases, same code
5. **Academic backing** (EMNLP 2025) + massive community validation (33K stars)

---

## Where It Falls Short

### General Weaknesses

1. **Undirected-only graphs** — BaseGraphStorage explicitly states edges are undirected. Loses directional semantics ("A employs B" ≠ "B employs A").
2. **LLM-as-judge benchmarks questionable** — no ground-truth accuracy evaluation. Independent eval shows NaiveRAG performs nearly as well on some tasks.
3. **32B+ parameter LLM requirement for extraction** — excludes smaller/cheaper models.
4. **No streaming support** documented.
5. **Workspace isolation is fragile** — string parameter, documented bugs.

### PG Backend Specifically

1. **Apache AGE is the weak link.** Multiple issues document severe performance problems. 3-5 minute queries with 3,500 nodes. Neo4j consistently outperforms. AGE is immature.
2. **Migration disaster closed as NOT_PLANNED.** 17-hour downtime with 407K edges signals PG backend is not treated as first-class.
3. **Two extensions, two failure modes.** pgvector AND AGE = two maintenance burdens, version compatibility issues, two query planners that don't optimize across each other.
4. **No combined graph+vector queries.** Entities stored in both AGE (graph nodes) and pgvector (embeddings) separately. Application layer orchestrates — no single SQL query combines both.
5. **Denormalized schema.** `LIGHTRAG_FULL_ENTITIES` and `LIGHTRAG_FULL_RELATIONS` duplicate data from AGE graph, creating consistency risks.
6. **Dollar-quoting workarounds** to avoid AGE's string escaping problems — impedance mismatch.
7. **N+1 query patterns.** No batch graph operations in PG implementation.

---

## What a PG-First Implementation Would Do Differently

This is the core opportunity for pg-raggraph:

1. **Skip Apache AGE entirely.** Use recursive CTEs, adjacency tables with proper indexes, or JSONB adjacency lists. AGE adds complexity without delivering real graph DB performance.

2. **Unified query execution.** Combine vector similarity (pgvector) with graph traversal (recursive CTEs) in a **single SQL query** — let the PG query planner optimize the whole operation.

3. **Single source of truth for entities.** Not duplicated across AGE graph + KV tables + full_entities tables. Foreign keys. Referential integrity.

4. **Native PG features for what AGE provides poorly:**
   - `LATERAL JOIN` for subgraph expansion
   - Window functions for scoring
   - Materialized views for pre-computed entity summaries
   - Partial indexes for workspace isolation

5. **Transactional consistency.** Entity extraction, graph updates, and vector indexing in a **single transaction** — not three separate storage backends hoping for eventual consistency.

6. **Proper schema migration.** Alembic instead of custom migration code that produced the 17-hour downtime.

7. **Adopt the dual-level retrieval idea** — it's genuinely novel and works. But implement it in SQL, not via AGE Cypher.

---

## Key Takeaway

LightRAG's momentum comes from solving a real problem (GraphRAG is too expensive) with a genuinely innovative approach (dual-level retrieval, incremental updates). But its PostgreSQL backend is a storage adapter bolted on, not a PG-first design — and Apache AGE is the weakest link. The dual-level retrieval concept is worth adopting; the storage architecture is worth replacing entirely.

---

**Sources:**
- [LightRAG GitHub](https://github.com/HKUDS/LightRAG)
- [LightRAG Paper (arXiv 2410.05779)](https://arxiv.org/abs/2410.05779)
- [EMNLP 2025 (ACL Anthology)](https://aclanthology.org/2025.findings-emnlp.568/)
- [Issue #2255: PG+AGE Migration](https://github.com/HKUDS/LightRAG/issues/2255)
- [Issue #1277: AGE Performance](https://github.com/HKUDS/LightRAG/issues/1277)
- [Issue #1927: Workspace Isolation](https://github.com/HKUDS/LightRAG/issues/1927)
- [LearnOpenCV: LightRAG Breakdown](https://learnopencv.com/lightrag/)
- [Unbiased Evaluation (arXiv 2506.06331)](https://arxiv.org/html/2506.06331v1)
- [Neo4j: Under the Covers With LightRAG](https://neo4j.com/blog/developer/under-the-covers-with-lightrag-extraction/)
