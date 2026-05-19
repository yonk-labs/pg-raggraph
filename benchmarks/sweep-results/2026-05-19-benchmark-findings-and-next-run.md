# Benchmark Findings & Next-Run Design

**Date:** 2026-05-19 · **Status:** investigation closed; fixes tracked separately (see §7).
**Raw data (committed):** `benchmarks/sweep-results/2026-05-18-locomo-sweep.json`, `2026-05-18-locomo-rank-embed.json`, `2026-05-19-mhr-sweep.json`, `2026-05-19-lme-sweep.json`.
**Harness:** `stele-phase6-7/benchmarks/external/pgrg_sweep.py` (MODE A: real datasets via stele's loaders + identical scorer; pg-raggraph as the retrieval backend).

This doc closes the LoCoMo/MHR/LME investigation: what we learned, what to ignore, and a concrete design for the next benchmark run. It is written so a future run can pick up cold.

---

## 1. Scope of what ran

- **Datasets:** LoCoMo (snap-research, 10 samples), MultiHop-RAG (609-doc news corpus, 130-query subset), LongMemEval-S (n=20).
- **Ingest arms:** `none` (no graph), `lede_spacy` (deterministic NER + co-occurrence), `llm` (gpt-4o-mini, later gpt-4o-mini dropped for local Qwen3-Coder). Embedding ladder: bge-small-384 / bge-base-768 / bge-large-1024 / nomic-Q-768.
- **Retrieval ladder:** L0 raw FTS, L1 naive (vec+BM25), L2 naive_boost (graph re-rank), L3 smart, L4 +cross-encoder rerank, GP_* graph-primary (local/global/hybrid).
- **Scorers:** deterministic answer-span recall@k (set-membership) **and** LLM-as-judge (gpt-5-mini, `reasoning_effort=minimal`, independent from the extractor) **and** rank-sensitive MRR / nDCG / hit@1.

---

## 2. The "wrong shape" finding (the headline)

**LoCoMo cannot test a graph retriever. MultiHop-RAG can. The data proves it.**

Graph-primary retrieval (`local`/`global`/`hybrid`) answer-span recall, same engine, three datasets:

| Dataset | Graph-primary | vs lexical base | Interpretation |
|---|--:|--:|---|
| LoCoMo (lede) | 24.9-37.8% | -13 to -26 pp | catastrophic |
| **MHR (lede / llm)** | **80.8-85.4%** | ~ parity (L1 = 83.1) | **competitive** |
| LongMemEval-S (lede) | 45-60% | -30 to -45 pp | collapse |

Why LoCoMo is the wrong shape (root causes, not opinion):

1. **Atomic turns → nothing to traverse.** LoCoMo is ingested as one dialogue turn per document (1-2 sentences). The lede graph on a LoCoMo conversation had **41 entities** (2 speakers + scraps). The same extractor on MHR's 609-doc corpus produced **13,882 entities / 58,685 relationships**. A graph retriever needs a graph; LoCoMo barely has one.
2. **Derived answers.** A large fraction of LoCoMo gold answers are synthesized (a computed date from "last Tuesday", a count). Answer-span recall is structurally capped below where graph traversal could differentiate.
3. **Scorer artifact.** Substring/token-overlap over concatenated top-k rewards verbatim presence and penalizes graph neighborhoods. Span-recall overstated judge accuracy ~2x even on MHR (86.9% span vs ~43% judge).

The sharper truth, not just "LoCoMo bad": on the **right** shape (MHR), graph-primary reaches **parity** with strong lexical retrieval (llm-qwen `GP_local` 85.4% span even edges out L1's 83.1%) - but it does **not beat** lexical+rerank. The graph is viable on graph-shaped corpora; it is not a free win.

---

## 3. Robust cross-dataset conclusions

1. **The cross-encoder reranker (L4) is the only universal lever.** Best LLM-judge on every dataset; decisive on LongMemEval-S (**95% judge, MRR 0.80, hit@1 70%**). It is not the graph. It is dataset-independent and the highest-ROI single change.
2. **Graph-as-enhancer (`naive_boost`) is metric-inert.** L1 ≡ L2 answer-span flatline on all three datasets - confirmed structural: `naive_boost` only re-ranks the set `naive` already returned, and answer-span@k is set-membership, blind to re-ranking. Only set-changing ops (rerank, smart-expansion) move it.
3. **Graph-as-primary is shape-dependent parity, never dominance.** Viable on MHR, collapse on LoCoMo/LME. A per-corpus deployment decision, not a default.
4. **Extraction quality barely moved retrieval.** llm-Qwen graph ≈ deterministic lede co-occurrence on judge accuracy. The expensive LLM extractor did not earn its cost on these benchmarks/metrics.
5. **The embedder is the real retrieval lever** (separate finding, LoCoMo rank-embed sweep): bge-small-384 → bge-large-1024 was +4.3 pp recall but **+27% MRR** (0.186 → 0.236) and +hit@1. Span-recall hid this; rank metrics exposed it.
6. **Span-recall overstates ~2x vs LLM-judge.** Never quote span-only numbers (the chunkshop "verbatim-span artifact"). The dual scorer was essential.

---

## 4. What NOT to trust (honest caveats)

- **Small n.** MHR was a 130-query subset; LME n=20 (judge 95% ≈ 19/20 - directional only). Treat single-digit pp gaps as noise.
- **Self-grading judge.** One gpt-5-mini call both answers from context and grades vs reference - internally consistent across cells (apples-to-apples) but slightly lenient vs a separate judge. Good for ranking cells, not for an absolute leaderboard number.
- **LoCoMo numbers.** The 2-sample wide pass (~51%) materially under-represented vs the full-10 (~68.7% reranked). Quote the full-set, reranked, judge number or nothing.
- **Harness location.** The harness lives in `stele-phase6-7` (separate repo). pg-raggraph is the backend via direct `GraphRAG` calls. Not committed in this repo.
- **Pre-K1 retrieval.** All numbers are on the current retrieval path, which seq-scans the namespace (K1). Two-stage retrieval (the K1 fix) changes candidate selection - **all retrieval numbers must be re-baselined after K1 lands.**

---

## 5. Suggested next benchmark run (concrete)

Ordered by value. Pre-register the hypothesis before running (per the original brief discipline).

### 5.1 Highest value: stratify MHR by question type

The aggregate MHR number hides the only question that matters for GraphRAG: **does the graph win on questions that REQUIRE multi-hop?** MHR queries carry a `question_type` (inference / comparison / temporal / null). The next run must report graph-primary vs lexical **per question_type**, not pooled. Hypothesis to pre-register: *graph-primary beats lexical+rerank on `inference`/`comparison` (multi-hop) questions specifically, even though it only ties in aggregate.* If that is false, GraphRAG's core value proposition is unsupported on this benchmark - a major finding either way.

### 5.2 Right the benchmark set

- **Demote LoCoMo** to a memory/recall datapoint only, always with the "cannot test graph" caveat. Never headline a graph claim with it.
- **Promote MHR + add MuSiQue / 2WikiMultiHopQA** (true compositional multi-hop, gold supporting facts) as the graph battleground. These have explicit multi-hop supervision LoCoMo lacks.
- **Scale the query subset** for statistical power: MHR full ~2.5k queries (or a 500+ disclosed subset), LME n >= 100. The 130/20 subsets are directional only.

### 5.3 Metric discipline

- LLM-judge is primary; span-recall is the floor (report both, never span alone).
- Add nDCG@k alongside MRR/hit@1 (already wired) - the rank metrics, not span, are what showed the embedder effect.
- Consider a second, different judge model for an agreement check (Cohen's kappa); flag any cell where judges disagree > 15%.

### 5.4 Re-baseline after fixes

- After **K1 (two-stage retrieval)** lands, re-run the full ladder - candidate selection changes, so prior retrieval numbers are obsolete for comparison.
- After **F1 (bounded onnxruntime threads) + the embedder upgrade to bge-base/large**, staging speed improves dramatically. The "~10-day run" is a direct symptom of the K1 seq-scan + per-process local embedder; the remediation fixes are also the benchmark-speed fixes.

### 5.5 Operational

- Use the local Qwen vLLM for extraction (free) and gpt-5-mini for judging (independent, ~$2/run) - this split worked and should be the standard.
- Stage once, sweep many (the harness already does this); never re-ingest per cell.
- Keep cell-level raw JSON + a committed findings doc per run (this format).

---

## 6. One-line verdict

The reranker is the lever; the graph is shape-dependent parity, not a default win; the embedder is the hidden retrieval lever; LoCoMo cannot adjudicate any of it. The next run's job is the per-question-type MHR stratification - that is the only remaining test of GraphRAG's actual thesis.

---

## 7. Fixes are tracked elsewhere (you are moving on to these)

This investigation is closed. The performance and correctness issues it surfaced are planned in:

- `docs/operations-guide.md` (K1-K9) and `docs/deployment-embedding-scaling.md` (F1-F7) - the issues.
- `docs/superpowers/plans/2026-05-19-pg-raggraph-scale-remediation.md` - the fix + mitigation + test plan.
- `skill-output/followup-prompt/Followup-Session-Prompt-scale-remediation.md` - the paste-ready autonomous driver for executing the plan.

K1 (two-stage retrieval) is both the top scale fix and the prerequisite for a faster, valid next benchmark run. Do K1 first; then re-baseline per §5.4.
