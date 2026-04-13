# graphrag-psql (jimysancho)

> "Implementation based on LightRAG and nano-graphrag to connect with psql"

**Repo:** [jimysancho/graphrag-psql](https://github.com/jimysancho/graphrag-psql)
**License:** MIT | **Stars:** 15 | **Forks:** 4 | **Commits:** 71
**Author:** Jaime Sancho Molero (solo developer)
**Status:** All 71 commits in 6 days (Oct 22-28, 2024), no activity since. Abandoned.
**Companion article:** [Knowledge Graphs with PostgreSQL (ReadyTensor)](https://app.readytensor.ai/publications/knowledge-graphs-with-postgresql-eQyINuo4ojwW)

---

## What It Is

A Python implementation that bridges LightRAG/nano-graphrag concepts with PostgreSQL as the persistent storage backend. PostgreSQL + pgvector replaces file-based storage for entities, relationships, and chunks, while **NetworkX remains the in-memory graph engine** for all traversal operations. The graph is serialized to a `graph.graphml` file on disk.

This is more of a tutorial/learning project than a production library. The ReadyTensor article confirms it was created as an educational exercise.

---

## Relationship to LightRAG / nano-graphrag

### What It Borrows
- Two-step entity/relationship extraction paradigm (extract then merge)
- Prompt templates for entity extraction (modified for JSON output)
- **"Gleaning"** — iterative re-extraction from the same chunk to catch missed entities
- Keyword extraction approach (high-level and low-level keywords)
- Local vs. global query dichotomy

### What It Changes
- **Storage:** PostgreSQL + pgvector instead of file-based storage
- **Merging:** fuzzywuzzy fuzzy string matching (threshold ~75) instead of LLM-based deduplication
- **Chunking:** Custom semantic chunking using embedding similarity rather than token-based splitting
- **Output parsing:** Forces LLM to return Python dictionaries, parsed via `eval()` (security issue)
- **Query modes:** Adds hybrid (local + global combined) and naive RAG (pure vector, no graph)

---

## Source Code Structure

```
graphrag-psql/
├── docker-compose.yml               # Single PostgreSQL service
├── init.sql                          # CREATE EXTENSION vector; CREATE EXTENSION uuid-ossp;
├── requirements.txt
└── graphrag/
    ├── config.py                     # GlobalConfig Pydantic model
    ├── main.py                       # Public API: insert, local_query, global_query, hybrid_query, naive_query
    ├── database/
    │   ├── base.py                   # SQLAlchemy engine, session factory
    │   └── models.py                 # Chunk, Entity, Relationship ORM models
    ├── indexing/
    │   ├── chunking.py               # Semantic chunking with embedding similarity
    │   ├── extraction.py             # Entity/relationship extraction + fuzzywuzzy merging
    │   ├── types.py                  # Pydantic models for entities, relationships, chunks
    │   ├── upsert.py                 # Upsert to PG + NetworkX graph creation
    │   └── utils.py                  # Hash calculation
    ├── llm/
    │   ├── llm.py                    # OpenAI API calls (extraction, embeddings, keywords, generation)
    │   └── prompt.py                 # Prompt templates
    └── query/
        ├── generate.py               # Query orchestration (local, global, hybrid, naive)
        ├── graph_search.py           # NetworkX traversal (NOT PostgreSQL graph queries)
        ├── types.py                  # Query result types
        └── vector_search.py          # pgvector cosine similarity
```

~17 Python files across 4 subpackages.

---

## Database Schema

Three tables with UUID primary keys and pgvector columns:

### chunk

| Column | Type | Notes |
|--------|------|-------|
| chunk_id | UUID (PK) | Default uuid4 |
| text | Text | NOT NULL |
| chunk_embedding | Vector(1536) | pgvector |
| hash | String | NOT NULL, indexed |

### entity

| Column | Type | Notes |
|--------|------|-------|
| entity_id | UUID (PK) | Default uuid4 |
| hash | String | NOT NULL, indexed |
| entity_name | String | NOT NULL |
| entity_type | String | Default "unknown" |
| description | String | NOT NULL |
| entity_embedding | Vector(1536) | pgvector |
| chunk_id | UUID (FK → chunk) | CASCADE delete |

### relationship

| Column | Type | Notes |
|--------|------|-------|
| relationship_id | UUID (PK) | Default uuid4 |
| hash | String | NOT NULL, indexed |
| description | String | NOT NULL |
| relationship_embedding | Vector(1536) | pgvector |
| keywords | String | Nullable |
| weight | Float | Nullable |
| source_id | UUID (FK → entity) | CASCADE delete |
| target_id | UUID (FK → entity) | CASCADE delete |
| chunk_id | UUID (FK → chunk) | CASCADE delete |

**Key difference from postgres-graph-rag:** This project *does* store chunks with embeddings, maintaining provenance back to source text.

**Data loss bug:** The Pydantic model tracks multiple chunk_ids per entity (`Set[str]`), but the DB schema stores only one FK (`chunk_id`). The `get_chunk_id` property picks the first element from the set arbitrarily, losing multi-chunk provenance.

---

## Architecture: Document Flow

### Ingestion Pipeline

```
Input text
    ↓
[1] Semantic Chunking
    → Split into sentences
    → Batch embeddings (text-embedding-3-small)
    → Recursive grouping by cosine similarity (threshold 0.75)
    → Token budget: min 80, max 180 tokens per chunk
    → Optional overlap: last 15% of words prepended to next chunk
    ↓
[2] Entity/Relationship Extraction (per chunk)
    → OpenAI gpt-4o-mini with extraction prompt
    → Gleaning: repeat up to max_gleaning times to catch missed entities
    → LLM returns Python dict → parsed via eval() (!)
    → Rate-limit handling (reduce batch size on 429s)
    → Hash-based caching: skip already-extracted chunks
    ↓
[3] Entity Merging (fuzzywuzzy)
    → fuzz.ratio(name_a, name_b) >= 75 AND types compatible → merge
    → Descriptions concatenated, chunk_ids unioned
    → kept_vs_merged mapping tracks consolidations
    ↓
[4] Relationship Remapping
    → Relationships referencing merged entities → remapped to surviving entity
    → Duplicate edges consolidated (descriptions combined, weights summed)
    ↓
[5] Embedding + Upsert
    → Compute embeddings for chunks, entities, relationships (parallel)
    → Hash-based dedup before insert
    → Upsert to PostgreSQL (sequential individual commits)
    ↓
[6] NetworkX Graph Creation
    → Build in-memory nx.Graph() (undirected)
    → Entities → nodes, Relationships → edges
    → Serialize to ./graph.graphml on disk
    ↓
    ⚠️ On subsequent calls: if graph.graphml exists, load from disk and RETURN.
       New data does NOT update the graph unless file is deleted manually.
```

### Query Pipeline (4 modes)

**Local Query:**
1. Extract keywords from question (high-level + low-level via LLM)
2. Vector similarity on **entity** table using keywords
3. Load NetworkX graph from disk
4. For each matched entity, find neighbors and edges in graph
5. Score chunks by entity-neighbor connection density
6. Top chunks → context → LLM for final answer

**Global Query:**
1. Extract keywords → vector similarity on **relationship** table
2. Load graph, score edges by `importance = (1 - order/total) * 0.7 + (weight/max_weight) * 0.3`
3. Map to chunks → LLM response

**Hybrid Query:** Run local + global in parallel, deduplicate chunks, combine contexts.

**Naive RAG:** Vector similarity directly on **chunk** table, no graph traversal.

---

## Entity Merging: fuzzywuzzy Approach

Uses `fuzzywuzzy.fuzz.ratio()` (Levenshtein distance-based similarity):

- Threshold: 75 (hardcoded)
- Match condition: name similarity >= 75 AND compatible entity types
- On merge: descriptions concatenated, chunk_ids unioned, relationships remapped
- **Limitations:**
  - Purely lexical — no semantic matching
  - "United States" and "USA" will NOT merge (different strings)
  - "Elon Musk" and "Musk" might not merge (ratio ~57)
  - Threshold not configurable
  - O(n²) comparison across all entities

---

## Graph Representation: NetworkX, NOT PostgreSQL

**The graph lives in NetworkX, not in the database.** PostgreSQL stores the raw data (entities, relationships, chunks with embeddings), but all graph traversal happens in-memory via NetworkX:

- `nx.Graph()` — **undirected**, losing directional relationship semantics
- Serialized to `./graph.graphml` on disk
- Loaded from file on subsequent calls (no DB round-trip for graph ops)
- **No Apache AGE, no recursive CTEs, no PostgreSQL graph queries**

This means PostgreSQL is really just a persistence layer for entities/chunks/embeddings. The "graph" part isn't in Postgres at all.

---

## Interesting: Semantic Chunking

The most sophisticated part of the codebase. Instead of naive token/character splitting:

1. Split text into sentences
2. Embed each sentence batch (5 sentences per batch)
3. Recursively group by cosine similarity (threshold 0.75)
4. Respect token budgets (80-180 tokens per chunk)
5. Prepend 15% overlap from previous chunk

This produces more semantically coherent chunks than character-based splitting, which helps downstream entity extraction quality.

---

## Dependencies

| Dependency | Purpose | Notes |
|------------|---------|-------|
| OpenAI API (gpt-4o-mini) | Extraction, keywords, generation | **Hardcoded, no abstraction** |
| OpenAI API (text-embedding-3-small) | All embeddings (1536 dim) | Hardcoded |
| SQLAlchemy | ORM for PostgreSQL | Synchronous sessions in async functions |
| pgvector | Vector storage + cosine similarity | **No vector indexes defined** |
| psycopg2 | Raw SQL for vector search | Separate from SQLAlchemy sessions |
| NetworkX | In-memory graph operations | All traversal here, not PG |
| fuzzywuzzy | Entity name matching | Levenshtein only |
| Pydantic | Data models + config | v2 |
| tiktoken | Token counting | GPT-4o-mini encoder |
| numpy | Embedding similarity in chunking | |
| unidecode | Diacritical mark removal | |
| Docker | PostgreSQL container | |

---

## Strengths

1. **Stores chunks.** Unlike postgres-graph-rag, this project preserves source text with embeddings. You can trace back to the original content.
2. **Semantic chunking.** Embedding-similarity-based chunking is more sophisticated than naive splitting.
3. **Multiple query modes.** Local, global, hybrid, and naive RAG give users flexibility.
4. **Gleaning.** Iterative re-extraction catches entities missed on first pass.
5. **Hash-based deduplication.** Prevents duplicate inserts on re-processing.
6. **Entity merging exists.** At least attempts fuzzy matching, unlike postgres-graph-rag which is exact-match only.
7. **Docker-ready.** `docker-compose up` gives you PostgreSQL + pgvector.
8. **Clear, readable code.** Well-organized into logical packages.

---

## Weaknesses and Gaps

### Critical Issues

1. **`eval()` on LLM output.** Arbitrary code execution vulnerability. LLM returns Python dict strings parsed via `eval()`. Should use `json.loads()` or `ast.literal_eval()`.

2. **No vector indexes.** No HNSW or IVFFlat indexes on any vector column. Every similarity search is a full sequential scan — O(n). Will not scale past a few thousand entities.

3. **Graph is NOT in PostgreSQL.** Despite the name "graphrag-psql", graph traversal happens in NetworkX loaded from a file. PostgreSQL is just entity/chunk/embedding storage. The "graph" part of GraphRAG isn't in Postgres at all.

4. **graph.graphml file stale lock.** If the file exists, new data insertions won't update the graph. Must manually delete the file to rebuild. No incremental updates.

5. **Entity chunk_id data loss.** Multi-chunk entities lose provenance — only one chunk_id persisted from the set.

### Architectural Issues

6. **No document management.** No document IDs, no ability to delete/update a specific document.
7. **Synchronous SQLAlchemy in async functions.** Blocks the event loop.
8. **Mixed database drivers.** SQLAlchemy ORM for CRUD + raw psycopg2 for vector search — two connection pools, inconsistent.
9. **Hardcoded to OpenAI gpt-4o-mini.** No provider abstraction.
10. **Undirected graph.** `nx.Graph()` loses directional relationship semantics ("A employs B" vs "B employs A").
11. **No community detection.** No Leiden clustering, no community summaries.
12. **No tests.** Zero test files.
13. **No CLI or API server.** Python library API only.
14. **No logging.** Uses `print()` statements.

---

## What This Teaches Us (for pg-raggraph)

### Adopt
- **Store chunks with embeddings.** Essential for provenance and hybrid retrieval.
- **Semantic chunking.** Embedding-similarity grouping produces better chunks than naive splitting.
- **Multiple query modes.** Local (entity-centric), global (relationship-centric), hybrid, and naive RAG are all useful.
- **Gleaning.** Iterative extraction catches more entities.
- **Hash-based dedup.** Efficient way to handle re-processing.

### Improve On
- **Graph traversal IN PostgreSQL.** Recursive CTEs or AGE — don't externalize to NetworkX files.
- **Real entity resolution.** Combine fuzzy string matching with vector similarity. Make threshold configurable. Handle abbreviations/acronyms.
- **Vector indexes.** HNSW indexes on all vector columns from day one.
- **Proper async DB.** asyncpg or psycopg3 async — no synchronous sessions in async code.
- **Pluggable LLM providers.** Abstract the LLM interface so users can use any provider.
- **Incremental graph updates.** New documents should update the graph without full rebuild.
- **Structured output parsing.** Use Pydantic structured output (never `eval()`).
- **Document lifecycle.** Track documents, support deletion with cascade.
- **Directed relationships.** Use a directed graph to preserve "A → B" vs "B → A" semantics.

### Key Insight

The name "graphrag-psql" is misleading — the graph isn't in PostgreSQL at all. It's a NetworkX file graph with PostgreSQL used for vector/entity storage. This is the core opportunity for pg-raggraph: actually put the graph IN PostgreSQL and query it with SQL/Cypher, eliminating the file-based NetworkX dependency entirely.

---

**Sources:**
- [graphrag-psql GitHub Repository](https://github.com/jimysancho/graphrag-psql)
- [Knowledge Graphs with PostgreSQL (ReadyTensor)](https://app.readytensor.ai/publications/knowledge-graphs-with-postgresql-eQyINuo4ojwW)
