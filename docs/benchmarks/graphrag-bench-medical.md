# Benchmark: GraphRAG-Bench — Medical

**Corpus:** `graphrag-bench-medical`
**Status:** draft (awaiting run completion)
**Run date:** 2026-04-21
**Raw results:** `benchmarks/age-bakeoff/results/raw/graphrag-bench-medical*.json`
**Judge results:** `benchmarks/age-bakeoff/results/judge/graphrag-bench-medical*.json`
**Reproduced by:** `CORPUS_ID=graphrag-bench-medical ./scripts/bench-corpus.sh`

---

## TL;DR

_Filled once the run completes._ Headline question: do graph retrieval modes earn their keep on a medical corpus designed specifically to test multi-hop reasoning and complex question types?

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

_Populated once judge completes._

### 5.1 Overall accuracy

| engine | mode | fully_correct | partially | wrong | hallucinated |
|---|---|---|---|---|---|
| pgrg | naive | | | | |
| pgrg | naive_boost | | | | |
| pgrg | local | | | | |
| pgrg | global | | | | |
| pgrg | hybrid | | | | |
| pgrg | smart | | | | |
| age | hybrid | | | | |
| age | local | | | | |
| age | global | | | | |
| msgraph | basic | _phase 4_ | | | |
| msgraph | local | _phase 4_ | | | |
| msgraph | global | _phase 4_ | | | |
| msgraph | drift | _phase 4_ | | | |

### 5.2 By question class

One row per class, columns per engine × mode, fully_correct counts.

### 5.3 Latency

| engine | mode | p50 ms | p95 ms | mean ms |
|---|---|---|---|---|

### 5.4 Cost

| engine | ingest USD | answer USD | judge USD | total USD |
|---|---|---|---|---|

## 6. Discussion

_To be written against actual numbers._ Key questions this paper must answer:

- Does pgrg's graph layer add signal on Complex Reasoning and Creative Generation here (where it didn't on SCOTUS)?
- Does MS GraphRAG beat both pgrg and AGE on the corpus its authors would expect it to win on?
- Does the per-question-class breakdown match or contradict the GraphRAG-Bench paper's leaderboard claim that graph methods dominate Complex Reasoning?

## 7. Limitations

- **Rubric mismatch with upstream:** the GraphRAG-Bench paper scores on per-type Accuracy + ROUGE-L + Coverage + Factual Score; ours uses the majority-of-3 judge-verdict rubric. Results not directly comparable to their leaderboard.
- **100-question subset vs 2,060 upstream:** stratified by class so the distribution is preserved, but variance per class is higher than a full-set run would show. Per-class counts at 25 give ±2-question noise (~8 pp) on observed accuracy.
- **Corpus-specific document framing:** medical is one concatenated row split by regex. If the regex misses a boundary, that topic merges into its neighbor; if it over-splits, a document gets fragmented. Manual inspection at load time showed 22 titled documents with sensible boundaries, but no formal boundary-accuracy validation.
- **MS GraphRAG uses different chunker + embedder.** Chunk-for-chunk comparability to pgrg/AGE is impossible. End-to-end accuracy still compares.
- **Chunker × embedder factorial not run on this corpus.** Winning cell from SCOTUS (hierarchy + bge-small-int8) carried forward as informed default. Follow-up: run the factorial on medical if mode-matrix results suggest the chunker choice is load-bearing.

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
