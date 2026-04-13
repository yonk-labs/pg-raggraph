# postgres-graph-rag (h4gen)

> "A Python Library to perform Graph RAG in your Postgres DB without headaches"

**Repo:** [h4gen/postgres-graph-rag](https://github.com/h4gen/postgres-graph-rag)
**License:** MIT | **Version:** 0.1.2 (Dec 22, 2025) | **Stars:** ~16 | **Forks:** 2 | **Commits:** 26
**Author:** Hagen Hoferichter (solo developer, built in a 2-day weekend sprint)
**Status:** No activity since December 2025 (~4 months stale)

---

## Philosophy: "PostgreSQL Maximalism"

Stop managing separate vector databases (Pinecone, Weaviate), graph databases (Neo4j), and relational databases. Use PostgreSQL as the single engine for all three concerns via pgvector and native SQL features. The argument: standard vector-only RAG cannot understand relationships between entities, and adding a separate graph database creates sync complexity.

---

## What It Actually Is

~500 lines of Python across 4 source files. A genuinely minimal proof-of-concept that validates the "GraphRAG in pure PostgreSQL" idea using:
- **pgvector** for entity embeddings and similarity search
- **Recursive CTEs** for multi-hop graph traversal (no Apache AGE)
- **Adjacency list** schema (nodes + edges tables)
- **psycopg3 async** with connection pooling

### Source Code Structure

```
postgres_graph_rag/
    __init__.py      # Exports only PostgresGraphRAG
    core.py          # Main class: chunking, add_texts, query, format_context
    database.py      # DatabaseManager: schema, CRUD, vector search, graph traversal
    extractor.py     # LLMExtractor: triplet extraction, embeddings (OpenAI + Gemini)
    models.py        # ProviderConfig TypedDict, default model configs
tests/
    test_core.py     # 2 mock-only tests (no integration tests hitting PG)
```

---

## Database Schema

Two tables, JSONB metadata for extensibility ("forever schema" — no migrations needed):

### graph_nodes

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK, auto-generated |
| namespace | VARCHAR(255) | Multi-tenancy isolation |
| content | TEXT | Entity name/label |
| embedding | VECTOR(N) | pgvector, default 1536 dim |
| metadata | JSONB | Extensible key-value store |
| created_at | TIMESTAMPTZ | Auto-set |

Indexes: unique on `(namespace, content)`, HNSW on `embedding` with cosine ops.

### graph_edges

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK, auto-generated |
| namespace | VARCHAR(255) | Multi-tenancy isolation |
| source_node_id | UUID | FK → graph_nodes, CASCADE |
| target_node_id | UUID | FK → graph_nodes, CASCADE |
| relation | TEXT | Predicate label |
| weight | FLOAT | Default 1.0 (never used in retrieval) |
| metadata | JSONB | Extensible |
| created_at | TIMESTAMPTZ | Auto-set |

Unique constraint: `(namespace, source_node_id, target_node_id, relation)`.

**Critical observation:** This is a pure adjacency-list model. Nodes are entities (not document chunks). **There is no chunks table** — original text is discarded after entity extraction.

---

## Architecture: Document Flow

### Ingestion Pipeline

```
Input text(s)
    ↓
[1] Chunking (character-based, 1000 chars, 100 overlap — naive, splits mid-word)
    ↓
[2] Parallel LLM extraction (asyncio.gather across chunks)
    → Each chunk → LLM → List[Triplet(subject, predicate, object)]
    ↓
[3] Deduplicate entity names (Python set() — exact string match only)
    ↓
[4] Batch embedding (all unique entities in one API call)
    ↓
[5] Upsert nodes (sequential INSERT…ON CONFLICT in a loop, not true bulk)
    ↓
[6] Upsert edges (same sequential pattern)
    ↓
[7] COMMIT (single transaction)
```

### Query Pipeline

```
Question string
    ↓
[1] Embed the question
    ↓
[2] Vector search: cosine distance on graph_nodes → top_k seed entities
    ↓
[3] Recursive CTE: expand N hops from seeds (bidirectional, cycle-safe)
    ↓
[4] Fetch all edges between discovered nodes
    ↓
[5] Format as text context string:
        "Entities: - Entity1, - Entity2..."
        "Relationships: - Entity1 --[rel]--> Entity2"
```

**The query returns a formatted string, not an LLM answer.** The user passes this context to their own LLM for answer generation.

### Recursive CTE Graph Traversal

Bidirectional, cycle-safe, namespace-scoped — this is the most well-implemented part:

```sql
WITH RECURSIVE graph_expansion AS (
    -- Base: seed nodes from vector search
    SELECT id, content, metadata, 0 as depth, ARRAY[id] as visited
    FROM graph_nodes WHERE id = ANY(seed_ids) AND namespace = ns

    UNION ALL

    -- Recursive: neighbors in both directions
    SELECT n.id, n.content, n.metadata, ge.depth + 1, ge.visited || n.id
    FROM graph_expansion ge
    JOIN graph_edges e ON (e.source_node_id = ge.id OR e.target_node_id = ge.id)
    JOIN graph_nodes n ON (n.id = e.target_node_id OR n.id = e.source_node_id)
    WHERE ge.depth < max_hops AND e.namespace = ns
    AND n.id != ge.id AND NOT (n.id = ANY(ge.visited))
)
SELECT DISTINCT id, content, metadata FROM graph_expansion
```

**No Apache AGE.** Pure SQL recursive CTEs on standard adjacency tables.

---

## Entity Extraction

Uses structured LLM output to extract `(subject, predicate, object)` triplets.

**Extraction prompt:** "You are an expert knowledge graph extractor. Your task is to decompose the given text into atomic subject-predicate-object triplets."

**Supported providers:**
- **OpenAI:** `beta.chat.completions.parse()` with Pydantic structured output (default: gpt-5-nano)
- **Gemini:** `generate_content()` with JSON response schema (default: gemini-2.5-flash-lite)

**No entity resolution exists.** Despite the README advertising pg_trgm fuzzy matching + vector distance, there is zero implementation. Deduplication is purely `set()` on entity name strings + SQL `ON CONFLICT (namespace, content)`. "OpenAI", "Open AI", and "openai" become 3 separate nodes.

---

## Feature Inventory: Shipped vs. Vaporware

### Actually Shipped (v0.1.2)
- Graph schema (2 tables, JSONB metadata, namespacing)
- Character-based text chunking (configurable, injectable)
- LLM triplet extraction (OpenAI + Gemini)
- Vector embeddings for entity nodes (pgvector)
- Cosine similarity search
- Recursive CTE multi-hop graph traversal
- Upsert semantics (idempotent)
- Async architecture with connection pooling
- Namespace-based multi-tenancy
- Context formatting as text string

### Advertised But NOT Shipped
- **BM25 full-text search** — not implemented
- **Entity resolution (pg_trgm + vector)** — not implemented
- **Relationship scoring** — schema has weight column, never used
- **Metadata-based path filtering** — not implemented
- **Community detection** — not implemented (networkx dependency is unused)
- **Cluster summarization** — not implemented
- **Row-Level Security** — not implemented
- **MCP server** — not implemented despite being in marketing materials
- **Token tracking / latency monitoring** — not implemented
- **Hybrid search** — not implemented

**~75% of advertised features are unimplemented.** The README and HN post market a significantly more complete product than what exists.

---

## Dependencies

| Dependency | Purpose | Actually Used? |
|------------|---------|----------------|
| psycopg[binary,pool] >=3.1.18 | Async PG driver + pooling | Yes |
| pgvector >=0.2.5 | pgvector Python bindings | Yes |
| openai >=1.12.0 | OpenAI API client | Yes |
| google-genai >=0.1.0 | Gemini API client | Yes |
| pydantic >=2.6.0 | Structured extraction schemas | Yes |
| python-dotenv >=1.0.1 | Env var loading | Yes |
| pandas >=2.2.0 | DataFrame formatting (overkill) | Yes (unnecessarily) |
| networkx >=3.4.2 | Community detection (planned) | **No — unused** |
| matplotlib >=3.10.8 | Visualization (planned) | **No — unused** |
| ipykernel >=7.1.0 | Jupyter support | Marginal |

---

## Strengths

1. **Genuinely simple.** ~500 LOC, easy to read, understand, and fork.
2. **Correct core abstraction.** Adjacency list + pgvector + recursive CTEs is sound and avoids external dependencies.
3. **Async-native.** psycopg3 async with connection pooling done properly.
4. **Clean upsert semantics.** ON CONFLICT handling for both nodes and edges is correct and idempotent.
5. **Recursive CTE traversal is well-implemented.** Bidirectional, cycle-safe, namespace-scoped.
6. **Multi-provider LLM support.** OpenAI and Gemini with structured output parsing.
7. **Parallel extraction.** asyncio.gather across chunks for concurrent LLM calls.
8. **Transactional consistency.** All ingestion writes in a single COMMIT.
9. **Zero-migration schema.** JSONB metadata means no ALTER TABLE as features evolve.
10. **Philosophy resonates.** "PostgreSQL Maximalism" is a compelling pitch.

---

## Weaknesses and Gaps

### Fundamental Design Issues

1. **No chunk storage.** Original text chunks are discarded after entity extraction. You lose provenance — cannot retrieve the source text that supports a relationship. Cannot do hybrid chunk+graph retrieval. This is the biggest architectural flaw.

2. **No entity resolution.** Exact string matching only. Real-world LLM extraction produces variations ("OpenAI" / "Open AI" / "openai") that become separate nodes. The advertised pg_trgm approach doesn't exist.

3. **No document lifecycle.** No concept of "documents" — you can't delete a document and cascade-remove its entities/edges. No source tracking at all.

4. **No query-time entity extraction.** The query embeds the question string and searches for similar entity nodes. It does not extract entities from the question to do targeted graph lookups.

### Implementation Issues

5. **Fake batch operations.** `upsert_nodes_batch` and `upsert_edges_batch` are sequential loops of individual INSERT statements, not actual bulk operations. Will degrade with large entity counts.

6. **Naive chunking.** Default character-based chunker splits mid-word/mid-sentence.

7. **Edge weights unused.** Schema has weight column but traversal ignores it completely.

8. **No similarity threshold.** Vector search returns top_k by distance with no minimum cutoff.

9. **Context is plain text only.** No structured output (JSON, typed objects) for programmatic consumption.

10. **Pandas dependency for string formatting.** `_format_context` uses DataFrames just to iterate rows — unnecessary overhead.

### Project Health

11. **26 commits over 2 days, then silence.** No activity for ~4 months. High bus-factor risk.
12. **2 mock-only tests.** No integration tests hitting PostgreSQL. No edge case testing.
13. **Unused dependencies** (networkx, matplotlib) bloat the install.

---

## What This Teaches Us (for pg-raggraph)

### Adopt
- Adjacency list + pgvector + recursive CTEs is a viable architecture (no AGE needed for basics)
- Async psycopg3 with connection pooling is the right driver choice
- JSONB metadata for schema extensibility
- Namespace-based multi-tenancy
- Upsert semantics for idempotent ingestion

### Improve On
- **Store chunks.** Need a chunks table linked to source documents, with embeddings. Graph entities reference chunks, not replace them.
- **Real entity resolution.** pg_trgm fuzzy matching + vector cosine distance at ingestion time. Merge threshold configurable.
- **True bulk operations.** Use `executemany()` or `COPY` for batch inserts.
- **Document lifecycle.** Track source documents, support deletion with cascade.
- **Hybrid retrieval.** Combine vector similarity + graph traversal + BM25 full-text in one pipeline.
- **Query-time entity extraction.** Extract entities from the question, look them up in the graph, then traverse.
- **Edge weight in traversal.** Use relationship confidence/frequency in path ranking.
- **Provenance.** Track which chunk/document each entity and relationship came from.

---

**Sources:**
- [GitHub Repository](https://github.com/h4gen/postgres-graph-rag)
- [Show HN Discussion](https://news.ycombinator.com/item?id=46347143)
- [GraphRAG on Postgres: A Builder's Guide (Medium)](https://medium.com/@duckweave/graphrag-on-postgres-a-builders-guide-1c6d2ecf2eed)
