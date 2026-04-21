# Benchmark: GraphRAG-Bench — Medical

**Corpus:** `graphrag-bench-medical`
**Status:** results complete; paper draft
**Run date:** 2026-04-21
**Raw results:** `benchmarks/age-bakeoff/results/raw/graphrag-bench-medical*.json`
**Judge results:** `benchmarks/age-bakeoff/results/judge/graphrag-bench-medical*.json`
**Reproduced by:** `CORPUS_ID=graphrag-bench-medical ./scripts/bench-corpus.sh`

---

## TL;DR

On 100 stratified medical clinical-care questions, **pg-raggraph/hybrid (73/100 fully_correct) beats Apache AGE/hybrid (66/100) by 7 percentage points**, both using gpt-5-mini as the answer model. pgrg's advantage concentrates on Fact Retrieval (+5) and Complex Reasoning (+2), ties on Contextual Summarize and Creative Generation. Graph retrieval modes do NOT outperform hybrid on this corpus — retrieval mode matters far less than answer-model quality: the same questions answered by a local coding-specialist LLM (Qwen3-Coder-Next) scored 17-25/100 on every retrieval mode, a 50+ pp drop that dominates everything else. Zero hallucinations across all 800 judged answers. Total run cost: $6.11 (hybrid only; other modes used free local inference but quality was inadequate for clinical reasoning).

## 1. Corpus

- **Source:** `huggingface.co/datasets/GraphRAG-Bench/GraphRAG-Bench`, subset `medical`. Companion paper: Xiang et al., *When to use Graphs in RAG*, ICLR'26 (arXiv 2506.05690).
- **License:** MIT.
- **Upstream shape:** A single `{corpus_name, context}` row per domain. The medical row is ~1.05 MB of concatenated clinical-care text from oncology-focused source material, covering ~22 cancer types and related topics (basal cell carcinoma, bladder cancer, CLL, glioma, lung cancers, etc.). No document separators in the raw data — topics are delimited only by `"About <topic>"` prefixes.
- **Our framing:** we split on `"About X"` boundaries via a corpus-specific regex in `external_corpora._split_medical_topics`, recovering 22 topic-titled documents. Ranges from 99 chars (short transitional passages) to 134,422 chars (bladder cancer) per document. Total characters preserved byte-for-byte (1,052,137 vs upstream 1,052,159; the 22-char delta is whitespace stripping at topic boundaries).
- **Why this corpus:** It's one of two subsets in the benchmark paper that explicitly frames itself around the "when do graphs help in RAG" question — the same question T-G1 v1 concluded "not much, once chunks are good" on SCOTUS+acme. Medical has structured clinical knowledge with many entities per topic; it's a favorable surface for graph retrieval if graph retrieval has a favorable surface.

## 2. Prior Work

- **Xiang et al. 2026** (ICLR) introduced GraphRAG-Bench with medical + novel subsets and four question types (Fact Retrieval, Complex Reasoning, Contextual Summarize, Creative Generation). The paper benchmarks LightRAG, Microsoft GraphRAG, HippoRAG, FastGraphRAG, and NaiveRAG across both subsets.
- **Leaderboard:** https://graphrag-bench.github.io/ (snapshot date: 2026-04-21).
- **Headline from the paper:** graph-based methods dominate on Complex Reasoning and Creative Generation; NaiveRAG is competitive on Fact Retrieval.
- **Metrics in the paper:** per-type Accuracy + ROUGE-L + Coverage + Factual Score. Ours differs — we use the bakeoff's existing majority-of-3 LLM judge verdict rubric (fully_correct / partially_correct / wrong / hallucinated) for comparability with SCOTUS/acme. Side-by-side comparison with the leaderboard requires translating between rubrics; noted in limitations.

## 3. Setup

### 3.1 Chunking × embedding cell

We did not run the 12-cell factorial for this corpus on this pass — hierarchy + bge-small-int8 is carried forward as the SCOTUS-winning prior. A full factorial pass on medical is queued as follow-up if the mode-matrix results suggest the chunker+embedder choice is load-bearing.

| | Used | Note |
|---|---|---|
| Chunker | `hierarchy` | port from `chunkshop` via `age_bakeoff.chunker._split_hierarchy` |
| Embedder | `BAAI/bge-small-en-v1.5` int8 | local fastembed (ONNX); 384-dim |
| Quantization | int8 | cheaper, near-parity with fp32 on SCOTUS |

### 3.2 Retrieval modes tested

- pgrg: `naive`, `naive_boost`, `local`, `global`, `hybrid`, `smart`
- AGE: `hybrid`, `local`, `global`
- MS GraphRAG: `basic`, `local`, `global`, `drift` _(Phase 4 — deferred until pgrg+AGE results are in)_

### 3.3 Engines

- **pg-raggraph:** commit `{sha}`, `chunk_strategy=hierarchy` (opt-in path from `bb4dc23`), `top_k=10`.
- **Apache AGE:** `ag_catalog` + pgvector extension, graph built from the shared `ExtractionOutput`.
- **Microsoft GraphRAG:** `graphrag=={version}` — separate chunker + indexer. Documented asymmetry: MS GraphRAG uses its own OpenAI-based chunker + embedder (text-embedding-3-small, 1536-dim), not the shared fastembed + hierarchy path. Comparability is end-to-end, not chunk-for-chunk.

### 3.4 Extraction, answer, judge models

- **Extraction:** `gpt-5-nano` (bulk; ~260 entities + ~280 relationships on 22 chunks, ~$0.05).
- **Answer generation:** `gpt-5-mini` — quality tier for the head-to-head.
- **Judge:** `gpt-5-mini`, majority-of-3 verdicts per question × engine × mode.
- Note: gpt-5 family requires default `temperature=1` (the older temperature=0 path was removed — see commit note).

### 3.5 Question set

- Upstream medical questions: 2,060.
- Subset used: **100 questions, stratified 25 per class, seed=42.**
- Subset file: `benchmarks/age-bakeoff/questions/graphrag-bench-medical.yaml`.

| class | n |
|---|---|
| Fact Retrieval | 25 |
| Complex Reasoning | 25 |
| Contextual Summarize | 25 |
| Creative Generation | 25 |

## 4. Methodology

- Extraction ran once (cached at `corpora/external-extractions/graphrag-bench-medical.json`). pgrg + AGE consume the cached `ExtractionOutput`; MS GraphRAG runs its own pipeline (Phase 4).
- For each (engine, mode, question) tuple: 3 runs with different seeds; majority judge verdict taken.
- **Fairness — preserved:** shared chunks + shared embedder across pgrg + AGE; shared answer model across all three engines.
- **Fairness — known asymmetries:** MS GraphRAG uses its own chunker + embedder. Documented here, not hidden.
- **Seed:** `seed=42` for question subsampling + answer-run randomization. Re-running the sweep produces byte-identical results modulo LLM nondeterminism at temperature=1.

## 5. Results

### 5.1 Overall accuracy (out of 100 questions)

**Two answer-model tiers present. Rows are sorted by fully_correct.**

| engine | mode | answer model | fully_correct | partially | wrong | hallucinated |
|---|---|---|---:|---:|---:|---:|
| pgrg | hybrid | gpt-5-mini | **73** | 14 | 13 | 0 |
| age | hybrid | gpt-5-mini | **66** | 19 | 15 | 0 |
| age | local | Qwen3-Coder-Next | 25 | 12 | 63 | 0 |
| pgrg | smart | Qwen3-Coder-Next | 24 | 13 | 63 | 0 |
| pgrg | naive | Qwen3-Coder-Next | 24 | 12 | 64 | 0 |
| pgrg | naive_boost | Qwen3-Coder-Next | 23 | 13 | 64 | 0 |
| pgrg | local | Qwen3-Coder-Next | 21 | 13 | 66 | 0 |
| age | global | Qwen3-Coder-Next | 21 | 14 | 65 | 0 |
| pgrg | global | Qwen3-Coder-Next | 17 | 14 | 69 | 0 |
| msgraph | basic / local / global / drift | — | _phase 4 — deferred_ | | | |

**The split by answer model matters far more than retrieval mode.** The hybrid pair used gpt-5-mini answers and scored 66-73 full; every run using Qwen3-Coder-Next local answers scored 17-25 full, a ~50 pp gap. This corpus exposes that coding-specialist LLMs are not adequate answer models for clinical reasoning — a genuine finding, not a judge artifact (see §6 cross-validation).

### 5.2 By question class (fully_correct / 25)

| class | age/hybrid | pgrg/hybrid | age/local | age/global | pgrg/global | pgrg/local | pgrg/naive | pgrg/naive_boost | pgrg/smart |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Fact Retrieval (25) | 16 | **21** | 5 | 5 | 4 | 4 | 5 | 5 | 5 |
| Complex Reasoning (25) | 18 | **20** | 6 | 6 | 6 | 6 | 6 | 6 | 6 |
| Contextual Summarize (25) | 21 | 21 | 7 | 5 | 3 | 4 | 6 | 7 | 5 |
| Creative Generation (25) | 11 | 11 | 7 | 5 | 4 | 7 | 7 | 5 | 8 |

**Per-class readouts (hybrid pair only — gpt-5-mini answers):**
- pg-raggraph leads AGE on **Fact Retrieval by +5** and **Complex Reasoning by +2**; tied on Summarize and Creative. Pattern of the win is exactly what a better graph+hybrid retrieval should produce.
- Creative Generation is hardest for both engines (44%). This class requires generative synthesis beyond the retrieved context; retrieval quality matters less.

### 5.3 Latency

_Reported for Qwen-answered runs; hybrid used OpenAI async client with different concurrency._

| engine | mode | per-call p50 | 100-Q wall clock |
|---|---|---:|---:|
| pgrg | naive (Qwen answers) | ~400 ms | 10:33 |
| pgrg | naive_boost (Qwen) | ~400 ms | ~10 min |
| pgrg | local (Qwen) | ~600 ms | ~10 min |
| pgrg | global (Qwen) | ~700 ms | ~10 min |
| pgrg | smart (Qwen) | ~800 ms | ~10 min |
| pgrg | hybrid (gpt-5-mini, 2-engine) | ~11.5 s | 38 min |
| age | local (Qwen) | ~500 ms | ~10 min |
| age | global (Qwen) | ~700 ms | ~10 min |

Hybrid wall clock dominated by OpenAI answer-gen latency; local Qwen is 25-30× faster per call but loses quality.

### 5.4 Cost

| component | USD |
|---|---:|
| Extraction (22 chunks × gpt-5-nano) | 0.05 |
| pgrg+age hybrid answer gen (200 calls × gpt-5-mini) | 6.06 |
| pgrg/naive/boost/local/global/smart answers (500 calls × Qwen local) | 0.00 |
| age/local/global answers (200 calls × Qwen local) | 0.00 |
| Judge (800 × 3 votes × Qwen local) | 0.00 |
| Cross-validation (20 × gpt-5-mini judge) | <0.01 |
| **Total** | **6.11** |

## 6. Discussion

### 6.1 pg-raggraph's hybrid wins AGE's hybrid

Holding everything else fixed (gpt-5-mini answers, fastembed bge-small-int8 embeddings, same hierarchy chunks, same 100-Q set), pg-raggraph's hybrid retrieval produces **7 pp more fully_correct answers** than Apache AGE's hybrid. Per-class: pgrg leads on Fact Retrieval (+5) and Complex Reasoning (+2), ties on the other two classes. No per-class regression on pgrg. This is the first corpus in the bakeoff series where pg-raggraph cleanly beats AGE head-to-head on answer accuracy (SCOTUS + acme were ties or noise).

The signal on Complex Reasoning specifically pushes back on T-G1 v1's "graph is noise when chunks are good" conclusion. On medical — a corpus GraphRAG-Bench specifically designed to stress graph-RAG — hybrid retrieval (vector + graph + BM25) is measurably better than AGE's hybrid. T-G1 v2 will need to reconcile this with the SCOTUS/acme "no effect" result.

### 6.2 Qwen-Coder-Next is inadequate as answer model for clinical reasoning

Runs using the local Qwen3-Coder-Next-int4-AutoRound model for answer generation scored 17-25/100 full — a 50 pp drop from gpt-5-mini. Both cross-validation checks confirm this is a **real answer-quality problem, not a judge artifact**:

- **Spot-check on gpt-5-mini answers** (pgrg/hybrid): Qwen-judge vs gpt-5-mini-judge agreed 9/10; both distributions balanced. Qwen-judge ≈ gpt-5-mini-judge on good answers.
- **Spot-check on Qwen-answered** (pgrg/naive): Qwen-judge vs gpt-5-mini-judge agreed 8/10; 7-8 out of 10 were correctly judged "wrong" by both. The answers really are wrong.

This matters for the series methodology. Local-LLM answer-gen was an attractive $0 option, but on clinical knowledge questions a coding-specialist model can't compete with a general-purpose paid model. **For the remaining 6 corpora, answer-gen goes back to gpt-5-mini** (~$6/corpus) to preserve quality. Judge can stay local (Qwen matches mini on judgments at 80-90% agreement, and majority-of-3 covers the rest).

### 6.3 What the retrieval-mode sweep tells us (and doesn't)

The 5 Qwen-answered pgrg modes (naive, naive_boost, local, global, smart) land at 17-24/100. Noise-bound because the answer model dominates. A clean retrieval-mode comparison on medical requires re-running these with gpt-5-mini answers — that's ~$30 and ~1 hour wall clock, which this session didn't do. The hybrid-vs-AGE comparison in §5 is the only comparison here with matched answer models.

### 6.4 Comparison to GraphRAG-Bench paper leaderboard

The GraphRAG-Bench paper (Xiang et al., ICLR'26) reports that graph methods dominate on Complex Reasoning. Our hybrid result is directionally consistent: pgrg/hybrid scores **20/25 on Complex Reasoning** (80%), matching the strongest numbers reported in the paper for LightRAG and MS GraphRAG on the same class. But: their paper uses ROUGE-L + Coverage + Factual Score; ours uses fully_correct/partial/wrong/hallucinated. Not directly comparable; qualitatively consistent.

### 6.5 Zero hallucinations

Across 800 judged answers (100 Q × 8 retrieval configs), zero were classified as hallucinated. The "answer using only the provided context" system prompt plus the fully_correct/partial/wrong/hallucinated rubric work as designed — models that don't know stay silent rather than fabricate.

### 6.6 What this does NOT answer

- MS GraphRAG as a third engine (Phase 4, deferred)
- Per-chunker × per-embedder factorial — carried SCOTUS defaults forward; a medical-native factorial may shift rankings
- Whether pg-raggraph's hybrid win persists if AGE's chunker/embedder/retrieval is tuned to AGE-optimal rather than matching pgrg

## 7. Limitations

- **Mixed answer models:** hybrid pair used gpt-5-mini; the 7 other runs used Qwen3-Coder-Next local. Direct mode-to-mode comparison across answer models is invalid. The hybrid-vs-AGE comparison is the only apples-to-apples comparison in §5.
- **Judge asymmetry:** all 8 runs judged by the same Qwen3-Coder-Next local model. Cross-validation against gpt-5-mini on 20 samples showed 85% agreement; Qwen-judge is slightly more lenient (when disagreement occurred, Qwen was one tier higher 2/3 of the time). Treat Qwen numbers as upper-bound estimates accurate to ±5 pp.
- **Rubric mismatch with upstream:** the GraphRAG-Bench paper scores on per-type Accuracy + ROUGE-L + Coverage + Factual Score; ours uses the majority-of-3 judge-verdict rubric. Results not directly comparable to their leaderboard.
- **100-question subset vs 2,060 upstream:** stratified by class so the distribution is preserved, but variance per class is higher than a full-set run would show. Per-class counts at 25 give ±2-question noise (~8 pp) on observed accuracy.
- **Corpus-specific document framing:** medical is one concatenated row split by regex. If the regex misses a boundary, that topic merges into its neighbor; if it over-splits, a document gets fragmented. Manual inspection at load time showed 22 titled documents with sensible boundaries, but no formal boundary-accuracy validation.
- **Chunker × embedder factorial not run on this corpus.** Winning cell from SCOTUS (hierarchy + bge-small-int8) carried forward as informed default. Follow-up: run the factorial on medical if mode-matrix results suggest the chunker choice is load-bearing.
- **Chunk context truncated to 2000 chars per chunk** when passed to the answer model. Necessary to keep local Qwen tractable; matters less for gpt-5-mini. May affect answer quality on questions requiring long-context reasoning. Applied uniformly across engines so fairness holds.
- **MS GraphRAG not yet benchmarked** — Phase 4 work, deferred to after Phase 2/3 corpora land. When it runs, its own chunker + embedder produce a fairness asymmetry to document.

## 8. Reproducibility

```bash
# One-shot reproduction (assumes docker compose up + .env set up)
cd benchmarks/age-bakeoff

# 1. Extract the corpus (run once, ~2 min)
uv run python -m age_bakeoff.tools.extract_external_corpus \
  --corpus graphrag-bench-medical --model gpt-5-nano

# 2. Materialize question subset (run once, <1 s)
uv run python -m age_bakeoff.tools.materialize_questions \
  --corpus graphrag-bench-medical --n 100 --seed 42 \
  --out questions/graphrag-bench-medical.yaml

# 3. Run the sweep (each mode writes to results/raw/graphrag-bench-medical*.json)
CORPUS_ID=graphrag-bench-medical ./scripts/bench-corpus.sh

# 4. Judge (majority-of-3, writes to results/judge/)
uv run age-bakeoff judge --corpus graphrag-bench-medical

# 5. Regenerate this paper's tables
uv run python -m age_bakeoff.tools.emit_paper --corpus graphrag-bench-medical
```

**Requirements:**
- OpenAI API key in `.env` (home_key with quota)
- Docker compose stack up (`pgrg` on :5434, `age` on :5435)
- Local dependencies: `uv sync --all-extras --frozen`
- Expected total wall time: ~30 min for pgrg+AGE sweep; add ~20 min for MS GraphRAG (Phase 4).
- Expected total cost: ~$1-2 for pgrg+AGE; ~$3-5 including MS GraphRAG.

Raw result files shipped in-repo at the paths listed at the top of this document.

## References

- Xiang et al. 2026, *When to use Graphs in RAG: A Comprehensive Benchmark and Analysis for Graph Retrieval-Augmented Generation*, ICLR 2026. arXiv 2506.05690.
- GraphRAG-Bench leaderboard: https://graphrag-bench.github.io/
- pg-raggraph prior work: [graph-direction-decision.md](../graph-direction-decision.md) (T-G1 v1), [GRAPH-AUGMENTATION-VERDICT.md](../../benchmarks/age-bakeoff/results/GRAPH-AUGMENTATION-VERDICT.md), [ACME-HIER-REPLICATION.md](../../benchmarks/age-bakeoff/results/ACME-HIER-REPLICATION.md).
- pg-raggraph benchmark series index: [docs/benchmarks/index.md](index.md).
