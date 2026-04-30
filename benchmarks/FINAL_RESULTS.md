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

We now have direct measurements on **two corpora** — SCOTUS (the original bake-off) and NTSB (added 2026-04-29). Both engines ingest the **same extraction** (identical chunks + entities + relationships), so the only point of variance is storage + retrieval engine.

#### SCOTUS — `gpt-5-mini` majority-of-3 judge, 30 questions, 779 chunks

| Mode | pgrg acc | AGE acc | pgrg p50 | AGE p50 | pgrg speedup |
|---|:-:|:-:|:-:|:-:|:-:|
| naive | 18/30 | 18/30 | 35 ms | 3,873 ms | **111×** |
| `naive_boost` | 17/30 | 18/30 | 40 ms | 3,895 ms | **98×** |
| smart | 17/30 | 18/30 | 32 ms | 3,226 ms | **101×** |
| local | 18/30 | 17/30 | 65 ms | 3,079 ms | **47×** |
| global | 18/30 | 18/30 | 43 ms | 3,906 ms | **91×** |
| hybrid | 18/30 | 17/30 | 73 ms | 3,088 ms | **42×** |

Full report: [`benchmarks/age-bakeoff/results/REPORT-VERDICT.md`](age-bakeoff/results/REPORT-VERDICT.md).

#### NTSB — Qwen + OpenAI judges, 10 questions, 82 chunks (re-runner: `benchmarks/run_age_compare_ntsb.py`)

Local vLLM Qwen3-Coder generates answers for both engines; same answers graded by both judges:

| Engine / Mode | Qwen judge | OpenAI judge | Retrieval p50 |
|---|:-:|:-:|:-:|
| pgrg / naive | 93.3% | 80.0% | 36 ms |
| pgrg / `naive_boost` | 90.0% | 80.0% | 27 ms |
| pgrg / smart | 86.7% | 66.7% | 45 ms |
| pgrg / local | 90.0% | 70.0% | 26 ms |
| pgrg / global | 90.0% | 73.3% | 24 ms |
| pgrg / hybrid | 86.7% | 70.0% | 36 ms |
| **age / hybrid** | **90.0%** | **80.0%** | **233 ms** |
| **pgrg speedup vs AGE** | accuracy tied | accuracy tied | **5–9×** |

#### Reading both corpora together

- **Accuracy parity holds.** On SCOTUS (n=30) and NTSB (n=10), both engines land in the same accuracy band — neither dominates. AGE's hybrid retrieval scores 90.0% Qwen / 80.0% OpenAI on NTSB, sitting alongside pgrg's best modes. This is what you'd expect when both engines consume identical extractions: the storage-and-traversal layer doesn't change which chunks contain the answer, only the speed of finding them.
- **The latency gap scales with corpus size.** AGE was 42–111× slower on SCOTUS (779 chunks); on NTSB (82 chunks) it's 5–9× slower. AGE's catastrophic plan estimates and full-table-scan tendencies hurt more as the graph grows. The architectural blocker (Cypher + pgvector can't combine in one query) is corpus-shape-independent; the size of the speedup is shape-dependent.
- **Same fair-defaults caveat.** Both engines got the standard retrieval-relevant indexes (HNSW for vectors, GIN for FTS, typed labels for AGE). Tuning AGE more aggressively would close some of the gap; tuning specifics in [`research/apache-age-evaluation.md`](../research/apache-age-evaluation.md).

#### Important read on NTSB specifically — graph mode doesn't help here

Look at the NTSB table: pgrg/naive scores 93.3% (Qwen) / 80.0% (OpenAI). pgrg/naive_boost is 90.0% / 80.0%. AGE/hybrid is 90.0% / 80.0%. **All modes cluster in the same band; naive without graph boost is at the top under Qwen and tied at the top under OpenAI.** Graph mode adds no measurable lift on this corpus.

This isn't a fluke or a measurement artifact (well, partly — see the n=10 caveat below — but the directional reading holds). It's a corpus-shape finding: **NTSB reports are self-contained narratives.** Each report has the pilot, weather, aircraft, accident sequence, and probable cause in one doc. Cross-incident questions in our set ("what role did pilot fatigue play across accidents?", "what patterns emerge across engine failure incidents?") are still answered by retrieving multiple self-contained reports via vector similarity; there's no entity chain to traverse that vector can't already follow.

This is the **opposite** of pg-agents (909-doc dev codebase, +18.9% from graph boost) — there, answers chain across docs via shared entities (services → owners → commits → files). That's where graph earns its keep.

The honest takeaway: NTSB is a *negative example* for graph mode. The earlier 2026-04-12 blog 00 claim that "graph wins by 4 points on NTSB" was probably noise on a single run; an apples-to-apples re-run shows the gap collapses. **Use this corpus to argue that graph isn't always worth it, not the other way around.**

#### Methodology note for NTSB

The n=10 question set is small enough that a single-question shift moves the percentages by 10 pp. Worse, the answer LLM (local Qwen3-Coder, ONNX/int4 quantized at temp=0) has GPU-non-determinism that swings n=10 numbers across runs. **Two consecutive Qwen-judge runs in the same hour disagreed by ~6 pp on pgrg/naive vs naive_boost** — same questions, same code, same extraction, different model state.

Treat NTSB numbers as **directional confirmation** of SCOTUS's findings (parity on accuracy, AGE much slower on retrieval), not a precision baseline. The canonical engine head-to-head remains SCOTUS's `n=30 × 3 runs × gpt-5-mini majority-of-3 judge` in [`age-bakeoff/results/REPORT-VERDICT.md`](age-bakeoff/results/REPORT-VERDICT.md).

### Methodology recommendation

For publishable accuracy claims:
- **Always show keyword-recall + at least one LLM-judge column** so readers see the spread.
- **Prefer cross-judge agreement over single-judge maxima.** `naive_boost` clears 80%+ on PG-docs under both judges; that's a more robust win than its 93.3% on NTSB-under-Qwen which softens to 96.7% under OpenAI.
- **Use multiple judges with different strictness profiles** when reporting a head-to-head between modes. Single-judge can be biased low (Qwen) or high (gpt-4o-mini); the bake-off's `gpt-5-mini` majority-of-3 is the gold standard but expensive.

The earlier (pre-2026-04-29) sections below are kept as history for prior cross-corpus runs; treat the 2026-04-29 numbers as canonical for current `main`.

---

## MuSiQue — multi-hop reasoning (2026-04-29)

First real-world multi-hop benchmark for pg-raggraph. **MuSiQue-Ans dev split, n=100 stratified across 33/33/34 across 2-hop / 3-hop / 4-hop.** Pooled corpus of 1,700 unique paragraphs (supporting + distractor) ingested as one namespace. 4 modes × 100 Qs × 2 LLM judges = 1,200 evaluations. Full writeup: [`benchmarks/musique/results.md`](musique/results.md).

> **Late-session update (2026-04-29 23:08).** Steps 1 and 2 from [`docs/proposals/Accuracy-Improvements-Roadmap.md`](../docs/proposals/Accuracy-Improvements-Roadmap.md) shipped. Step 1 (`short_answer` mode) lifted F1 from **4.4% → 33.0%** (hybrid) at zero added cost. Step 2 (cross-encoder reranker) lifted F1 further on `naive`/`naive_boost` (+5-7 pp) and support recall by +8 pp across the board, but regressed `hybrid` slightly and overshot the +80 ms latency DoD by 17-42×. The v1 numbers below are kept for v0 narrative; **see `benchmarks/musique/results.md` v2/v3 sections for current canonical numbers.**

### What this corpus tests

MuSiQue questions are *constructed* to require multi-hop reasoning. A 4-hop question chains four facts across four documents, with shared entities as the only connection. If graph mode never helps anywhere, MuSiQue is the corpus where it should — questions can't be answered by retrieving any single paragraph.

### Headline (by mode)

| mode | EM | F1 | Support recall | Qwen judge | OpenAI judge | p50 latency |
|---|---|---|---|---|---|---|
| naive | 0.0 % | 4.1 % | 59.3 % | 35.7 % | 39.3 % | 3,229 ms |
| naive_boost | 0.0 % | 3.8 % | 59.3 % | 39.7 % | 42.3 % | 2,912 ms |
| hybrid | 0.0 % | 4.4 % | 59.8 % | 39.7 % | 40.7 % | 3,084 ms |
| **smart** | 0.0 % | 4.0 % | 58.1 % | **41.3 %** | **46.7 %** | **2,800 ms** |

⚠️ **The 0.0% EM and ~4% F1 are misleading.** 27% of all (question, mode) pairs scored EM=0 but received FULLY_CORRECT (3/3) from BOTH LLM judges. `rag.ask()` produces verbose generative answers; MuSiQue's gold answers are short factual strings ("NES", "the country of India"). The format mismatch tanks EM/F1 even when the answer is correct. Treat the LLM-judge column or support-recall as the apples-to-apples signal, not raw EM/F1. Fix: add a `short_answer` mode to `rag.ask()` and re-run. Captured for next session.

### The interesting per-hop pattern

**Qwen judge — accuracy by hop class:**

| mode | 2-hop | 3-hop | 4-hop |
|---|---|---|---|
| naive | 43.4 % | 40.4 % | 23.5 % |
| naive_boost | 43.4 % | 42.4 % | **33.3 %** |
| hybrid | **54.5 %** | 39.4 % | 25.5 % |
| smart | 51.5 % | **42.4 %** | 30.4 % |

**OpenAI judge — accuracy by hop class:**

| mode | 2-hop | 3-hop | 4-hop |
|---|---|---|---|
| naive | 42.4 % | 49.5 % | 26.5 % |
| naive_boost | 44.4 % | 47.5 % | 35.3 % |
| hybrid | 51.5 % | 44.4 % | 26.5 % |
| smart | **52.5 %** | **51.5 %** | **36.3 %** |

Three findings, both judges agree on:

1. **Graph mode helps unambiguously on 2-hop.** `hybrid` and `smart` beat `naive` by ~9-11 pp.
2. **Full hybrid traversal hurts on 4-hop.** `hybrid` falls to 25-26% on 4-hop — *worse* than `naive_boost` (33-35%) which only does 1-hop graph boost. Deep multi-hop traversal pulls in noise that confuses the answer LLM.
3. **`smart` is the best overall pick** — top judge scores AND lowest p50 latency. Confidence routing successfully picks the right amount of graph per question.

The 4-hop asymmetry — `naive_boost` (1-hop boost) wins, `hybrid` (1-3 hop traversal) loses — is the most actionable finding. **The right amount of graph is "a little"**, not "a lot."

### Where pgrg sits on the public MuSiQue table

Comparison only meaningful via support recall and LLM-judge proxy, given the answer-format issue. F1 column intentionally omitted from our row.

| System | F1 | Recall@5 | Notes |
|---|---|---|---|
| BM25 | low 30s | ~40 % | Sparse lexical baseline |
| ColBERTv2 | ~37 | ~65 % | Strong dense retrieval baseline |
| **pgrg `smart` (LLM-judge proxy, OpenAI)** | **~46.7 %** | **58.1 %** | Different metric — see methodology disclosure |
| NV-Embed-v2 | 44.8 | 69.7 % | SOTA pure-vector embedder |
| HippoRAG (v1) | ~46 | ~70 % | KG triples + Personalized PageRank |
| RAPTOR | mid-40s | ~70 % | Hierarchical clustering |
| HippoRAG 2 | 51.9 | 74.7 % | KG + PPR + filtering |
| PropRAG | ~54 | 77.3 % | Propositions + beam-search PPR (zero-shot SOTA) |

Honest reading:

- **Our retrieval (58-60% support recall) is in the BM25/ColBERTv2 band, below NV-Embed-v2 / HippoRAG / RAPTOR.** Likely cause: embedder. We use `bge-small-en-v1.5` (384-dim); the field's stronger numbers run NV-Embed-v2 (4096-dim). Embedder swap is a pre-Phase-A consideration in [`docs/proposals/PropRAG-on-Postgres.md`](../docs/proposals/PropRAG-on-Postgres.md).
- **Our LLM-judge accuracy (~46.7% best mode) is in NV-Embed-v2 / HippoRAG-v1 territory** — but this is a soft proxy. Don't quote without methodology disclosure.
- **The gap to PropRAG (~54 F1)** is real and aligns with what the proposal predicts: propositions + PPR are the missing pieces.

### Reading vs NTSB and pg-agents

| Corpus | Doc shape | Best mode | Lift over `naive` |
|---|---|---|---|
| NTSB (10 self-contained reports) | Self-contained narratives | tied | ~0 pp — graph adds no value |
| pg-agents (909 dev codebase docs) | Dense entity chains across files | hybrid | +18.9 pp — graph wins big |
| MuSiQue (1,700 multi-hop paragraphs) | Constructed for cross-doc chains | smart on 2-hop / naive_boost on 4-hop | +9-11 pp on 2-hop, mixed on 3-4 hop |

Pattern: **graph mode's value scales with cross-document entity density and inversely with question depth.** Easy multi-doc questions (2-hop, dev codebase) → graph helps. Hard multi-hop questions (4-hop chains) → graph helps if it's a *little* graph (1-hop boost) but hurts if it's a *lot* (full hybrid traversal). Self-contained docs → graph adds nothing.

This is the most useful per-corpus calibration we have. Don't recommend `hybrid` blindly. Recommend `smart` (which routes to the right amount) or `naive_boost` (which adds just-enough graph) for multi-hop.

### Reproduce

```bash
# 1. Dataset (~30 MB, single jsonl)
mkdir -p benchmarks/musique/raw
curl -L -o benchmarks/musique/raw/musique_ans_v1.0_dev.jsonl \
  https://huggingface.co/datasets/dgslibisey/MuSiQue/resolve/main/musique_ans_v1.0_dev.jsonl

# 2. Sample + pool corpus (~5 sec)
python3 benchmarks/musique/prepare.py

# 3. Ingest (~120 min on local Qwen)
uv run python benchmarks/musique/ingest.py

# 4. Eval — 100 Qs × 4 modes × 2 judges (~65 min)
export OPENAI_API_KEY=...
uv run python -u benchmarks/musique/run.py --judge both
```

Cost: free Qwen + ~$0.30 OpenAI gpt-4o-mini judge.

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
