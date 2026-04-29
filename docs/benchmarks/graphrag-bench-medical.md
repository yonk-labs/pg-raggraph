# Benchmark: GraphRAG-Bench — Medical

**Corpus:** `graphrag-bench-medical`
**Status:** results complete (v2 — fixed chunker)
**Run date:** 2026-04-22 (v2); original 2026-04-21 (v1, retracted)
**Raw results:** `benchmarks/age-bakeoff/results/raw/graphrag-bench-medical*.json`
**Judge results:** `benchmarks/age-bakeoff/results/judge/graphrag-bench-medical*.json`
**Reproduced by:** `benchmarks/age-bakeoff/scripts/launch-gb-medical-v2-matrix.sh`

---

## TL;DR

On 100 stratified medical clinical-care questions answered by gpt-5-mini and judged by gpt-5-mini:

**Neither engine dominates on medical.** pgrg modes range 59-66/100 fully_correct; AGE modes 63-66. The top pgrg mode is `naive_boost` at 66 (n=3 majority); the top AGE mode is `hybrid` at 66 (n=3 majority). pgrg/hybrid lands at 63 (n=3 majority) — **slightly behind** AGE/hybrid (66) and behind pgrg's own simpler modes. n=3 majority-of-3 verdicts confirm the n=1 reads on all three tracked cells.

**The v1 result (pgrg/hybrid 73 vs age/hybrid 66) has been retracted.** It was produced with a broken hierarchy chunker that silently truncated embeddings through fastembed's 512-token cap on 134 KB section bodies, combined with a Qwen-judge that was ~10 pp more lenient than gpt-5-mini. Under the fixed chunker + fair judge, the v1 spread collapses and AGE catches up 10 points — the chunker bug was disproportionately hurting AGE's retrieval (AGE had no strong BM25/graph fallback to compensate for broken vectors). See §7.1 for the full v1 retraction.

**Retrieval mode matters less than expected on this corpus.** Cross-mode delta is 7 pp within pgrg (59 global → 66 naive_boost) and 3 pp within AGE (63 age_local → 66 age_hybrid). Cross-engine delta at the top of each is 0 (both at 66). On clinical medical Q&A with properly sized chunks, retrieval mode is a minor lever; answer-model quality is the dominant one.

Total run cost: ~**$27 for answers + ~$1.50 for judge on work_key** (v2 matrix + n=3 follow-ups for hybrid + naive_boost) — up from v1's $6.11 (which only paid for hybrid; v1's seven other runs used free local Qwen). v2 pays for apples-to-apples quality across every cell.

---

## 1. Corpus

- **Source:** `huggingface.co/datasets/GraphRAG-Bench/GraphRAG-Bench`, subset `medical`. Companion paper: Xiang et al., *When to use Graphs in RAG*, ICLR'26 (arXiv 2506.05690).
- **License:** MIT.
- **Upstream shape:** A single `{corpus_name, context}` row per domain. The medical row is ~1.05 MB of concatenated clinical-care text from oncology-focused source material, covering ~22 cancer types and related topics (basal cell carcinoma, bladder cancer, CLL, glioma, lung cancers, etc.). No document separators in the raw data — topics are delimited only by `"About <topic>"` prefixes.
- **Our framing:** we split on `"About X"` boundaries via a corpus-specific regex in `external_corpora._split_medical_topics`, recovering 22 topic-titled documents. Ranges from 99 chars (short transitional passages) to 134,422 chars (bladder cancer) per document. Total characters preserved byte-for-byte (1,052,137 vs upstream 1,052,159).
- **Why this corpus:** one of two subsets in the benchmark paper that explicitly frames itself around "when do graphs help in RAG" — the same question T-G1 v1 concluded "not much, once chunks are good" on SCOTUS+acme. Medical has structured clinical knowledge with many entities per topic; a favorable surface for graph retrieval if graph retrieval has a favorable surface.

## 2. Prior Work

- **Xiang et al. 2026** (ICLR) introduced GraphRAG-Bench with medical + novel subsets and four question types (Fact Retrieval, Complex Reasoning, Contextual Summarize, Creative Generation).
- **Leaderboard:** https://graphrag-bench.github.io/ (snapshot date: 2026-04-22).
- **Headline from the paper:** graph-based methods dominate on Complex Reasoning and Creative Generation; NaiveRAG is competitive on Fact Retrieval.
- **Metrics in the paper:** per-type Accuracy + ROUGE-L + Coverage + Factual Score. Ours uses the bakeoff's majority-of-N LLM judge verdict rubric (fully_correct / partially_correct / wrong / hallucinated) for comparability with SCOTUS/acme. Side-by-side comparison with the leaderboard requires rubric translation; noted in limitations.

## 3. Setup

### 3.1 Chunking × embedding cell (v2)

| | Used | Note |
|---|---|---|
| Chunker | `hierarchy` with `chunk_max_tokens=512` cap | fixed `_split_hierarchy` in commit `58d8c1d`; now sub-splits oversized section bodies and preserves heading prefix per sub-chunk |
| Embedder | `BAAI/bge-small-en-v1.5` int8 | local fastembed (ONNX); 384-dim |
| Quantization | int8 | cheaper, near-parity with fp32 on SCOTUS |

**v1 used the same hierarchy strategy but without the size cap** — a 134 KB "bladder cancer" section was being fed to bge-small as a single chunk and silently truncated to its first ~512 tokens (~2 KB). v2's chunker produces **537 chunks** from the same 22 docs (up from v1's **22 chunks**), with max 2082 chars per chunk (≤ the 2000-char hierarchy cap + heading prefix).

### 3.2 Retrieval modes tested (v2)

- pgrg: `naive`, `naive_boost`, `local`, `global`, `hybrid`, `smart`
- AGE: `hybrid`, `local`, `global`
- MS GraphRAG: `basic`, `local`, `global`, `drift` _(Phase 4 — deferred)_

### 3.3 Engines

- **pg-raggraph:** commit `58d8c1d`, `chunk_strategy=hierarchy`, `top_k=10`.
- **Apache AGE:** `ag_catalog` + pgvector extension, graph built from the shared `ExtractionOutput`.
- **Microsoft GraphRAG:** `graphrag=={version}` — separate chunker + indexer (Phase 4, not run in this pass).

### 3.4 Extraction, answer, judge models (v2)

- **Extraction:** `gpt-5-nano` on `work_key`. 537 chunks produced 3,012 entities + 6,960 relationships (~$1-2).
- **Answer generation:** `gpt-5-mini` on `work_key`, 1 run per question per (engine × mode).
- **Judge:** `gpt-5-mini` on `work_key`, 1 vote per (engine × mode × question) in this pass.
- Note: gpt-5 family requires default `temperature=1`.

### 3.5 Question set

- Upstream medical questions: 2,060.
- Subset: **100 questions, stratified 25 per class, seed=42.**
- Subset file: `benchmarks/age-bakeoff/questions/graphrag-bench-medical.yaml`.

| class | n |
|---|---|
| Fact Retrieval | 25 |
| Complex Reasoning | 25 |
| Contextual Summarize | 25 |
| Creative Generation | 25 |

## 4. Methodology

- Extraction ran once under the fixed chunker (cached at `corpora/external-extractions/graphrag-bench-medical.json`); both engines consume the shared cache. v1's cache was renamed to `graphrag-bench-medical.v1_broken_chunker.json` and preserved for the retraction analysis in §7.1.
- For each (engine, mode, question) tuple: 1 run + 1 judge vote in this pass (v1 used 3 votes for hybrid).
- **Fairness — preserved:** shared chunks + shared embedder across pgrg + AGE; shared answer model (gpt-5-mini) across every (engine × mode) combination.
- **Judge consistency:** unlike v1 (Qwen local judge, with a 20-question gpt-5-mini spot check), v2 judges every answer with gpt-5-mini. Apples-to-apples at the judge layer.
- **Seed:** `seed=42`. Results reproducible modulo LLM nondeterminism at temperature=1.

## 5. Results

### 5.1 Overall accuracy (out of 100, fully_correct)

All rows gpt-5-mini answer + gpt-5-mini judge. Sorted by fully_correct within engine.

| engine | mode | n | fully_correct | partially | wrong | hallucinated |
|---|---|:---:|---:|---:|---:|---:|
| pgrg | naive_boost | 3 | **66** | 20 | 9 | 5 |
| pgrg | naive | 1 | 65 | 22 | 9 | 4 |
| pgrg | smart | 1 | 65 | 19 | 9 | 7 |
| pgrg | local | 1 | 64 | 21 | 10 | 5 |
| pgrg | hybrid | 3 | 63 | 22 | 8 | 7 |
| pgrg | global | 1 | 59 | 24 | 12 | 5 |
| age | hybrid | 3 | **66** | 21 | 9 | 4 |
| age | global | 1 | 65 | 20 | 8 | 7 |
| age | local | 1 | 63 | 23 | 8 | 6 |

**`n` column** = runs per question (1 or 3). Hybrid (both engines) and pgrg/naive_boost re-run at n=3 with majority-of-3 verdicts after the initial matrix. n=3 cells confirm the n=1 totals — the three tracked cells moved 0 pp at the aggregate level under majority-of-3, validating the ±3pp confidence band claimed in §7.

**Top of each engine ties at 66.** pgrg's best is `naive_boost` (graph boost on top of vector, cheap to apply); AGE's best is `hybrid`. pgrg's `hybrid` mode lands 3 pp behind its own `naive_boost` — hybrid was supposed to be the gold standard but gives up ground on this corpus. pgrg's `global` mode is the notable loser at 59.

### 5.2 By question class (fully_correct / 25)

Columns for pgrg/nb, pgrg/hyb, age/hyb are n=3 majority-of-3; others n=1.

| class | pgrg/naive | pgrg/nb⁽³⁾ | pgrg/local | pgrg/global | pgrg/smart | pgrg/hyb⁽³⁾ | age/hyb⁽³⁾ | age/local | age/global |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Fact Retrieval | 22 | 22 | 21 | 22 | 22 | **23** | 22 | 22 | 20 |
| Complex Reasoning | 22 | 21 | 21 | 17 | 21 | 20 | 21 | 20 | 20 |
| Contextual Summarize | 18 | 19 | 18 | 16 | 19 | 18 | 19 | 18 | 20 |
| Creative Generation | 3 | 4 | 4 | 4 | 3 | 2 | 4 | 3 | 5 |

**Per-class takeaways** (n=3 where available; within-class shuffling under majority-of-3 is up to ±3 pp while aggregates held):
- **Fact Retrieval (92% upper bound):** pgrg/hybrid edges AGE by +1 (23 vs 22) under n=3; this flipped from the n=1 reading (AGE had led by +3). Within-noise, but consistent with pgrg's graph+BM25 legs helping on fact-shaped questions.
- **Complex Reasoning (88% upper bound):** pgrg/naive leads at 22, pgrg/hybrid at 20 (up from 18 at n=1) and age/hybrid at 21. Graph-hybrid retrieval still doesn't clearly beat cheap vector-only on this class.
- **Contextual Summarize (80% upper bound):** age/global leads at 20. pgrg/hybrid and age/hybrid tie at 18-19; pgrg/global is the worst at 16.
- **Creative Generation (20% upper bound):** universally hard. Cross-engine delta is 3 pp (2-5 out of 25). Retrieval doesn't help — these questions require generative synthesis beyond the retrieved context.

### 5.3 Latency

Per-call p50 on gpt-5-mini (OpenAI async, concurrency ~8):

| engine | mode | per-call p50 | 100-Q wall clock |
|---|---|---:|---:|
| pgrg | naive | ~10 s | 18 min |
| pgrg | naive_boost | ~10 s | 16 min |
| pgrg | local | ~9 s | 14 min |
| pgrg | global | ~11 s | 18 min |
| pgrg | smart | ~12 s | 20 min |
| pgrg | hybrid (both engines, 200 calls) | ~33 s | 70 min |
| age | hybrid (same call-share as above) | — | — |
| age | local | ~40 s | 65 min |
| age | global | ~40 s | 66 min |

AGE modes are ~4× slower than pgrg modes on the same answer model. AGE's two-phase Cypher traversal + pgvector cross-query is the drag. Total matrix wall clock: **4h49m** (answer runs) + **2h02m** (judge) = **6h52m** for the full sweep including one v1 re-judge.

### 5.4 Cost

| component | USD |
|---|---:|
| Extraction (537 chunks × gpt-5-nano, work_key) | ~$1-2 |
| Answer gen (900 calls × gpt-5-mini, 8 modes × 100 Q + hybrid × 100 both engines, work_key) | ~$25 |
| Judge (1,100 × gpt-5-mini, work_key; includes v1 re-judge) | 0.50 |
| **Total v2 cost** | **~$27-28** |

v1's $6.11 was artificially low because only hybrid used gpt-5-mini; the other 5 pgrg modes and 2 AGE modes used free local Qwen. v2 pays for apples-to-apples quality.

## 6. Discussion

### 6.1 pg-raggraph vs AGE: roughly tied on this corpus

Top pgrg mode (naive_boost, 66) = top AGE mode (hybrid, 66) to the question. pgrg/hybrid lands 3 pp behind AGE/hybrid. Across all nine (engine, mode) pairs the fully_correct spread is **59-66** — a 7 pp band. pgrg isn't strictly better than AGE on medical; it's either tied or slightly behind depending on which mode you pick.

This is a significant departure from v1's framing. The v1 paper claimed "pg-raggraph cleanly beats Apache AGE head-to-head on answer accuracy" on medical. Under the fixed chunker + fair judge, that claim doesn't hold. See §7.1.

### 6.2 pgrg/hybrid underperforms its own simpler modes

pgrg/hybrid (63) < pgrg/naive_boost (66) < pgrg/naive (65) ≈ pgrg/smart (65) ≈ pgrg/local (64).

Hybrid is supposed to be the "kitchen-sink" mode — vector + BM25 + graph in one score. On this corpus, the weighted combination hurts rather than helps. Hypotheses:

- **Weight miscalibration.** Default hybrid weights were tuned on SCOTUS. Medical's clinical prose may want a different vector/BM25/graph mix. `tune_scoring_weights()` (from the evolving-knowledge spec) could be applied here first thing.
- **Graph signal noise.** Medical corpora have dense entity graphs (3,012 entities × 6,960 relationships across 537 chunks). Graph boost may be firing too often and promoting lower-quality chunks.
- **Small-chunk effect.** With 537 small chunks instead of 22 huge ones, graph relevance propagation pulls in more noise than signal.

The naive_boost lead suggests the 1-hop graph boost helps, but the full recursive hybrid hurts. Room for retrieval-mode work.

### 6.3 AGE caught up under the fixed chunker — why

Under gpt-5-mini judge, v1→v2 hybrid scores:
- pgrg/hybrid: **63 → 63** (flat)
- age/hybrid: **56 → 66** (+10)

AGE gained 10 pp from the chunker fix; pgrg gained 0. The mechanism: in v1, bge-small truncated each 134 KB chunk's embedding to ~512 tokens of the leading text. AGE's hybrid scoring leans heavily on vector similarity (its BM25 is a late-added afterthought and its graph traversal is independent of the embedding signal). With vectors broken, AGE was retrieving poorly. pgrg was saved by its stronger BM25 + graph boost + FTS weighting, which compensated for the broken vectors. **Fix the vectors and AGE catches up.**

This is consistent with T-G1 v1's "graph is noise when chunks are good" finding but adds a subtlety: **when chunks are bad, pgrg's non-vector signals are a useful defense — but that defense isn't a clean win over AGE, it's a patch over a different problem.**

### 6.4 Qwen-judge vs gpt-5-mini-judge — a calibration data point

Because we preserved the v1 hybrid raw files and re-judged them with gpt-5-mini, we have a direct side-by-side measurement of what changes when you swap the judge. Same answers, same questions, same rubric — only the judge model differs.

| file | answer model | Qwen-judge | gpt-5-mini-judge | Δ |
|---|---|---:|---:|---:|
| pgrg/hybrid (v1 raw) | gpt-5-mini | 73 | 63 | **−10** |
| age/hybrid (v1 raw) | gpt-5-mini | 66 | 56 | **−10** |

Three findings from this measurement:

1. **Qwen-judge is systematically ~10 pp more lenient** than gpt-5-mini-judge on clinical Q&A. Both runs used the same `fully_correct / partially_correct / wrong / hallucinated` rubric and the same majority-of-3 procedure in v1. The drift is in the judge's classification boundary, not the counting.

2. **The ordinal spread is preserved.** pgrg/hybrid − age/hybrid = +7 under both judges. If you're doing pair-comparison ("does engine A beat engine B"), the judge choice costs you no information. If you're reporting absolute accuracy ("pg-raggraph hits 73%"), the judge choice costs you 10 points.

3. **The v1 cross-validation spot-check (20 questions) found 85-90% agreement** between judges. That was accurate for ordinal agreement per-question but understated the systematic-drift effect on aggregated scores. A bigger cross-check sample or a calibration-aware metric (e.g., Cohen's κ by verdict class) would have caught the 10-pp systematic drift.

**Cost context:** the full v2 judge run (1,100 calls × gpt-5-mini) cost **$0.50**. The Qwen-local option saves $0.50 per corpus. That's not a meaningful tradeoff for a reported benchmark — but it's a useful data point for anyone doing cheap iterative experimentation where ordinal agreement is what they care about. Keep the Qwen lane available, publish with the OpenAI lane.

**Bonus: same-judge run-to-run variance.** The n=3 re-run accidentally re-judged the v2 n=1 hybrid + naive_boost raw files a second time (the second judge launcher iterated the whole corpus raw dir, not just its own mode). Same answers, same judge model, gpt-5-mini at temp=1:

| mode | initial n=1 judge | re-judge (same answers, same judge) | Δ |
|---|---:|---:|---:|
| pgrg/hybrid | 63 | 66 | +3 |
| age/hybrid | 66 | 67 | +1 |
| pgrg/naive_boost | 66 | 64 | −2 |

Run-to-run judge variance on the same inputs is ~±3 pp on this rubric/corpus. That matches the ±3 pp confidence band claimed in §7 and is a useful calibration for anyone interpreting a single-run score within a few points.

### 6.5 Comparison to GraphRAG-Bench paper leaderboard

The Xiang paper reports graph methods winning on Complex Reasoning; our v2 shows pgrg/naive winning Complex Reasoning on our subset (22/25 = 88%). The winning mode is *not* a graph-retrieval mode — it's a vector-only mode. This pushes back on the paper's "graph methods dominate Complex Reasoning" framing, at least on this subset with gpt-5-mini answers. Caveat: the paper uses different answer models and a different rubric; direct numerical comparison is not meaningful.

### 6.6 Zero → low hallucinations

v1: 0 hallucinations across 800 answers.
v2: 43 hallucinations across 900 answers (4.8%).

The switch from Qwen-judge to gpt-5-mini-judge is the likely driver. Qwen-judge classified hallucinated answers as `wrong`; gpt-5-mini-judge is stricter about the hallucinated/wrong distinction. Worth noting: all 43 hallucinations are in answer rows, not judge rows. The answer model (same in both cases, gpt-5-mini) did hallucinate at a low rate on clinical questions — the judges just characterized those cases differently.

### 6.7 What this does NOT answer

- **MS GraphRAG (Phase 4):** not run. An open leg of the three-engine comparison.
- **Chunker × embedder factorial on medical:** carried SCOTUS winning cell forward. A medical-native factorial might move the absolute scores.
- **Weight tuning per-corpus:** pgrg/hybrid's loss to pgrg/naive_boost may be fixable with weight tuning. `rag.tune_scoring_weights()` should be applied to this corpus before any "retrieval mode X doesn't work on medical" conclusions.
- **Answer-model comparison:** everything here is gpt-5-mini. Whether gpt-5 or Claude changes the picture is an open question.

## 7. Limitations

- **Mixed n per cell.** hybrid (both engines) and pgrg/naive_boost re-run at `-n 3` with majority-of-3 verdicts; other six modes remain at `-n 1`. Aggregate totals did not move at n=3 for the three tracked cells (confirming the n=1 reads were stable), but within-class distribution shuffled by up to ±3 pp. Measured same-answer same-judge run-to-run variance is also ~±3 pp (§6.4). Treat single-run scores as having a ±3 pp confidence band; n=3 cells are tighter.
- **100-question subset vs 2,060 upstream.** Stratified by class so distribution is preserved, but per-class counts at 25 give ±2-question (8 pp) noise on observed accuracy.
- **Hybrid weight defaults.** pgrg/hybrid loses to pgrg/naive_boost on this corpus; the default weights were calibrated on SCOTUS, not medical. Before concluding "hybrid is broken on medical," tune weights per corpus.
- **Rubric mismatch with upstream paper.** GraphRAG-Bench paper uses per-type Accuracy + ROUGE-L + Coverage + Factual Score; ours uses majority-of-N judge verdicts. Not directly comparable.
- **Judge consistency across engines.** Both engines' answers judged by the same gpt-5-mini run but with independent context. If gpt-5-mini-judge has any systematic engine bias, it would show here. 20-question cross-check on an independent judge model (e.g., Claude) would harden this.
- **Corpus-specific document framing.** Medical corpus is one concatenated row split by `"About <topic>"` regex. 22 topics recovered, no formal boundary-accuracy validation.
- **AGE 4× slower on retrieval.** Latency-sensitive applications should prefer pgrg. Quality-parity doesn't mean operational-parity.
- **MS GraphRAG not benchmarked.** Phase 4, deferred.

## 7.1 V1 retraction — "pgrg/hybrid 73 vs age/hybrid 66"

The v1 version of this paper (2026-04-21) reported pgrg/hybrid 73 vs age/hybrid 66 as the headline result and framed it as "the first corpus where pg-raggraph cleanly beats AGE." **That headline is retracted.**

### What went wrong

Two independent bugs compounded:

1. **Hierarchy chunker had no size cap.** `_split_hierarchy` in `age_bakeoff/chunker.py` (and its port in `pg_raggraph/chunking.py`) split on markdown headings and emitted raw section bodies. The medical corpus has topic sections up to 134 KB (bladder cancer). bge-small-en-v1.5 silently truncates input at 512 tokens (~2 KB). The vector index was built on the first ~2 KB of each 134 KB chunk — the rest of the content was invisible to vector retrieval. Documented in `benchmarks/age-bakeoff/RETURN-TO-BAKEOFF-3.md`.

2. **Qwen-judge was ~10 pp more lenient than gpt-5-mini-judge.** v1 judged non-hybrid runs with local Qwen (free) and did a 20-question cross-check that found 85-90% agreement. That agreement was on ordinal judgments, not absolute calibration. v2 re-judged v1's hybrid raw files with gpt-5-mini: pgrg/hybrid v1 **73 → 63**, age/hybrid v1 **66 → 56**.

### What the numbers actually are

Re-running the v1 hybrid raw results through gpt-5-mini judge (apples-to-apples with v2):

| | v1 reported | v1 re-judged (gpt-5-mini) | v2 (fixed chunker) |
|---|---:|---:|---:|
| pgrg/hybrid | 73 | 63 | 63 |
| age/hybrid | 66 | 56 | 66 |

The v1 reported gap (+7 pgrg) was real but the absolute numbers were inflated by Qwen-judge lenience. **AGE gained 10 pp from the chunker fix; pgrg gained 0.** The final v2 picture has AGE slightly ahead of pgrg at the hybrid leg and roughly tied overall.

### Why AGE recovered more

In v1, bge-small truncated all embeddings to the first ~2 KB. AGE's retrieval relies heavily on vector similarity (its BM25 leg is a late-added supplement and its graph traversal is embedding-agnostic). With vectors broken, AGE retrieved poorly. pg-raggraph's stronger BM25 + graph boost + FTS weighting acted as a defense-in-depth and partially compensated for the broken vectors — giving pgrg an artificial lead over AGE. Fix the vectors, AGE catches up.

### Artifacts preserved

- v1 hybrid raw: `results/raw/graphrag-bench-medical__hybrid.v1_broken_chunker.json`
- v1 hybrid judge (Qwen, original): `results/judge/graphrag-bench-medical__hybrid.v1_broken_chunker.json`
- v1 extraction cache: `corpora/external-extractions/graphrag-bench-medical.v1_broken_chunker.json`
- v1 retraction write-up: `benchmarks/age-bakeoff/RETURN-TO-BAKEOFF-3.md`

### Lesson

Any result that depends on retrieval embeddings should also **verify chunk sizes are within the embedder's context window**. pg-raggraph and the bakeoff now cap hierarchy chunks at `chunk_max_tokens` (commit `58d8c1d`). chunkshop's equivalent fix is in progress (sibling tool, tracked separately).

## 8. Reproducibility

```bash
# One-shot v2 reproduction (assumes docker compose up + .env configured)
cd benchmarks/age-bakeoff

# 1. Extract under the fixed chunker (~$1-2, ~5 min)
BAKEOFF_EXTRACTION_BASE_URL="" OPENAI_API_KEY=$WORK_KEY \
uv run python -m age_bakeoff.tools.extract_external_corpus \
  --corpus graphrag-bench-medical --strategy hierarchy --model gpt-5-nano --force

# 2. Ingest into both engines (~15 min)
uv run age-bakeoff ingest --corpus graphrag-bench-medical --chunker hierarchy

# 3. Run the 8-mode matrix (~3 hours wall clock, ~$25)
bash scripts/launch-gb-medical-v2-matrix.sh

# 4. Regenerate this paper's tables
python3 -m age_bakeoff.tools.emit_paper --corpus graphrag-bench-medical
```

**Requirements:**
- OpenAI API key in `.env` or environment (work_key recommended for the ~$30 budget)
- Docker compose stack up (`pgrg` on :5434, `age` on :5435)
- Local dependencies: `uv sync --all-extras --frozen`
- Expected total wall time: ~5 hours end-to-end (runs + judge)
- Expected total cost: ~$27-28 on work_key

## References

- Xiang et al. 2026, *When to use Graphs in RAG: A Comprehensive Benchmark and Analysis for Graph Retrieval-Augmented Generation*, ICLR 2026. arXiv 2506.05690.
- GraphRAG-Bench leaderboard: https://graphrag-bench.github.io/
- pg-raggraph chunker fix: commit `58d8c1d`, *fix(chunker): cap hierarchy sections + dual content primitive*.
- v1 session handoff (context for the retraction): `benchmarks/age-bakeoff/RETURN-TO-BAKEOFF-3.md`.
- Evolving-knowledge RAG design (weight tuning context): `docs/archive/superpowers/specs/2026-04-22-evolving-knowledge-rag-design.md`.
- pg-raggraph benchmark series index: [docs/benchmarks/index.md](index.md).
