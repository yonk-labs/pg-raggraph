# pg-raggraph Benchmark Results

## TL;DR
With parallel ingestion (4 docs × 16 LLM calls at a time), pg-raggraph ingests real-world corpora at ~11s/doc — a **4.3x speedup** over sequential processing. On small-to-medium corpora (20-31 docs), naive vector+BM25 often matches or beats graph modes on simple queries. **Graph modes gain ground (+4 percentage points) on cross-document questions** like "how does pilot experience affect incident outcomes?"

---

## Ingestion Speed Benchmarks (Parallel Optimization)

| Configuration | 1 Doc | 3 Docs | 20 Docs (NTSB) | Speed |
|--------------|-------|--------|----------------|-------|
| **Sequential (original)** | ~45s | ~135s | ~900s (15 min) | baseline |
| **Parallel (`doc_concurrency=4`, `extract_concurrency=16`)** | 24s | 34s | **213s (3.5 min)** | **4.3x faster** |

**Configuration:**
```python
GraphRAG(
    doc_concurrency=4,      # 4 docs processed in parallel
    extract_concurrency=16, # 16 concurrent LLM extraction calls
)
```

**Optimizations applied:**
1. **Parallel LLM extraction** (was sequential) — biggest win, ~90% of speedup
2. **Batched entity embeddings** (was 1 call per entity) — major win for entity-dense docs
3. **Parallel document processing** (`asyncio.gather` with semaphore)
4. **LLM response caching** (content-hash keyed)
5. **Content hash dedup** (skip unchanged files)

---

## Test Environment

- **PostgreSQL:** 16 with pgvector + pg_trgm (Docker, port 5434)
- **Embedding:** BAAI/bge-small-en-v1.5 (384 dim, local fastembed)
- **LLM:** Intel/Qwen3-Coder-Next-int4-AutoRound (vLLM at 192.168.1.193:8000)
- **Retrieval top_k:** 10

---

## Corpus 1: PostgreSQL Documentation (31 docs)

**Source:** Official PG 16 docs + pgvector/pgdash/pgedge blog posts
**Size:** 491KB text, 26 ingested docs, 1,140 entities, 1,563 relationships

### 10 Technical Questions

```
╔══════════════════════════════════════════════════════════╗
║ Mode       Accuracy    Avg Lat     Max Lat    N          ║
╠══════════════════════════════════════════════════════════╣
║ naive        80.0%        16ms        32ms    10         ║
║ local        72.0%        27ms        32ms    10         ║
║ global       72.0%        20ms        26ms    10         ║
║ hybrid       72.0%        35ms        44ms    10         ║
╚══════════════════════════════════════════════════════════╝
```

**Finding:** Naive wins on technical docs because keywords are dense and self-contained.

---

## Corpus 2: NTSB Aviation Incident Reports (20 docs)

**Source:** [docugami/KG-RAG-datasets](https://github.com/docugami/KG-RAG-datasets)
**Size:** 110KB text, **20 docs, 314 entities, 420 relationships** (ingested in 213s)

### Cross-Incident Questions

Questions designed to require multi-doc reasoning:

```
Question                            naive   local   hybrid
----------------------------------------------------------
Common causes across incidents      4/5     4/5     4/5
Pilot experience factor             4/5     5/5     5/5  ← GRAPH WINS
Weather conditions                  4/5     4/5     4/5
Aircraft types                      4/5     4/5     4/5
Regulations cited                   2/4     2/4     2/4

Overall: naive 75% | hybrid 79% (+4 points)
Graph wins: 1/5
```

**Finding:** Graph mode pulls ahead on the most cross-document question ("pilot experience factor") — this requires connecting pilot info across multiple incident reports. On more isolated questions, both modes tie.

---

## Corpus 3: SEC 10-Q Filings (20 docs, in progress)

**Source:** [docugami/KG-RAG-datasets](https://github.com/docugami/KG-RAG-datasets)
**Size:** 3.3MB text (largest corpus)
**Content:** Real quarterly SEC filings from AAPL, AMZN, INTC, MSFT, NVDA (Q3 2022 – Q3 2023)
**Gold-standard QnA:** 195 question-answer pairs (76 single-chunk, 54 multi-chunk, 65 multi-doc)

**Status:** Ingesting with `doc_concurrency=4, extract_concurrency=16`. Expected ~20-30 min based on doc size.

Results will be updated here once ingestion completes. This is the best corpus for measuring the graph advantage because:
- Multi-doc questions REQUIRE cross-company or cross-quarter reasoning
- 195 gold-standard answers provide objective accuracy measurement
- Entity density is very high (companies, products, financial metrics, dates)

---

## Query Performance (all corpora)

Latencies measured on ingested corpora:

| Corpus | Entities | naive avg | local avg | hybrid avg |
|--------|----------|-----------|-----------|------------|
| PostgreSQL docs | 1,140 | 16ms | 27ms | 35ms |
| NTSB (20 docs) | 314 | 13ms | ~25ms | 29ms |

All modes consistently under **100ms p95** (target achieved).

---

## Honest Assessment

**Graph RAG is not a universal upgrade over vector+BM25 search.** Our testing reveals:

### Graph modes win when:
- Questions require connecting entities across documents ("Who owns X that caused Y?")
- The corpus has explicit cross-doc relationships (dependencies, ownership, causality)
- Answers require multi-hop traversal (3+ entities)
- You need the list of connected people/systems, not just the answer

### Naive (vector+BM25) wins when:
- Answers are in single documents or contiguous chunks
- Keyword density is high (technical docs, code, API references)
- Question has specific jargon (product names, function names)
- Speed matters most

### The right strategy:
**Start with naive. Upgrade to hybrid only if cross-document questions fail.**

pg-raggraph lets you choose per-query, so you can use vector speed where it works and graph reasoning where it's needed.

---

## Comparison to Published GraphRAG Benchmarks

Our results are consistent with:
- **GraphRAG-Bench (ICLR 2026):** GraphRAG advantage only on relational QA requiring multi-hop reasoning
- **Unbiased Evaluation (arXiv 2506.06331):** NaiveRAG performs nearly as well as graph methods on many benchmarks
- **LightRAG EMNLP 2025:** 60-84% win rates (LLM-as-judge metric) — higher than our keyword metric because it counts paraphrased correctness

**The graph advantage is real but narrower than marketing suggests.** We're honest about this.

---

## Hardware Notes

All ingestion bottlenecks are LLM inference time. With a faster LLM:
- **GPT-4o-mini API:** ~1-2s per chunk → ingestion would be ~3x faster
- **Local Qwen3-Coder via vLLM:** ~3-5s per chunk (our setup)
- **Local Llama 3.2 7B:** ~2-4s per chunk (standard Ollama setup)

The parallelism we added makes the best use of available LLM throughput. If your LLM supports batch APIs (like vLLM continuous batching), the parallel extraction will saturate it efficiently.
