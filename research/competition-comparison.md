# Feature Comparison: pg-raggraph vs Competition

## TL;DR
pg-raggraph is the only PostgreSQL-first GraphRAG library that works on every managed PG provider, uses single-query hybrid retrieval (CTE + pgvector + BM25), and ships in <1,500 LOC. It trades LightRAG's 33K-star ecosystem and community summaries for simplicity, portability, and the "just use Postgres" advantage.

---

## Feature Matrix

| Feature | pg-raggraph | LightRAG | postgres-graph-rag | graphrag-psql | Neo4j GraphRAG | Zep (Graphiti) |
|---------|:-----------:|:--------:|:-----------------:|:-------------:|:--------------:|:--------------:|
| **Core Engine** | | | | | | |
| Entity extraction (LLM) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Entity resolution (fuzzy + vector) | ✅ | ✅ (LLM) | ❌ | Levenshtein only | ✅ | ✅ |
| Relationship extraction | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Chunk storage with provenance | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| Directed relationships | ✅ | ❌ (undirected) | ❌ (undirected) | ❌ (undirected) | ✅ | ✅ |
| Community detection (Leiden) | ❌ (planned) | ❌ | ❌ | ❌ | ✅ | ❌ |
| Community summaries | ❌ | ❌ | ❌ | ❌ | ✅ (MS GraphRAG) | ❌ |
| Temporal fact tracking | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| | | | | | | |
| **Retrieval** | | | | | | |
| Vector similarity (cosine) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| BM25 full-text search | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Graph traversal | ✅ (recursive CTE) | ✅ (AGE/Neo4j) | ✅ (recursive CTE) | ❌ (NetworkX file) | ✅ (Cypher) | ✅ (Cypher) |
| Single-query hybrid (vector + graph + BM25) | ✅ | ❌ (separate) | ❌ (separate) | ❌ | ❌ (separate) | ❌ |
| Dual-level retrieval (entity + topic) | ✅ | ✅ | ❌ | Partial | ❌ | ❌ |
| Multiple query modes | ✅ (4 modes) | ✅ (5 modes) | 1 mode | 4 modes | 2 modes | 1 mode |
| | | | | | | |
| **Database** | | | | | | |
| PostgreSQL-native | ✅ | Adapter | ✅ | Partial (NetworkX) | ❌ (Neo4j) | ❌ (Neo4j/FalkorDB) |
| Works on AWS RDS | ✅ | ❌ (needs AGE) | ✅ | ✅ | N/A | N/A |
| Works on Supabase/Neon | ✅ | ❌ (needs AGE) | ✅ | ✅ | N/A | N/A |
| Works on Azure | ✅ | ✅ (AGE supported) | ✅ | ✅ | N/A | N/A |
| pgvector (HNSW) | ✅ | ✅ | ✅ | ✅ (no index!) | N/A | N/A |
| Apache AGE required | ❌ | ✅ | ❌ | ❌ | N/A | N/A |
| Single DB (no graph DB) | ✅ | ✅ (with PG) | ✅ | ❌ (NetworkX file) | ❌ | ❌ |
| ACID transactions | ✅ | Partial | ✅ | ❌ | ❌ | ❌ |
| | | | | | | |
| **Ingestion** | | | | | | |
| Incremental updates (delta) | ✅ (content hash) | ✅ | ❌ | ❌ (full rebuild) | ✅ | ✅ |
| Markdown-aware chunking | ✅ | ❌ (token-based) | ❌ (character) | ✅ (semantic) | ❌ | ❌ |
| LLM response caching | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Batch embedding | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Document lifecycle (delete) | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ |
| | | | | | | |
| **Interface** | | | | | | |
| Python SDK (async) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| CLI | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| REST API | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Web UI | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| MCP server | ❌ (planned) | ❌ | Advertised (not shipped) | ❌ | ❌ | ❌ |
| LangChain adapter | ❌ (planned) | ❌ | ❌ | ❌ | ✅ | ✅ |
| LlamaIndex adapter | ❌ (planned) | ❌ | ❌ | ❌ | ✅ | ❌ |
| | | | | | | |
| **Operations** | | | | | | |
| Local embeddings (no API) | ✅ (fastembed) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Pluggable LLM providers | ✅ (OpenAI-compat) | ✅ (many) | ✅ (OpenAI/Gemini) | ❌ (OpenAI only) | ✅ | ✅ |
| Namespace multi-tenancy | ✅ | ✅ (workspace) | ✅ | ❌ | ❌ | ✅ |
| Structured logging | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Error messages (not tracebacks) | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Docker compose ready | ✅ | ✅ | ❌ | ✅ | N/A | N/A |
| | | | | | | |
| **Project Health** | | | | | | |
| Stars | 0 (new) | 33K+ | 16 | 15 | 2K+ | 24.8K |
| License | MIT | MIT | MIT | MIT | Apache 2.0 | Apache 2.0 |
| Core LOC | ~1,500 | ~10K+ | ~500 | ~1,700 | Large | Large |
| Test coverage | 55+ tests | Yes | 2 tests | 0 tests | Yes | Yes |
| Last activity | Active (2026-04) | Active | Dec 2025 (stale) | Oct 2024 (abandoned) | Active | Active |
| Contributors | 1 | Many | 1 | 1 | Many | Many (Zep team) |

---

## Key Differentiators

### pg-raggraph wins on:

1. **Cloud portability** — Only PG-native GraphRAG that works on ALL managed providers (RDS, Supabase, Neon, GCP Cloud SQL). LightRAG requires AGE (Azure only).

2. **Single-query hybrid retrieval** — CTE + pgvector + BM25 in ONE SQL statement. Every competitor does separate graph and vector queries with application-layer merging.

3. **Simplicity** — 1,500 LOC vs 10K+ (LightRAG). 9 dependencies. One database. No AGE, no Neo4j, no NetworkX files.

4. **Local embeddings by default** — fastembed with ONNX runtime (~65MB). No PyTorch (2GB), no API key required to start.

5. **Error handling** — Friendly errors, path validation, namespace validation, logged warnings. Competitors show raw tracebacks (postgres-graph-rag, graphrag-psql) or swallow errors silently (LightRAG AGE backend).

6. **Directed relationships** — "A employs B" ≠ "B employs A". LightRAG, postgres-graph-rag, and graphrag-psql all use undirected graphs.

### pg-raggraph loses on:

1. **Community & ecosystem** — 0 stars vs 33K (LightRAG), 24.8K (Graphiti). No community, no Discord, no StackOverflow answers.

2. **Community detection / summaries** — Not implemented. MS GraphRAG and Neo4j offer global queries via community hierarchies.

3. **Temporal knowledge** — Zep/Graphiti tracks when facts change. pg-raggraph has no time dimension.

4. **Framework integrations** — No LangChain/LlamaIndex adapters shipped yet. Neo4j and Zep have mature integrations.

5. **Answer generation** — pg-raggraph returns chunks (retrieval only). Doesn't synthesize an answer. Competitors like LightRAG include the answer generation step.

6. **Production scale validation** — Tested on small fixtures. No 100K+ entity benchmarks. LightRAG and Neo4j have production deployments.

---

## When to Choose What

| Use Case | Best Choice | Why |
|----------|-------------|-----|
| "I already use PostgreSQL and want GraphRAG" | **pg-raggraph** | No new infrastructure, works on your existing PG |
| "I need the most battle-tested OSS GraphRAG" | **LightRAG** | 33K stars, EMNLP paper, active community |
| "I need temporal knowledge for AI agents" | **Zep/Graphiti** | Purpose-built for evolving facts and agent memory |
| "I need enterprise support and Cypher" | **Neo4j GraphRAG** | Mature, commercial support, deepest graph features |
| "I want the simplest possible setup" | **pg-raggraph** | 1 command install, 1 database, 9 deps |
| "I'm on AWS RDS and can't install extensions beyond pgvector" | **pg-raggraph** | Only option that works without AGE |
| "I need community detection / global queries over themes" | **Neo4j or MS GraphRAG** | They have Leiden + hierarchical summaries |

---

## Performance Comparison (Where Measured)

| Metric | pg-raggraph | LightRAG | postgres-graph-rag |
|--------|:-----------:|:--------:|:-----------------:|
| Retrieval latency (test data) | **16-36ms** | ~80ms (claimed) | Not benchmarked |
| Token cost per query | ~100 tokens (embed only) | ~100 tokens | ~100 tokens |
| Ingestion (4 docs, ~100 entities) | ~10s | Similar | Similar |
| Entity resolution | pg_trgm + vector (0.85 threshold) | LLM-based (expensive) | None |
| HNSW index on entities | ✅ | ✅ | ❌ (no indexes) |
| BM25 alongside vector | ✅ | ❌ | ❌ |

---

## Summary

pg-raggraph occupies a specific niche: **the simplest possible GraphRAG for teams already on PostgreSQL who can't/won't add Neo4j or AGE**. It's not trying to be LightRAG (ecosystem) or Neo4j (enterprise) or Zep (temporal agents). It's trying to be the pgvector-equivalent for GraphRAG: the extension-level solution that makes PostgreSQL good enough that you don't need a specialized database.

The technical differentiator (single-query CTE + pgvector + BM25) is genuine and architecturally impossible for AGE-based implementations to replicate. The cloud portability story is strong. The gaps (community detection, temporal tracking, answer generation) are real but addressable without architectural changes.
