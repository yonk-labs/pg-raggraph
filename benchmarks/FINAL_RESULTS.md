# pg-raggraph: Cross-Corpus Benchmark Results

## Re-verification — 2026-04-29

Re-ran PG-docs and NTSB corpora against current `main` (post Tier-1 merge + audit hardening) using **three methodologies side-by-side**:

1. **Keyword-recall** — `benchmarks/run_benchmark.py`. Deterministic, $0 cost. Measures `% of expected keywords found in retrieved chunks`. Same proxy the original 2026-04-12 blog 00 numbers used. Blind to synonyms / right-keyword-wrong-context.
2. **Qwen judge (local vLLM)** — `benchmarks/run_llm_judge.py --judge local`. Same Intel/Qwen3-Coder-Next-int4-AutoRound model the AGE bake-off uses. $0 cost. Grades `rag.ask()` answers 0–3 against question + retrieved chunks.
3. **OpenAI judge** — `benchmarks/run_llm_judge.py --judge openai`. gpt-4o-mini. ~$0.50 for 60 calls. Independent grader for cross-judge robustness check.

The answer generator (the LLM `rag.ask()` calls) is **always** the local vLLM. We're comparing how the same answers get scored by different judges, not benchmarking different answer-generators.

### PostgreSQL docs — 31 docs, 248 chunks, 1,332 entities, 1,793 rels (re-ingested 2026-04-29 in 1,252 s on `balanced` profile)

| Mode | Keyword-recall | Qwen judge | OpenAI judge | Δ judge |
|---|:-:|:-:|:-:|:-:|
| naive | 82.0% | 73.3% | 86.7% | **+13.4** |
| `naive_boost` ⭐ | n/a* | 80.0% | 83.3% | +3.3 |
| smart | n/a* | 76.7% | 86.7% | +10.0 |
| local | 82.0% | 76.7% | 86.7% | +10.0 |
| global | 78.0% | 73.3% | 86.7% | +13.4 |
| hybrid | 82.0% | 73.3% | 86.7% | +13.4 |

*`run_benchmark.py` predates `naive_boost` and `smart` modes.

OpenAI judge "fully-correct" / "wrong-or-empty" per mode (out of 10 questions): naive 8/1, naive_boost 8/1, smart 8/1, local 8/1, global 8/1, hybrid 8/1.

### NTSB aviation reports — 20 docs, 82 chunks, 344 entities, 438 rels (re-ingested 2026-04-29 in 309 s, 15.5 s/doc — **3× faster** than the 45 s/doc 2026-04-12 sequential baseline)

| Mode | Qwen judge | OpenAI judge | Δ judge |
|---|:-:|:-:|:-:|
| naive | 86.7% | **100.0%** | +13.3 |
| `naive_boost` | 93.3% | 96.7% | +3.4 |
| smart | 86.7% | 90.0% | +3.3 |
| local | 93.3% | **100.0%** | +6.7 |
| global | 80.0% | **100.0%** | +20.0 |
| hybrid | 86.7% | **100.0%** | +13.3 |

OpenAI judge "fully-correct" / "wrong-or-empty" (n=10): naive 10/0, naive_boost 9/0, smart 9/1, local 10/0, global 10/0, hybrid 10/0.

### Reading the 2026-04-29 numbers

**Judge choice matters more than retrieval mode does on these corpora.** Same 60 PG-docs + 60 NTSB answers, scored 0–3 by two different judges, produce 3.3 to 20.0-pp swings between the Qwen and OpenAI columns. Within a single judge column, mode-to-mode variance is much smaller (0–6.6 pp on PG-docs under either judge; 6.6–13.3 pp on NTSB under Qwen). Methodology disclosure for any retrieval claim should always include which judge graded it.

**PG-docs:** under both judges, modes converge to the same accuracy band — the original blog 00 claim "hybrid lost by 8 points" is **no longer reproducible**. Qwen judge crowns `naive_boost` (80%); OpenAI judge says all modes tie at 86.7% except `naive_boost` which dips slightly. Both views support the same directional finding — *graph doesn't dominate on technical-doc corpora* — but neither replicates the original 8-pp negative gap. The keyword-recall column is stable across the cluster (82% for naive/local/hybrid).

**NTSB:** Qwen judge cleanly shows `naive_boost` and `local` ahead of naive (93.3% vs 86.7%) — the cross-incident-question signal graph mode is supposed to deliver. **OpenAI judge basically saturates** at 100% for naive/local/global/hybrid — the gap collapses because OpenAI grades these answers as fully-correct regardless of mode. That's a separate finding: gpt-4o-mini may be too generous on multi-incident questions where any plausible synthesis gets credit. The robustness check raises the bar for "graph wins on NTSB" — the win is real under Qwen, but vanishes under a more lenient grader.

**Ingest performance:** `asyncio.gather` parallel-extract delivered the **3× speedup** the original blog claimed it would. NTSB 20 docs in 309 s = 15.5 s/doc vs the 45 s/doc sequential baseline.

### How do these numbers compare to Apache AGE?

**Honest answer: PG-docs and NTSB were never directly measured against Apache AGE.** Our pgrg-vs-AGE head-to-head ran on SCOTUS only (`benchmarks/age-bakeoff/`). Adapting the bake-off harness to PG-docs / NTSB is its own effort (~30–60 min wall time, ~$1–2 LLM cost). What we have today, applied to **SCOTUS** with the same `gpt-5-mini` majority-of-3 judge methodology:

| Mode | pgrg accuracy (n=30) | AGE accuracy (n=30) | pgrg p50 latency | AGE p50 latency | pgrg speedup |
|---|:-:|:-:|:-:|:-:|:-:|
| naive | 18/30 | 18/30 | 35 ms | 3,873 ms | **111×** |
| `naive_boost` | 17/30 | 18/30 | 40 ms | 3,895 ms | **98×** |
| smart | 17/30 | 18/30 | 32 ms | 3,226 ms | **101×** |
| local | 18/30 | 17/30 | 65 ms | 3,079 ms | **47×** |
| global | 18/30 | 18/30 | 43 ms | 3,906 ms | **91×** |
| hybrid | 18/30 | 17/30 | 73 ms | 3,088 ms | **42×** |

Source: [`benchmarks/age-bakeoff/results/REPORT-VERDICT.md`](age-bakeoff/results/REPORT-VERDICT.md). Same extraction JSON, same chunker, same embedder, same LLM judge — fair-defaults vs fair-defaults disclosed in [`research/apache-age-evaluation.md`](../research/apache-age-evaluation.md).

**What this means for PG-docs and NTSB:** if you transposed the architecture (recursive CTEs vs Cypher subqueries calling pgvector via two round-trips), the latency story is consistent — AGE would be 40–110× slower on retrieval, regardless of the corpus, because the architectural blocker is *Cypher and pgvector can't combine in one query*. The accuracy story is harder to predict from SCOTUS alone — both engines tied at 17–18/30 there because they share the same upstream extraction; the same parity probably holds on PG-docs / NTSB but we haven't confirmed.

**If you want a direct measurement on these corpora**, the bake-off harness supports adding new corpora — see `benchmarks/age-bakeoff/README.md`. Not blocked, just a separate run.

### Methodology recommendation

For publishable accuracy claims:
- **Always show keyword-recall + at least one LLM-judge column** so readers see the spread.
- **Prefer cross-judge agreement over single-judge maxima.** `naive_boost` clears 80%+ on PG-docs under both judges; that's a more robust win than its 93.3% on NTSB-under-Qwen which softens to 96.7% under OpenAI.
- **Use multiple judges with different strictness profiles** when reporting a head-to-head between modes. Single-judge can be biased low (Qwen) or high (gpt-4o-mini); the bake-off's `gpt-5-mini` majority-of-3 is the gold standard but expensive.

The earlier (pre-2026-04-29) sections below are kept as history for prior cross-corpus runs; treat the 2026-04-29 numbers as canonical for current `main`.

---

## TL;DR (updated with smart mode)

Smart mode delivers **hybrid's accuracy at 1.8-2.9x better latency** across 4 real-world corpora (462 docs, 8,342 entities, 17,637 relationships). The confidence-triggered routing ships fast on easy questions (naive path) and applies cheap graph boost or full expansion only when needed. **Smart mode is the new default — use it unless you have a specific reason not to.**

## Smart Mode Results

| Corpus | Smart Accuracy | Smart Latency | Hybrid Latency | Speedup |
|--------|---------------|---------------|----------------|---------|
| PostgreSQL Docs | 87.5% | 45ms | 80ms | **1.8x** |
| NTSB Aviation | 73.7% | 48ms | 44ms | baseline |
| SCOTUS (6 years) | 88.9% | 66ms | 176ms | **2.7x** |
| SEC 10-Q Multi-Doc | 47.1% | 63ms | 182ms | **2.9x** |

Smart mode matches hybrid's accuracy on 3 of 4 corpora while being significantly faster. On NTSB (the smallest cross-document corpus), local mode (78.9%) beats smart mode (73.7%) — smart's confidence routing could be tuned for small corpora.

## All Modes, All Corpora

```
Corpus                    N     naive     boost     smart     local    global    hybrid
  PostgreSQL Docs          10    87.5%    87.5%    87.5%    87.5%    75.0%    87.5%
  NTSB Aviation             5    73.7%    73.7%    73.7%    78.9%    73.7%    78.9%
  SCOTUS (6 years)          8    88.9%    88.9%    88.9%    88.9%    81.5%    88.9%
  SEC 10-Q (Multi-Doc)     20    47.1%    47.1%    47.1%    47.7%    48.4%    47.7%

  Latency (avg ms):
  PostgreSQL Docs             41        39        45        52        59        80
  NTSB Aviation               36        37        48        37        35        44
  SCOTUS (6 years)            58        92        66       138        70       176
  SEC 10-Q (Multi-Doc)        53        54        63       134        81       182
```

## Original TL;DR
Across 461 real documents, 8,322 entities, 17,637 relationships, and 4 different corpora (technical docs, aviation reports, legal cases, financial filings), **naive vector+BM25 and graph modes are within 5 percentage points of each other**. Graph modes win a small but real edge on cross-incident NTSB questions (+5.2%) and on SEC multi-doc questions (+1.3% for global mode). On self-contained corpora (PostgreSQL docs, SCOTUS), naive is as good or better. **This is the most honest answer we can give: GraphRAG helps in specific scenarios, but the advantage is narrower than marketing suggests.**

---

## Test Environment

- **Database:** PostgreSQL 16 with pgvector + pg_trgm (Docker, port 5434)
- **Embeddings:** BAAI/bge-small-en-v1.5 (384 dim, local fastembed)
- **LLM:** OpenAI gpt-4o-mini (for extraction)
- **Profile:** aggressive (doc_concurrency=4, extract_concurrency=16)
- **Retrieval top_k:** 10
- **Metric:** keyword recall (% of expected keywords in retrieved chunks)

---

## Corpus Summary

| Corpus | Docs | Chunks | Entities | Relationships | Ingest Time |
|--------|------|--------|----------|---------------|-------------|
| NTSB Aviation | 20 | 82 | 320 | 349 | 81s |
| SEC 10-Q | 20 | 1,872 | 2,787 | 8,459 | 451s |
| PostgreSQL Docs | 31 | 2,120 | 929 | 1,096 | 161s |
| SCOTUS Cases | 390 | 6,137 | 4,286 | 7,733 | 1,532s |
| **TOTAL** | **461** | **10,211** | **8,322** | **17,637** | **37 min** |

**Ingestion cost:** ~$1.50 in OpenAI API fees (gpt-4o-mini at $0.15/$0.60 per 1M tokens)

---

## Accuracy Results (Higher = Better)

```
Corpus                    N     naive     local    global    hybrid
------------------------------------------------------------------------
PostgreSQL Docs          10    87.5%    85.0%    80.0%    85.0%
NTSB Aviation             5    73.7%    78.9%    63.2%    78.9%   ← graph wins
SCOTUS (6 years)          8    88.9%    85.2%    81.5%    85.2%
SEC 10-Q (Multi-Doc)     20    47.1%    47.7%    48.4%    47.1%   ← graph wins
```

### Where graph wins
- **NTSB Aviation**: hybrid/local 78.9% vs naive 73.7% (**+5.2 pts**)
- **SEC 10-Q Multi-Doc**: global 48.4% vs naive 47.1% (**+1.3 pts**)

### Where naive wins
- **PostgreSQL Docs**: naive 87.5% vs hybrid 85.0% (**-2.5 pts for graph**)
- **SCOTUS Cases**: naive 88.9% vs hybrid 85.2% (**-3.7 pts for graph**)

### Why the differences

- **Technical documentation (PG, SCOTUS)** has high keyword density and self-contained answers. BM25 nails these with exact term matching. Graph expansion pulls in tangentially related entities that dilute the top rankings.
- **Cross-document reports (NTSB)** benefit from graph traversal — questions about "pilot experience across incidents" require connecting pilot entities across different reports. Graph wins here.
- **SEC 10-Q** is interesting: only 47% accuracy for ALL modes because the questions come from gold QnA pairs that ask for specific dollar amounts in tables. None of the modes reliably extract numeric answers from deeply nested financial tables — this is more a chunking/extraction issue than a retrieval issue.

---

## Latency Results (Lower = Better)

```
Corpus                     naive     local    global    hybrid
------------------------------------------------------------------------
PostgreSQL Docs             26ms      33ms      39ms      53ms
NTSB Aviation               24ms      26ms      21ms      27ms
SCOTUS (6 years)            37ms     106ms      50ms     132ms
SEC 10-Q (Multi-Doc)        38ms      86ms      52ms     119ms
```

- **All modes under 200ms** (our target)
- **Naive is consistently fastest** — no graph traversal overhead
- **Hybrid is ~3x slower** than naive (runs both local + global, merges)
- **Latency scales with entity count** — SCOTUS (4,286 entities) + SEC (2,787 entities) are slower than PG (929) + NTSB (320)

---

## Key Findings

### 1. The graph advantage is narrow (but real)
- On self-contained technical docs: naive wins by 2-4 percentage points
- On cross-document reports: graph wins by 1-5 percentage points
- **Average improvement from graph: +0.1 percentage points** (basically a wash)

### 2. Graph modes are more expensive
- Naive: 24-38ms average
- Hybrid: 27-132ms average (**2-4x slower**)
- On large corpora (SCOTUS), the graph overhead is significant

### 3. Recommendation
**Start with naive (`mode="naive"`). Upgrade to hybrid only when:**
- Your corpus is cross-document-heavy (reports, incident logs, change logs)
- Your questions require connecting entities across docs
- Latency isn't critical

This matches the academic literature: GraphRAG wins on specific query patterns, not universally.

### 4. SEC 10-Q numeric extraction is a known weak spot
All modes score ~47% on SEC Multi-Doc questions because:
- Gold answers contain specific dollar figures from nested financial tables
- Our chunking extracts table rows as plain text, losing structure
- Vector/BM25/graph all struggle equally with numeric matching
- This is a **chunking limitation**, not a retrieval mode issue

**Potential fix:** markdown-aware table extraction + structured table indexing. Not in current scope.

---

## Performance at Scale

With parallel ingestion (aggressive profile + gpt-4o-mini):

| Metric | Value |
|--------|-------|
| Total ingestion time | 37 minutes |
| Total documents | 461 |
| Total entities extracted | 8,322 |
| Total relationships | 17,637 |
| Average per doc | 4.8s |
| Average cost per doc | $0.003 |
| **Total cost** | **~$1.50** |

For comparison, running the same workload sequentially with a local 7B LLM would have taken ~6-8 hours and zero dollars. OpenAI gave us **~10x speedup** for $1.50.

---

## Query Latency at Scale

Retrieval stays fast even at 8K+ entity scale:

| Corpus | Entities | naive p95 | hybrid p95 |
|--------|---------:|----------:|-----------:|
| NTSB | 320 | 36ms | 31ms |
| PG Docs | 929 | 44ms | 75ms |
| SEC | 2,787 | 65ms | 230ms |
| SCOTUS | 4,286 | 54ms | 177ms |

All **well under the 100ms naive-mode target**. Hybrid crosses 200ms only on SEC (due to 1,872 chunks searched).

---

## Raw Data

```json
{
  "PostgreSQL Docs": {
    "naive":  {"accuracy": 87.5, "avg_lat": 26, "p95_lat": 44, "n": 10},
    "local":  {"accuracy": 85.0, "avg_lat": 33, "p95_lat": 43, "n": 10},
    "global": {"accuracy": 80.0, "avg_lat": 39, "p95_lat": 52, "n": 10},
    "hybrid": {"accuracy": 85.0, "avg_lat": 53, "p95_lat": 75, "n": 10}
  },
  "NTSB Aviation": {
    "naive":  {"accuracy": 73.7, "avg_lat": 24, "p95_lat": 36, "n": 5},
    "local":  {"accuracy": 78.9, "avg_lat": 26, "p95_lat": 31, "n": 5},
    "global": {"accuracy": 63.2, "avg_lat": 21, "p95_lat": 24, "n": 5},
    "hybrid": {"accuracy": 78.9, "avg_lat": 27, "p95_lat": 31, "n": 5}
  },
  "SCOTUS": {
    "naive":  {"accuracy": 88.9, "avg_lat": 37, "p95_lat": 54, "n": 8},
    "local":  {"accuracy": 85.2, "avg_lat": 106, "p95_lat": 147, "n": 8},
    "global": {"accuracy": 81.5, "avg_lat": 50, "p95_lat": 58, "n": 8},
    "hybrid": {"accuracy": 85.2, "avg_lat": 132, "p95_lat": 177, "n": 8}
  },
  "SEC 10-Q Multi-Doc": {
    "naive":  {"accuracy": 47.1, "avg_lat": 38, "p95_lat": 65, "n": 20},
    "local":  {"accuracy": 47.7, "avg_lat": 86, "p95_lat": 193, "n": 20},
    "global": {"accuracy": 48.4, "avg_lat": 52, "p95_lat": 61, "n": 20},
    "hybrid": {"accuracy": 47.1, "avg_lat": 119, "p95_lat": 230, "n": 20}
  }
}
```

Full JSON saved at: `benchmarks/cross_corpus_results.json`

---

## Reproducing These Results

```bash
# 1. Download datasets
cd benchmarks/kg-rag-eval && git clone https://github.com/docugami/KG-RAG-datasets.git .
uv run python benchmarks/extract_kgrag_pdfs.py
uv run python benchmarks/download_pg_docs.py
uv run python benchmarks/download_scotus.py

# 2. Ingest (requires OpenAI API key)
export OPENAI_API_KEY=sk-...
export INGEST_PROFILE=aggressive
uv run python benchmarks/ingest_all.py

# 3. Run benchmarks
uv run python benchmarks/run_all_benchmarks.py
```

**Expected time:** ~40 minutes for ingestion, ~15 seconds for benchmarks.
**Expected cost:** ~$1.50 in OpenAI API usage.
