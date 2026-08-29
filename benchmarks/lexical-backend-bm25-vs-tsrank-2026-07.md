# Lexical backend: BM25 vs ts_rank — benchmark & tuning

**Date:** 2026-07-11 · **Trigger:** issues #102/#103 (hyphen tokenizer, exact-ID retrieval) · **Decision at stake:** should `lexical_backend` default flip from `ts_rank` to `bm25`?

## TL;DR

- The **0.9.1 hyphen-tokenizer fix** (`_to_or_tsquery`) was the real exact-ID win. On the default **bge-small/384** stack the vector leg already discriminates hyphen-numeric IDs, so the query-side tokenizer was the gap — not the scoring backend.
- **BM25 does NOT beat ts_rank** on scotus — neutral-to-worse on retrieval metrics and **+32% slower** on hybrid.
- **Tuning it did not help on scotus** (19 configs across `k1` × `b` × `w_bm25`): the gap is structural and *widens* when the lexical leg is weighted up. ts_rank's proximity ranking beats BM25's IDF on semantic QA.
- **But bm25 WINS on locomo** (keyword / exact-token conversational recall) — naive hit@1 0.267 vs 0.233. The advantage is **query-shape-dependent**: ts_rank for semantic QA, bm25 for keyword/ID lookups.
- **Decision: default stays `ts_rank`; bm25 opt-in for keyword/ID/exact-token workloads.** No flip.

## Method

- Harness: `benchmarks/e2e` (`run.py`), sweep via `PGRG_LEXICAL_BACKEND` env (query-time knob; no re-ingest needed between backends).
- Corpus: **scotus** (391 SCOTUS opinions — docket numbers, case captions, rare legal terms: the corpus that most stresses the lexical leg). 30 queries, seed 4225.
- Stack: **bge-small/384** (the actual default the setting governs), live DB. Arm: `lede_spacy` (no LLM). Modes: `L1_naive` (isolates vector+lexical), `GP_hybrid` (adds graph).
- Judge: **gpt-5-mini** (OpenAI). Metrics: judge_score, span_recall, mrr, ndcg, hit@1, latency p50/p95.

## Baseline results (k1=1.2, b=0.75)

| Metric | Mode | ts_rank | bm25 | Δ (bm25−ts) |
|---|---|---|---|---|
| judge_score | naive | 0.967 | 1.000 | +0.033 (1 question, n=30 noise) |
| judge_score | hybrid | 0.867 | 0.817 | −0.050 |
| mrr | naive | 0.183 | 0.156 | −0.028 |
| mrr | hybrid | 0.122 | 0.092 | −0.031 |
| ndcg | naive | 0.174 | 0.162 | −0.012 |
| ndcg | hybrid | 0.147 | 0.097 | −0.050 |
| span_recall | naive | 0.200 | 0.200 | 0.000 |
| span_recall | hybrid | 0.200 | 0.133 | −0.067 |
| latency p50 | naive | 116 ms | 118 ms | +2 ms |
| latency p50 | hybrid | 300 ms | 395 ms | **+96 ms (+32%)** |

**Read:** judge deltas are within n=30 noise (±1 question); every deterministic retrieval metric is equal-or-worse for BM25; BM25 adds real latency on hybrid (per-row correlated BM25 subquery over the expanded candidate set). Judge scores are near-ceiling (0.87–1.0) → scotus answers are easy regardless of backend, so the deterministic metrics carry the signal.

## Baseline verdict

**Keep `ts_rank` as the default; BM25 stays opt-in.** With default Okapi params there is no measured accuracy gain and a latency cost. This contradicts #103's assumption that a bm25-default flip is "load-bearing" — on our actual stack the tokenizer fix already closed the exact-ID gap.

Limitations: n=30, single corpus, judge near-ceiling. The deterministic metrics + latency all point the same way, so a larger n is unlikely to reverse the baseline call.

## Tuning (why BM25 lagged, and can it be fixed?)

Hypotheses for BM25 underperformance on scotus:
1. **Length normalization `b=0.75`** over-penalizes long legal chunks (the gold chunks are long). Lowering `b` should help most.
2. **TF saturation `k1`** may be mistuned for chunk-scale text.
3. Under RRF fusion (default) only the lexical *rank* matters; ts_rank's cover-density/proximity ranking may beat BM25's IDF+length ranking on scattered legal query terms.

### Sweep 1 — `bm25_b` / `bm25_k1` (naive, mrr/ndcg, `--judge none`)

| config | mrr | ndcg | recall | hit@1 |
|---|---|---|---|---|
| **ts_rank (baseline)** | **0.183** | **0.174** | 0.200 | **0.167** |
| bm25 k1=1.2 b=0.75 (default) | 0.156 | 0.162 | 0.200 | 0.133 |
| bm25 k1=1.2 b=0.5 | 0.156 | 0.162 | 0.200 | 0.133 |
| bm25 k1=1.2 b=0.25 | 0.157 | 0.163 | 0.200 | 0.133 |
| bm25 k1=1.2 b=0.0 | 0.161 | 0.164 | 0.200 | 0.133 |
| bm25 k1=0.6 b=0.0 | 0.161 | 0.164 | 0.200 | 0.133 |
| bm25 k1=2.0 b=0.0 | 0.161 | 0.166 | 0.200 | 0.133 |

`k1`/`b` are **near-inert** (mrr 0.156→0.161 across the whole range) and every config stays below ts_rank. `span_recall` is identical (0.200) everywhere. Length normalization was **not** the lever — dropping `b` to 0 barely moved anything.

### Sweep 2 — `w_bm25` fusion weight (the real lever)

The default fusion is weighted-RRF `w_sem=0.50 / w_bm25=0.20` (`retrieval.py:131`) — the vector leg carries **2.5× the lexical weight**, which is why bm25's internal scores wash out. Raising `w_bm25` (bm25 pinned at its best k1=1.2/b=0.0):

| w_bm25 | ts_rank mrr | bm25 mrr |
|---|---|---|
| 0.20 | 0.183 | 0.161 |
| 0.35 | 0.178 | 0.158 |
| 0.50 | **0.200** | 0.140 |
| 0.70 | 0.183 | 0.140 |

**The gap widens as the lexical leg matters more** — raising `w_bm25` *helps ts_rank and hurts bm25*. (Bonus, tentative at n=30: `w_bm25≈0.5` lifts ts_rank to mrr 0.200 / hit@1 0.200 — a possible ts_rank tuning win worth a bigger-n check.)

### Per-stratum (naive)

No stratum favors bm25 on retrieval rank; the only bm25 "wins" are +1-question judge deltas at n=10 (noise). scotus has **no keyword/exact-ID stratum** — every question is natural-language legal QA.

## Wheelhouse test — locomo (keyword / exact-token conversational recall)

To check bm25's *actual* strength, ran the same head-to-head on **locomo** (272 docs, 30q, exact turn-ID tokens like `D3:11`; bge-small/384; gpt-5-mini judge). Here the direction **flips**:

| Metric | Mode | ts_rank | bm25 | winner |
|---|---|---|---|---|
| hit@1 | naive | 0.233 | **0.267** | **bm25** |
| mrr | naive | 0.296 | **0.312** | **bm25** |
| ndcg | naive | 0.323 | 0.322 | tie |
| judge | naive | 0.950 | 0.933 | ts (±1 q) |
| (hybrid) | — | slightly ahead | — | ts_rank |

Per-category (naive): bm25 **ties or wins every category**, winning `category=1` decisively (hit@1 0.143→0.286, doubled; n=7) and dead-even on the bulk `category=4` (n=18). bm25 loses no category.

**Read:** on a corpus with exact-token / ID signal, BM25's IDF ranks the exact chunk higher — the inverse of scotus. Small n (per-category 2–18), so individual cells are noisy, but the aggregate direction is consistent and opposite to scotus.

## Final conclusion

**bm25 cannot be tuned to match ts_rank on semantic QA — but it wins on keyword/exact-token recall.** On scotus, across 19 configs (k1 × b × w_bm25) plus per-stratum, ts_rank is equal-or-better on every retrieval metric and the gap *grows* when the lexical leg is weighted up. On locomo, the direction flips — bm25 wins the naive rank metrics. Root cause: **ts_rank's cover-density (query-term proximity) ranking beats BM25's IDF bag-of-words on natural-language questions over prose; BM25's IDF wins when the query is an exact-keyword / exact-token lookup.** The backend advantage is query-shape-dependent, not global.

**Decision: `lexical_backend` default stays `ts_rank`. Do not flip.** The common RAG case is semantic questions (scotus-shaped) — ts_rank wins there and is lower-latency. bm25 stays **opt-in**, the right choice for **keyword / exact-ID / exact-token workloads** (tickets, incidents, SKUs, region codes, turn/session IDs, conversational recall), demonstrated on locomo. The 0.9.1 hyphen-tokenizer fix makes exact-ID *matching* correct on both backends; the exact-ID gap #103 raised was closed by that fix, not the backend.

**When to flip bm25 on:** corpus is keyword/ID/exact-token heavy AND queries are lookups (not open-ended semantic) AND the embedder is weak enough that the vector leg can't discriminate. Otherwise leave ts_rank.

Limitations: n=30 per corpus, judge near-ceiling, per-category cells small (2–18). Directions are consistent and mechanistically explained (proximity vs IDF), so unlikely to reverse; specific per-category deltas are noisy.
