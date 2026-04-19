# Diagnostic Findings — 2026-04-18

## TL;DR
- **10-pp threshold not cleared.** scotus: age +5.83 pp, pgrg +0.00 pp (k=10 → k=50). acme sweep is invalid.
- **Gold set is not the bottleneck.** 0/30 paraphrases judged wrong/hallucinated.
- **~42-45% of required facts never appear in any retrieved chunk at k=10** on scotus (age 16/38, pgrg 17/38). This is the real ceiling.
- **`top_k_sweep.json → corpora.acme.*.*` is polluted with scotus content** — 100/100 chunk IDs carry `case-*` prefix, 0/1,700 chunks contain any acme literal. The acme corpus was not ingested when the sweep ran.
- **Multi-hop-bridging is not the class that benefits from larger k** — it is already the best-recovered class at k=5 (0.650) and plateaus. Factual is the only class with meaningful lift (+9.72 pp, but driven by 2 questions).

## 1. Gold strictness
0/30 alternative phrasings judged `wrong`/`hallucinated`. Across `corpora.acme[*]` and `corpora.scotus[*]`, every `strict_count` is 0 and every verdict is `fully_correct`. Judge-vs-itself is consistent. Caveat: generator==grader (`src/age_bakeoff/diagnostics.py:58-62`); this does not bound corpus-text findability — §3 does.

## 2. Context relevance (`context_relevance.json`)

Fraction of retrieved chunks scoring >0, and tail distribution:

| Corpus | Engine | chunks>0 | mean score | qs with ≥1 ≥0.5 | qs with 0 relevant |
|---|---|---|---|---|---|
| acme | age | 39/100 | 0.303 | 9/10 | 1/10 |
| acme | pgrg | 42/100 | 0.332 | 9/10 | 1/10 |
| scotus | age | 25/100 | 0.229 | 10/10 | 0/10 |
| scotus | pgrg | 21/100 | 0.194 | 9/10 | 1/10 |

Per-class `avg_max` is 1.0 almost everywhere, but `avg_mean` is low (0.1-0.6) — the retriever finds 1-3 gold chunks and 7-9 filler. Cross-checked via top_k_sweep at k=10 on scotus: chunks containing ≥1 required fact = 55/100 (age), 58/100 (pgrg). Facts missing from ALL retrieved chunks = 16/38 age, 17/38 pgrg.

**Multi-hop hypothesis does not hold.** scotus class recall at k=10: factual 0.347, single_hop 0.667, semantic 0.569, multi_hop_bridging 0.733. Factual is the worst class; multi-hop is the best.

## 3. Top-k sweep

### 3a. Data validity
`top_k_sweep.json → corpora.acme` is invalid — 100/100 sampled chunk IDs have `case-*` (scotus) prefix; 0/1,700 chunks contain any acme literal; 1,058/1,700 scotus-sweep chunks contain scotus literals. The acme corpus was not loaded during the sweep. Note: `context_relevance.json` acme data IS valid (max scores hit 1.0), because it ran earlier against a different DB state.

### 3b. Recall curve (scotus only)

| Corpus | Engine | k=5 | k=10 | k=20 | k=50 | Δ(50−10) pp |
|---|---|---|---|---|---|---|
| scotus | age | 0.555 | 0.572 | 0.630 | 0.630 | **+5.83** |
| scotus | pgrg | 0.472 | 0.538 | 0.538 | 0.538 | **+0.00** |

Per-question lift: scotus/age 2/10 questions improved k=10→k=50 (total +2 facts); scotus/pgrg 0/10. Questions hitting 100% recall: scotus/age 1/10 at all k; scotus/pgrg 0/10 at all k.

### 3c. Lift by class (scotus, engines averaged)

| Class | k=5 | k=10 | k=20 | k=50 | Δ(50−10) pp |
|---|---|---|---|---|---|
| factual | 0.306 | 0.347 | 0.444 | 0.444 | **+9.72** |
| single_hop | 0.667 | 0.667 | 0.667 | 0.667 | +0.00 |
| semantic | 0.528 | 0.569 | 0.569 | 0.569 | +0.00 |
| multi_hop_bridging | 0.650 | 0.733 | 0.733 | 0.733 | +0.00 |

Only factual benefits, and it's still under 10 pp.

### 3d. Latency cost (p50)

| Corpus | Engine | k=10 | k=50 | Δ |
|---|---|---|---|---|
| scotus | pgrg | 58.1 ms | 59.6 ms | +1.5 ms |
| scotus | age | 2,583.9 ms | 3,272.7 ms | +688.8 ms |
| acme | pgrg | 56.7 ms | 62.4 ms | +5.7 ms |
| acme | age | 2,127.3 ms | 2,618.7 ms | +491.4 ms |

For pgrg raising k is free; for AGE it costs ~500-700 ms/query.

### 3e. DC-003 verdict
**Not cleared.** Max lift is +5.83 pp at engine level, +9.72 pp for one class driven by 2 questions. Growing `top_k` alone will not hit the ≥10 pp bar.

## Recommendations (ROI-ordered)

1. **Do not ship "raise default top_k to 50" as the DC-003 fix.** Expected gain ≤+5.83 pp on one (corpus, engine) cell. Fails the ≥10 pp bar. (Evidence: §3b.)

2. **Attack the 42-45% of facts missing from retrieved context at k=10.** Two probes, in order:
   - **BM25 weight / hybrid scoring** (Task 2.4 `--signals` knob, already queued). Factual-class required_facts like `"2022"`, `"Civil Rights"` are exact-string needs that lexical search should dominate on. If lexical recovers half the 16 missing scotus facts, that alone is ~+20 pp on factual and ~+4-6 pp overall.
   - **Required-fact hit rate as a retrieval debug scorer.** For each missed fact, grep raw corpus to confirm the chunk exists, then investigate why the retriever ranked it below k.

3. **Re-run `diagnose top-k-sweep` with acme actually ingested.** Current acme slice is unusable. Cost: one re-ingest + LLM-free sweep.

4. **Park the gold-strictness thread.** 0/30 paraphrases failed. No yield here.

---

# Addendum — naive + naive_boost sweep results (2026-04-18 22:20 EDT)

## TL;DR
- **DC-003 NOT cleared on any (corpus, engine) cell.** Best lift: pgrg-scotus +1 question (10 → 11) = **+3.3 pp**. Threshold is +3 questions (+10 pp).
- `naive_boost` (the documented winner in `docs/modes.md` with +18.9% avg top score on pg_agents) did **not** reproduce that lift on the bakeoff. naive_boost matched plain naive on every cell.
- On acme, both naive and naive_boost went **backwards** vs hybrid baseline (5 → 4 for each engine).
- `smart` remains the best pgrg mode on scotus (11/30) and acme (6/30). Adaptive routing beats any single-mode choice.

## Full matrix — fully_correct out of 30 (Δ pp vs hybrid baseline)

| Mode | acme/age | acme/pgrg | scotus/age | scotus/pgrg |
|---|---|---|---|---|
| hybrid (baseline) | 5 | 5 | 11 | 10 |
| smart | 4 (−3.3) | 6 (+3.3) | 12 (+3.3) | 11 (+3.3) |
| local | 4 (−3.3) | 6 (+3.3) | 11 (0) | 10 (0) |
| global | 6 (+3.3) | 7 (+6.7) | 11 (0) | 10 (0) |
| **naive** | 4 (−3.3) | 4 (−3.3) | 11 (0) | 11 (+3.3) |
| **naive_boost** | 4 (−3.3) | 4 (−3.3) | 11 (0) | 11 (+3.3) |

## Retrieval latency p50 (ms)

| Mode | acme/age | acme/pgrg | scotus/age | scotus/pgrg |
|---|---|---|---|---|
| hybrid | 45.9 | 32.6 | 2361 | 70 |
| smart | 44.9 | 23.0 | 2389 | 36 |
| naive | 47.1 | **21.0** | 2175 | **22** |
| naive_boost | 46.9 | **21.5** | 2599 | **24** |

pgrg naive / naive_boost are the fastest modes at ~22 ms on scotus (3× faster than smart at 36 ms, 3× faster than hybrid at 70 ms). **Speed win holds, quality win does not.**

## Why naive_boost's +18.9% claim did not reproduce

The `docs/modes.md:338-357` benchmark measured **avg top score** and **high-confidence count** on a 909-doc pg_agents corpus with 20 open-ended dev questions. The bakeoff measures **LLM-judged fully_correct** on gold-labeled questions with specific required facts. These are different metrics:

- Top score / confidence reflect **retrieval rank quality** — how well the graph boost re-ranks semantically-adjacent chunks.
- Fully correct reflects **answer correctness** — did the generator produce the gold fact?

naive_boost reranks chunks but does not pull in new chunks (by design — that's what makes it cheap). If the required fact is not in the top-K at naive retrieval time, boost cannot recover it. The 42-45% missing-fact rate documented in §2 bounds what boost can do.

## DC-003 implications

- `naive_boost` is **not** the DC-003 fix. Scope narrows to remaining candidates: Task 2.4 BM25 isolation, cross-encoder re-ranking, MSR datasets with harder multi-hop questions.
- This counts as a **documented negative experiment** under SC-002's alternate-path ("≥3 distinct negative experiments"). Current negatives: top_k sweep, naive-mode, naive_boost-mode.
- Smart mode remains pgrg's best bakeoff performer. Consider making `smart` (not `hybrid`) the REPORT.md default row.

## Sweep hygiene — two bugs fixed this run

1. **Bakeoff CLI `--mode` help text missing `naive_boost`** — `cli.py:221` listed valid modes as `hybrid|smart|local|global|naive`. pg-raggraph accepts `naive_boost` (`retrieval.py:158`). Fixed; `config.py:21` comment updated to match; two acceptance tests added in `tests/test_config.py`.
2. **`judge` and `diagnose context-relevance` skipped labelled variants under `--corpus`** — `cli.py:345` and `cli.py:778` filtered by raw-filename stem (`"acme__naive" not in ("acme", "scotus")` → skip). Now both sites filter by base corpus via `_corpus_and_label_from_stem`. Phase 2 results were not affected because those runs judged bare `judge` (no `--corpus` arg).

## Observability added

`benchmarks/age-bakeoff/scripts/run-mode-sweep.sh` wraps each `run` command with `timeout 45m`, verifies `results/raw/{corpus}__{label}.json` exists with `EXPECTED_RECORDS=180` after exit, and dumps diagnostics (log tail, `ps`, `docker stats`, both DBs' `pg_stat_activity` + blocked locks, disk free) to `/tmp/bakeoff-stall-<ts>-<tag>/` on any failure. Reusable for Task 2.4, MSR, pg-src.
