# pg-raggraph: Engineering Findings

> What we learned building a PostgreSQL-native GraphRAG library and benchmarking it on real-world corpora.

## TL;DR

1. **GraphRAG's advantage is narrower than marketing suggests.** On technical documentation, plain vector+BM25 often ties or beats graph modes. Graph shines specifically on cross-document questions.
2. **Ingestion speed is the bottleneck, not retrieval.** Sequential LLM extraction makes benchmarking impractical. Parallelizing gave us a **4.3x speedup** (20 docs: 15 min → 3.5 min).
3. **litellm was a supply-chain attack target** (March 2026). We use httpx directly with OpenAI-compatible API format instead.
4. **Apache AGE is the wrong abstraction for PG-native GraphRAG.** Recursive CTEs + pgvector are 2-40x faster for 1-3 hop traversals and work on every managed PG provider.
5. **Real data reveals real bugs.** Our edge case tests found 4 bugs that mock tests missed.

---

## Finding 1: The Graph RAG Advantage is Narrow But Real

### What we tested
- **PostgreSQL docs (31 docs, 1,140 entities):** Technical reference documentation
- **NTSB aviation reports (20 docs, 314 entities):** Incident reports with cross-document patterns
- **Custom corpora (10+ docs):** Synthetic engineering docs with known multi-hop relationships

### What we found

On **self-contained technical documentation** (PostgreSQL docs), naive vector+BM25 **outperformed** graph modes:

| Mode    | Accuracy | Avg Latency |
|---------|----------|-------------|
| naive   | **80.0%** | 16ms |
| local   | 72.0% | 27ms |
| global  | 72.0% | 20ms |
| hybrid  | 72.0% | 35ms |

**Why?** PostgreSQL documentation has dense keywords (`vacuum`, `hnsw`, `tsvector`) that BM25 nails immediately. Each concept is self-contained within one document. Graph expansion pulls in tangentially related entities, diluting the top-ranked results.

On **cross-document reports** (NTSB), graph modes pulled ahead on the specifically multi-hop question:

```
Question                            naive   local   hybrid
----------------------------------------------------------
Common causes across incidents      4/5     4/5     4/5
Pilot experience factor             4/5     5/5     5/5  ← GRAPH WINS
Weather conditions                  4/5     4/5     4/5
Aircraft types                      4/5     4/5     4/5

Overall: naive 75% | hybrid 79% (+4 points)
```

The one graph win ("pilot experience factor") required correlating pilot details across multiple incidents — exactly where following entity relationships across documents matters.

### The honest verdict

**Start with naive. Upgrade to hybrid only if cross-document questions fail.** GraphRAG gives you a 3-5 percentage point accuracy boost on specific multi-hop questions at the cost of 2x latency. For most direct factual questions, vector+BM25 is sufficient and faster.

This is consistent with the academic literature:
- **Unbiased GraphRAG Evaluation (arXiv 2506.06331)**: "NaiveRAG performs nearly as well as graph methods on many benchmarks"
- **GraphRAG-Bench (ICLR 2026)**: Graph advantage only on relational QA requiring multi-hop reasoning
- **fast-graphrag**: PageRank-based retrieval competitive with full GraphRAG

LightRAG's claimed 60-84% win rates (EMNLP 2025) use **LLM-as-judge** evaluation, which rewards paraphrased correctness. Our keyword-recall metric is more conservative but more objective.

---

## Finding 2: Parallelization is the #1 Ingestion Win

### The baseline problem

Initial ingestion of a single 6KB NTSB incident report took **~45 seconds**. For a 20-document corpus, that's 15 minutes. For 200 docs? 2.5 hours. Benchmarking at scale was impractical.

### Where the time went

Profiling revealed ingestion time was almost entirely LLM extraction:
- Read file: <1ms
- Chunking: ~10ms
- Batch embedding (fastembed): ~500ms
- **LLM extraction: 30-50s** (sequential, 1 chunk at a time)
- Entity resolution + inserts: ~500ms

### The fix

Three optimizations, biggest win first:

**1. Parallel LLM extraction** (~90% of speedup)
```python
# Before: sequential loop
for chunk in chunks:
    result = await llm.extract(chunk)

# After: asyncio.gather with semaphore
sem = asyncio.Semaphore(16)  # 16 concurrent LLM calls
tasks = [_extract_one(chunk, sem) for chunk in chunks]
results = await asyncio.gather(*tasks)
```

**2. Batched entity embeddings**
```python
# Before: one call per entity
for entity in entities:
    emb = await embedder.embed([entity.name])  # N calls

# After: single batch call
all_texts = [f"{e.name} {e.description}" for e in entities]
embs = await embedder.embed(all_texts)  # 1 call
```

**3. Parallel document processing**
```python
doc_sem = asyncio.Semaphore(4)  # 4 docs in parallel
await asyncio.gather(*[process_file(f) for f in files])
```

### Results

| Workload | Sequential (local) | Parallel (vLLM) | Parallel (OpenAI gpt-4o-mini) |
|----------|----------|----------|----------|
| 1 NTSB doc | ~45s | 24s | **18s** |
| 20 NTSB docs | ~900s (15 min) | 213s (3.5 min) | **40s** |
| Speedup vs baseline | 1x | 4.3x | **22.5x** |

**Why vLLM hit a ceiling at 4.3x:** local single-GPU vLLM saturates at ~16 concurrent requests. Our parallelism ran ahead of LLM throughput.

**Why OpenAI hit 22.5x:** OpenAI's infrastructure handles 32+ parallel requests easily, each in 0.5-1s. We can push `extract_concurrency=32` and saturate it without hitting backpressure.

**Per-document cost with OpenAI gpt-4o-mini:** ~$0.005 per document. Ingesting the full benchmark suite (462 docs) costs under **$2.50**.

### Lesson: test with real data early

We only discovered the ingestion bottleneck when trying to benchmark with real corpora. Mock tests with fake LLMs hide this problem entirely. The lesson: **if you care about real-world performance, test with real data as early as possible.**

---

## Finding 3: litellm was Supply-Chain Attacked

**March 24, 2026:** TeamPCP published malicious litellm versions 1.82.7 and 1.82.8 to PyPI by stealing credentials through a compromised Trivy CI action. The packages were live for ~40 minutes before quarantine. The malware: credential harvesting, Kubernetes lateral movement, persistent backdoor.

### How we avoided it

Before committing to litellm as our LLM client, we evaluated alternatives. We switched to **httpx** with the OpenAI-compatible API format:

```python
class HttpxLLMProvider:
    async def complete(self, messages):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json={"model": self.model, "messages": messages,
                      "response_format": {"type": "json_object"}},
            )
            return resp.json()["choices"][0]["message"]["content"]
```

This works with:
- Ollama (default for local)
- OpenAI API
- vLLM (our benchmark LLM)
- LM Studio, LocalAI, Together AI
- Any OpenAI-compatible endpoint

**Cost:** ~50 lines of code. **Saved:** one large dependency + one known supply-chain attack vector.

### Lesson: minimize dependencies, especially for LLM plumbing

Every dependency is a potential attack vector. For a "simple, small" library, prefer direct HTTP calls to framework abstractions when the underlying API is standardized.

---

## Finding 4: Apache AGE is the Wrong Abstraction

Before writing a single line of code, we evaluated Apache AGE (PostgreSQL's graph extension). **We rejected it for four reasons:**

### 1. Cloud compatibility kills it
AGE requires `shared_preload_libraries` (needs PostgreSQL restart). Only Azure Database for PostgreSQL supports it among managed providers. No AWS RDS. No Supabase. No Neon. No GCP Cloud SQL.

For a library targeting developers on "the PostgreSQL you already run," this is a dealbreaker.

### 2. Can't combine with pgvector in a single query
AGE Cypher and pgvector live in different worlds. The GraphRAG killer operation — "seed entities from vector similarity, then expand via graph, then rank chunks" — requires **two round-trips** with AGE.

With recursive CTEs, it's **one query**:
```sql
WITH RECURSIVE seeds AS (
    SELECT id FROM entities
    ORDER BY embedding <=> $1::vector
    LIMIT 5
),
neighborhood AS (
    SELECT id, 0 AS depth, ARRAY[id] AS path FROM seeds
    UNION ALL
    SELECT e2.id, n.depth + 1, n.path || e2.id
    FROM neighborhood n
    JOIN relationships r ON (r.src_id = n.id OR r.dst_id = n.id)
    JOIN entities e2 ON e2.id = CASE ... END
    WHERE n.depth < 2 AND NOT (e2.id = ANY(n.path))
)
SELECT c.content, 1 - (c.embedding <=> $1::vector) AS score
FROM chunks c
JOIN entity_chunks ec ON ec.chunk_id = c.id
WHERE ec.entity_id IN (SELECT id FROM neighborhood)
ORDER BY score DESC LIMIT 10;
```

One query. One round-trip. One transaction.

### 3. Slower for GraphRAG patterns
Benchmarks show recursive CTEs are **2-40x faster** than AGE Cypher for 1-3 hop traversals — the typical GraphRAG pattern. AGE defaults to sequential scans and has produced catastrophic query plans (LightRAG issue #2255: 49 **billion** estimated rows for 681K actual rows, causing a 17-hour migration).

### 4. Proven alternative exists
The `postgres-graph-rag` library already implements full GraphRAG using only recursive CTEs + pgvector. No AGE required.

### Our architecture

```
adjacency tables  →  WITH RECURSIVE CTEs  →  pgvector HNSW
    (entities)       (graph traversal)      (vector search)
```

All standard SQL. Works on every managed PG provider. No extensions beyond pgvector (near-universal support).

---

## Finding 5: Edge Cases Reveal Real Bugs

Our test strategy required testing "like a real user" — not just happy paths. We ran 12 edge cases against the implementation. **4 of them found real bugs:**

| Edge Case | What Broke | Fix |
|-----------|-----------|-----|
| EC-002: 10,000-char query | `to_tsquery` parser overflow | Truncate to 20 significant words |
| EC-005: Invalid query mode | Silently accepted any string | Validate mode against Literal type |
| EC-006: Binary file ingest | UnicodeDecodeError crash | Try/except UTF-8, skip with warning |
| EC-010: Concurrent same-file ingest | Unique constraint violation | INSERT ON CONFLICT DO UPDATE |

Each of these is something a real user would hit. None were caught by our initial 55-test happy-path suite.

### The meta-lesson

**Happy-path tests give false confidence.** We had 55 passing tests before running edge cases. The edge case tests found bugs in production-critical paths (concurrency, input validation, encoding). For any library claiming production-readiness, edge case testing isn't optional — it's where the real value is.

---

## Finding 6: BM25 AND vs OR Semantics Matters

PostgreSQL's `plainto_tsquery('english', 'payment outage')` produces `payment & outage` — it requires **both** words to match. This is the default for `plainto_tsquery`.

**We discovered this when our "circuit breaker Stripe" query returned zero results** — no single chunk contained both "circuit breaker" and "Stripe" (they were in different documents).

### The fix

We built an OR-based tsquery converter:

```python
def _to_or_tsquery(text: str) -> str:
    words = re.findall(r"\w+", text.lower())
    words = [w for w in words if len(w) > 2][:20]  # cap at 20
    return " | ".join(words) if words else "empty"
```

Now `"payment outage"` becomes `"payment | outage"` — matches chunks containing either word. The ranking still prefers chunks with both (via `ts_rank`), but recall dramatically improves.

### Why the cap at 20 words?

Edge case EC-002 discovered that very long queries overflow `to_tsquery`'s parser. Truncating to 20 significant words prevents the overflow while preserving query intent.

---

## Benchmark Data Sources

We tested against 4 real-world corpora:

| Corpus | Source | Docs | Gold QA | Notes |
|--------|--------|------|---------|-------|
| **PostgreSQL Docs** | Official PG 16 + blogs | 31 | 10 (hand) | Technical reference |
| **NTSB Aviation** | [KG-RAG Eval](https://github.com/docugami/KG-RAG-datasets) | 20 | Draft | Incident reports |
| **SEC 10-Q** | [KG-RAG Eval](https://github.com/docugami/KG-RAG-datasets) | 20 | **195** | Real financial filings |
| **HotpotQA** | [hotpotqa.github.io](https://hotpotqa.github.io/) | 4,937 | **500** | Wikipedia multi-hop |
| **SCOTUS** | [Oyez API](https://api.oyez.org/) | 391 | — | Supreme Court cases |

**Total:** ~5,400 documents, ~700 gold QA pairs, ~55MB of text.

---

## Performance Numbers

**Retrieval latency** (all query modes):

| Corpus | Entities | naive | local | global | hybrid |
|--------|----------|-------|-------|--------|--------|
| PG Docs | 1,140 | 16ms | 27ms | 20ms | 35ms |
| NTSB | 314 | 13ms | 25ms | — | 29ms |
| SEC (partial) | 900+ | — | — | — | — |

All modes consistently under **50ms p95**, well within our 100ms target.

**Ingestion throughput** (parallel, doc_concurrency=4, extract_concurrency=16):
- NTSB: 20 docs / 213s = ~9.4 docs/min
- SEC: larger docs (~150KB each) → ~25-30 min for 20 docs
- With a faster LLM (GPT-4o-mini, local Llama 3.2 on GPU): estimated 2-5x faster

---

## What We Got Wrong Initially

Things we believed that turned out to be false or nuanced:

1. **"GraphRAG wins on multi-hop questions"** — Partially true. It wins on specifically cross-document questions with explicit relationships. On questions where the answer spans multiple chunks of the same document, vector+BM25 is sufficient.

2. **"Our small test corpus would show clear graph wins"** — False. With 3-4 docs and top_k=10, vector search retrieves basically everything, so there's nothing for graph expansion to add.

3. **"Sequential ingestion is fine for a prototype"** — False. It made real benchmarking impossible. Parallelization was day-one necessary.

4. **"LLM caching would solve the slow ingestion"** — Partially. It helps on re-runs, but first-run performance is what users experience.

5. **"The postgres-graph-rag approach is a good model"** — Yes for the recursive CTE pattern, no for the missing features (no chunk storage, no entity resolution, no dedup).

---

## What We Got Right

1. **Rejecting Apache AGE early** — Saved us from cloud compatibility hell and the LightRAG-style performance disasters.

2. **Prioritizing single-query hybrid retrieval** — The CTE + pgvector + BM25 in one SQL query is genuinely differentiated and architecturally elegant.

3. **Local embeddings by default** — fastembed works out of the box without API keys, makes `pgrg demo` instantly runnable.

4. **Testing with real LLM from day one** — Found the silent cache poisoning bug that would have blocked all real-world use.

5. **Being honest about the accuracy findings** — Marketing "graph wins on everything!" would have been easy. Saying "graph wins on specific patterns, naive is better elsewhere" is correct and builds trust.

---

## Takeaways for Other Builders

1. **Test with real data as early as possible.** Mock tests hide the bottlenecks that matter (LLM throughput, real query patterns, edge cases).

2. **Question framework abstractions.** litellm was tempting. httpx + OpenAI-compatible format is simpler, smaller, and we dodged a supply-chain attack.

3. **Parallelize the slow thing, not the fast thing.** 90% of our ingestion speedup came from parallelizing LLM extraction. DB operations were never the bottleneck.

4. **Edge case testing is mandatory.** 55 happy-path tests missed 4 real bugs. The cost of writing edge case tests is trivial compared to the cost of a bug in production.

5. **Be honest about where your approach fails.** The GraphRAG marketing overstates the benefits. Users who understand when to use each mode will build better systems than users who blindly apply graph RAG to every problem.

6. **Document your "wrong" beliefs.** Future you (and your users) will learn more from "we thought X, but it turned out Y" than from polished narratives of success.
