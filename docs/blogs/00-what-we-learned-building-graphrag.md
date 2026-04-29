# What We Learned Building a PostgreSQL-Native GraphRAG

*Or: why the "graph wins on everything" narrative is wrong, and what actually works.*

> **Note:** This is the original retrospective from the project's early benchmarking, dated 2026-04. The headline lessons here all still hold, but the project has evolved since:
>
> - **+18.9% accuracy lift** measured on a real 909-doc developer codebase ([`benchmarks/pg-agents-results.md`](../../benchmarks/pg-agents-results.md)).
> - **Apache AGE bake-off completed**, with the [methodology / fairness disclosure](../../research/apache-age-evaluation.md) documenting exactly what AGE was and wasn't tuned with. AGE retrieval ran 42–111× slower in fair-defaults mode.
> - **Tier 1 evolving-knowledge** features shipped (`retracted`, `as_of`, `version_filter`) — see [`01-intro-classic-vs-evolving.md`](01-intro-classic-vs-evolving.md), [`02-path-a-versioned-python-docs.md`](02-path-a-versioned-python-docs.md), and [`03-path-b-medical-retractions.md`](03-path-b-medical-retractions.md) for worked examples.
>
> The numbers below are from the early 2026-04 benchmarks (PG docs, NTSB, SEC 10-Q, SCOTUS). They reflect what graph mode does and doesn't do on classic technical-doc corpora, which is the lens this post is written through. For current-state measurements on the larger pg-agents corpus and the new evolving-knowledge workloads, follow the links above.

---

GraphRAG is having a moment. Microsoft open-sourced theirs in 2024, LightRAG hit 33K stars with an EMNLP 2025 paper, Zep ships production-ready temporal knowledge graphs. Every vendor promises multi-hop reasoning, cross-document insight, and dramatic accuracy improvements over "naive" vector RAG.

We built pg-raggraph — a PostgreSQL-native GraphRAG library — and benchmarked it against real-world corpora (PostgreSQL docs, SEC 10-Q filings, NTSB aviation reports, HotpotQA Wikipedia, 391 Supreme Court cases). Here's what surprised us.

## The Marketing vs Reality Gap

We expected graph modes to dominate on multi-hop questions. They didn't — at least not on the corpora we tested.

> **All numbers in this section** are from the **2026-04-12 benchmark run** against the original PG-docs and NTSB corpora (`benchmarks/postgres-docs/` and `benchmarks/kg-rag-eval/ntsb/`). They reflect what graph mode did and didn't do on those specific runs. They have **not been re-verified** against `main` since the post-audit hardening + Tier 1 merge — a re-run would land in a separate session. The directional finding ("graph doesn't dominate on technical-doc corpora") was reproduced later on the 909-doc pg-agents corpus, where graph boost adds **+18.9%** at the same latency — see [`pg-agents-results.md`](../../benchmarks/pg-agents-results.md). Treat the percentages below as period data; treat the lesson as still load-bearing.

On **PostgreSQL documentation** (31 docs, 1,140 entities; measured 2026-04-12), plain vector+BM25 hit **80% accuracy** on technical questions. Our hybrid graph mode? **72%**. Graph lost by 8 percentage points on the very technical-doc queries we expected it to excel at.

On **NTSB aviation incident reports** (20 docs, 314 entities; measured 2026-04-12), hybrid scored 79% vs naive's 75% — a modest 4-point improvement on cross-incident questions. Graph won exactly **one of five test questions**: "How does pilot experience affect incident outcomes?" — which required correlating pilot certifications across multiple reports.

This matches the academic literature more honestly than the marketing does:
- **GraphRAG-Bench (ICLR 2026)**: Graph advantage only on relational QA requiring multi-hop reasoning
- **Unbiased Evaluation (arXiv 2506.06331)**: "NaiveRAG performs nearly as well as graph methods on many benchmarks"
- **fast-graphrag**: PageRank beats full GraphRAG on many tasks

**The honest verdict:** GraphRAG helps on a narrow class of questions — ones that genuinely require connecting information across multiple documents via explicit entity relationships. On direct factual questions, vector similarity is often sufficient and always faster.

This matters because the default recommendation from most GraphRAG libraries is "use graph mode for everything." That's wrong. The right answer is: **start with naive, upgrade to hybrid only when you see cross-document questions failing.**

## Why We Rejected Apache AGE

Before writing a single line of code, we evaluated Apache AGE — PostgreSQL's graph extension that adds Cypher query support. It's the obvious choice for "PG-native GraphRAG," right?

We rejected it. Four reasons:

**1. Cloud compatibility kills it.** AGE requires `shared_preload_libraries`, which needs a PostgreSQL restart. Only Azure Database for PostgreSQL supports it among managed providers. No AWS RDS. No Supabase. No Neon. No GCP Cloud SQL. For a library targeting "the PostgreSQL you already run," this is a dealbreaker.

**2. Can't combine with pgvector in a single query.** The killer GraphRAG operation — "seed entities from vector similarity, then expand via graph, then rank chunks" — requires two separate query steps with AGE. With recursive CTEs, it's one query, one round-trip, one transaction:

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
    JOIN relationships r ON r.src_id = n.id OR r.dst_id = n.id
    JOIN entities e2 ON e2.id = CASE ... END
    WHERE n.depth < 2 AND NOT (e2.id = ANY(n.path))
)
SELECT c.content, 1 - (c.embedding <=> $1::vector) AS score
FROM chunks c
JOIN entity_chunks ec ON ec.chunk_id = c.id
WHERE ec.entity_id IN (SELECT id FROM neighborhood)
ORDER BY score DESC LIMIT 10;
```

**3. AGE is slower for GraphRAG patterns.** Benchmarks show recursive CTEs are 2-40x faster than AGE Cypher for 1-3 hop traversals. AGE's query planner defaults to sequential scans and has produced catastrophic plans — LightRAG issue #2255 documents a 17-hour migration disaster caused by a query that estimated 49 **billion** rows for a 681K-row join.

**4. Proven alternative exists.** The postgres-graph-rag library already implements full GraphRAG using only recursive CTEs + pgvector. No extensions beyond what every managed PostgreSQL provider already offers.

Our architecture: adjacency tables + recursive CTEs + pgvector. All standard SQL. Works on RDS, Supabase, Neon, Cloud SQL, Azure — any PostgreSQL 16+ with pgvector. One extension. Near-universal support.

## Why We Dropped litellm

litellm is a popular unified LLM client. We were going to use it. One week before we committed to it, **TeamPCP published malicious versions 1.82.7 and 1.82.8 to PyPI** via a compromised Trivy CI action. The packages were live for ~40 minutes before quarantine. Payload: credential harvesting, Kubernetes lateral movement, persistent backdoor for remote code execution.

We switched to httpx with the OpenAI-compatible API format directly:

```python
async with httpx.AsyncClient() as client:
    resp = await client.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        },
    )
    return resp.json()["choices"][0]["message"]["content"]
```

50 lines of code. Works with Ollama, OpenAI, vLLM, LM Studio, LocalAI, Together, and any OpenAI-compatible endpoint. One fewer dependency. Zero supply-chain risk for LLM calls.

**Lesson:** every dependency is an attack vector. For a library that values "small" as a core principle, prefer direct HTTP calls over framework abstractions when the underlying API is standardized.

## Ingestion Speed Was the Real Problem

Our first ingestion of an NTSB incident report — a 6 KB document — took **45 seconds** (sequential single-doc baseline measured 2026-04-12; pre-`asyncio.gather` parallel-extract refactor). For a 20-document corpus, that's 15 minutes. For 200 docs? 2.5 hours. Benchmarking was impractical.

We profiled and found the culprit: LLM extraction was running one chunk at a time, sequentially. Each LLM call took 3-5 seconds, and with 10 chunks per document, we were waiting 30-50 seconds per file.

Three optimizations fixed this, biggest first:

**1. Parallel LLM extraction** (~90% of the speedup)
```python
sem = asyncio.Semaphore(32)  # Up to 32 concurrent LLM calls
tasks = [_extract_one(chunk, sem) for chunk in chunks]
results = await asyncio.gather(*tasks)
```

**2. Batched entity embeddings**  
Before: one embedding call per entity (100 entities = 100 calls). After: one batch call for all entities (100 entities = 1 call).

**3. Parallel document processing**  
Process up to 8 documents simultaneously with `asyncio.gather`.

### Results

| Workload | Sequential | Parallel + vLLM | Parallel + OpenAI |
|----------|-----------|-----------------|-------------------|
| 1 NTSB doc | ~45s | 24s | **18s** |
| 20 NTSB docs | ~900s | 213s | **40s** |
| Speedup | baseline | 4.3x | **22.5x** |

With OpenAI GPT-4o-mini and full parallelism (32 concurrent extraction calls), we're ingesting at **2 seconds per document**. That's fast enough to re-ingest a 500-doc corpus during a coffee break.

**Lesson:** test with real data early. Mock tests hide the bottlenecks that matter. We only found the ingestion problem when trying to benchmark real corpora — and it was immediately obvious that benchmarking was impossible without parallelism.

## BM25 Does AND by Default — Fix It

PostgreSQL's `plainto_tsquery('english', 'payment outage')` produces `payment & outage`. It requires **both** words to match. This is the default.

We discovered this bug when our test query "circuit breaker Stripe" returned zero results. No single chunk contained both "circuit breaker" and "Stripe" — they were in different documents.

The fix is a trivial query rewriter:

```python
def _to_or_tsquery(text: str) -> str:
    words = re.findall(r"\w+", text.lower())
    words = [w for w in words if len(w) > 2][:20]  # cap at 20 to prevent overflow
    return " | ".join(words) if words else "empty"
```

Now `"payment outage"` becomes `"payment | outage"` — matches chunks with either word. The 20-word cap prevents parser overflow on very long queries (we found this via an edge case test with a 10K-character query).

**Lesson:** defaults matter. PostgreSQL's full-text search is powerful but AND-by-default. For RAG, OR is usually what you want — better recall, and `ts_rank` still prioritizes chunks with more matching terms.

## Edge Cases Found Real Bugs

Our test strategy required "test like a real user." We wrote 12 edge case tests. **Four of them found real bugs:**

| Edge Case | Bug | Fix |
|-----------|-----|-----|
| 10,000-char query | `to_tsquery` parser overflow | Truncate to 20 significant words |
| Invalid query mode | Silently accepted any string | Validate mode against allowed set |
| Binary file ingest | UnicodeDecodeError crash | Try/except UTF-8, skip with warning |
| Concurrent same-file ingest | Unique constraint violation | INSERT ON CONFLICT DO UPDATE |

Our happy-path suite had 55 passing tests before edge case testing. None of them caught these bugs. Every one was something a real user would eventually hit.

**Lesson:** happy-path tests give false confidence. Edge case testing isn't optional for any library claiming production-readiness — it's where the real value is. Budget time for breaking your own code.

## The Findings in Table Form

| What | We Expected | What Happened |
|------|------------|---------------|
| GraphRAG accuracy | "Dramatically better than vector" | +3-5 points on specific multi-hop questions only |
| Apache AGE | "PostgreSQL graph extension = obvious choice" | Slower than CTEs, cloud-incompatible, architecturally wrong |
| litellm | "Standard LLM abstraction layer" | Supply-chain attack vector, we dodged the bullet |
| Ingestion speed | "Sequential is fine for a prototype" | Impractical for benchmarking, required day-one parallelism |
| BM25 defaults | "PostgreSQL text search just works" | AND semantics return zero results; needed OR rewriter |
| Happy-path tests | "55 passing tests = production ready" | Edge case tests found 4 real bugs |

## What We'd Tell Other Builders

1. **Be honest about where your approach fails.** The GraphRAG marketing overstates the benefits. Users who understand when to use each mode will build better systems than users who blindly apply graph RAG to every problem.

2. **Test with real data as early as possible.** Mock tests hide bottlenecks. Real LLMs on real corpora reveal the actual problems.

3. **Parallelize the slow thing, not the fast thing.** 90% of our ingestion speedup came from parallelizing LLM extraction. DB operations were never the bottleneck.

4. **Question framework abstractions.** The simpler solution (httpx + OpenAI-compatible format) dodged a supply-chain attack that could have compromised every user of the library.

5. **Measure retrieval latency AND ingestion speed.** Fast queries on a corpus that takes 3 hours to ingest is a bad trade. Users care about the full end-to-end experience.

6. **Default to honesty.** We're telling you graph RAG didn't win on our technical docs benchmark. That's the truth. Marketing-speak would have said "graph RAG improves cross-document reasoning by 8%." Both are technically accurate. Only one respects the reader.

---

## The Code

pg-raggraph is MIT-licensed, ~4K LOC core (grew with the Tier 1 evolution layer), 9 core dependencies, works on every managed PostgreSQL provider. If you're already running PostgreSQL and want to add GraphRAG to an app, it's the simplest path:

```bash
# Until the first stable PyPI release, install from source:
git clone https://github.com/yonk-labs/pg_raggraph
cd pg_raggraph
uv sync
docker compose up -d postgres

uv run pgrg ingest ./your-docs/
uv run pgrg query "your question"
```

Or from Python:
```python
from pg_raggraph import GraphRAG

async with GraphRAG("postgresql://localhost:5434/pg_raggraph") as rag:
    await rag.ingest(["./docs/"])
    # `smart` (the default) routes between naive / boost / expand based on
    # confidence. Pin to `mode="hybrid"` only when you know your corpus
    # benefits from it.
    result = await rag.query("How does auth work?")
    for chunk in result.chunks:
        print(chunk.content)
```

No Neo4j. No Pinecone. No Apache AGE. Just PostgreSQL, pgvector, and async Python.
