# pg-raggraph Benchmark Strategy

This repo needs two benchmark products with different jobs:

1. **Showcase benchmarks**: small, polished, easy to rerun, easy to explain. These are for demos, launch notes, and "why this matters" comparisons.
2. **Matrix benchmarks**: broad, repeatable, audit-heavy sweeps for regressions, best practices, and configuration guidance.

Do not mix these. A showcase run should never become a 300-cell research grid, and the matrix harness should not optimize for a marketing table.

## Benchmark Layers

### 1. Showcase

Purpose:

- Produce a short, defensible "wow" comparison.
- Explain the story in one table.
- Keep runs cheap enough to repeat before publishing.

Current examples:

- `benchmarks/showcase/sweep.py`
- `benchmarks/showcase/experiments.py`
- `benchmarks/showcase/grounding.py`

Expected output:

- One summary table.
- A small committed result set.
- Clear caveats about dataset size, judge, and context budget.

Showcase should use selected best-known configurations, not exhaustive search.

### 2. Matrix / Beast Harness

Purpose:

- Find regressions.
- Discover workload-specific best practices.
- Compare costs and accuracy across a large configuration matrix.
- Produce per-case audits so failures are inspectable.

This harness should be configuration-driven and resumable. It should write every intermediate artifact needed to answer: "Why did this cell win or fail?"

Recommended package location:

- `benchmarks/matrix/`

## Required Baselines

Every workload should have at least two baselines before testing variants.

### Baseline A: Full-Document Oracle

Question:

> If we send the complete relevant document set to the answer model, what answer does it produce, how many tokens does it cost, and does it match the gold/reference answer?

Procedure:

1. Retrieve candidate documents semantically from chunks.
2. Attach one or more full source documents to the prompt.
3. Generate an answer.
4. Judge against gold when available.
5. If no gold exists, generate and adjudicate a synthetic reference.

Record:

- selected document IDs
- full document token count
- prompt/completion tokens
- answer latency
- answer text
- judge verdict/rationale
- whether the full-document context exceeded model limits

This is the expensive upper-context baseline. It is not always the accuracy ceiling, but it is the best "send the source" comparison.

### Baseline B: Classic RAG

Question:

> At the default chunk size and top-k, what does conventional retrieval plus raw chunks achieve?

Initial default:

- chunk size: 500-ish tokens
- overlap: 50 tokens
- top-k: 25

Sweep top-k separately:

- 10
- 25
- 50
- 100
- 250
- 500
- 1000, only for long-context stress runs

Record the same answer, judge, token, and timing fields as the full-document baseline.

Classic RAG is the operational baseline. Most experimental configurations should report deltas against both full-document and classic-RAG baselines.

## Matrix Axes

The matrix should be explicit and finite per run. Avoid hidden defaults.

### Corpus / Workload

Supported workload families:

- MHR
- MuSiQue
- 2Wiki
- HotpotQA
- LoCoMo
- RAGAS-style inputs
- LongBench
- LangBench
- SCOTUS
- pg-raggraph source/codebase corpus
- custom user corpora

Each workload definition should declare:

- corpus loader
- query loader
- gold answer source, if any
- required facts source, if any
- workload tags: single-hop, multi-hop, temporal, null-query, code, legal, conversational, long-context

### Embedding

Examples:

- `BAAI/bge-large-en-v1.5`
- `BAAI/bge-base-en-v1.5`
- `sentence-transformers/all-MiniLM-L6-v2`
- `nomic-embed-text`
- local OpenAI-compatible embedding endpoints

Each embedding cell must record:

- model name
- dimension
- provider/runtime
- normalization behavior, if relevant

### Chunking

Supported strategies:

- `auto`
- `hierarchy`
- `chunkshop:hierarchy`
- `chunkshop:sentence_aware`
- `chunkshop:semantic`
- `chunkshop:fixed_overlap`
- `chunkshop:neighbor_expand`

Chunking settings:

- target tokens/chars
- overlap
- title/heading prefix behavior
- embedded-content vs displayed-content behavior
- any summarization/neighbor expansion embedded into chunks

### Retrieval Operators

Vector operators:

- cosine
- inner product
- L2, when supported and meaningful

Search families:

- vector
- FTS/BM25
- hybrid vector + FTS
- predicate/metadata filtering
- soft metadata scoring
- graph-local
- graph-global
- graph-hybrid

pg-raggraph modes:

- `naive`
- `naive_boost`
- `local`
- `global`
- `hybrid`
- `smart`
- `summary`

Retrieval strategy:

- weighted
- pre-filter
- vector-first

### Context Assembly

The retrieval result and the context sent to the answer model should be separate concepts.

Context assembly strategies:

- full selected documents
- raw chunks
- document summary
- document summary + TOC
- document summary + TOC + extracted facts
- retrieved chunk summary
- document summary prepended to raw chunks
- document summary prepended to chunk summary
- facts only
- TOC + facts + chunk summary

### Derived Metadata Columns

For machine reports like `lede --mode report --output json`, store the complete
payload under a raw metadata key such as `metadata.lede_report`, then promote
repeat-query paths into generated columns:

- `metadata.lede_report.attributes.term.value` → `meta_term`
- `metadata.lede_report.attributes.docket_number.value` → `meta_docket_number`
- `metadata.lede_report.attributes.citation.value` → `meta_citation`
- workload-specific entities such as SCOTUS justice names, customer IDs, dates,
  products, repos, file paths, or version labels

The raw JSON stays available for audits, FTS enrichment, embeddings, and future
extractors. Generated columns give the benchmark a fair deterministic baseline
for predicate-style questions instead of forcing semantic retrieval to guess at
structured filters.

Each context strategy must record:

- source tokens considered
- context tokens sent
- compression ratio vs source
- delta vs classic RAG tokens
- delta vs full-document tokens

### Answer And Judge Models

Separate these roles:

- answer model
- reference-generation model, when no gold exists
- judge model(s)

The harness should support:

- quick mode for smoke tests
- accurate mode for final/disputed runs
- up to three judges for important sweeps
- cached prompts
- resume
- provider/runtime failures as `ERROR` rows, not aborted runs

Use `llm-judge` for answer generation and judging where possible.

## Gold And Synthetic References

Some workloads have benchmark gold answers. Some custom corpora do not.

When gold exists:

- preserve the original gold answer
- preserve aliases
- preserve required facts/supporting facts when available
- judge semantic correctness, not byte equality

When gold does not exist:

1. Run full-document answer generation multiple times, preferably with more than one model.
2. Cluster semantically equivalent answers.
3. Create a reference object with:
   - canonical answer
   - accepted aliases
   - required facts
   - optional acceptable specificity levels
   - rejected/conflicting answers
4. Store the reference beside the workload, not inside transient results.

Example:

Question: `Where was Matt Yonkovit born?`

Accepted answers may include:

- `Michigan`, if the question only asks broadly where.
- `Grand Rapids`, if city-level specificity is acceptable.
- `St. Mary's Hospital in Grand Rapids`, if the available source supports that detail.

Question: `What city and hospital was Matt Yonkovit born at?`

Required facts become:

- city: `Grand Rapids`
- hospital: `St. Mary's Hospital`

An answer with only `Michigan` is then incomplete.

## Metrics

Every cell should report:

- answer pass rate
- exact/substring score, only as a secondary diagnostic
- semantic judge score
- retrieval recall
- required-fact recall
- supported facts
- missing facts
- contradictions
- source tokens considered
- context tokens sent
- completion tokens
- total tokens
- token delta vs full-document baseline
- token delta vs classic-RAG baseline
- latency: retrieval, context assembly, answer generation, judging, total
- provider/runtime errors
- cost estimate when model pricing is configured

Recommended derived metrics:

- `accuracy_per_1k_tokens`
- `fact_recall_per_1k_tokens`
- `cost_per_correct_answer`
- `latency_per_correct_answer`
- `compression_loss`: baseline fact recall minus variant fact recall
- `retrieval_waste`: context tokens that do not support required facts

## Reports

Matrix reports should have three levels.

### Executive Summary

- Best overall configurations.
- Best cheap configurations.
- Best high-accuracy configurations.
- Best per workload family.
- Regressions vs previous baseline.

### Specialist Recommendations

The report should produce one default recommendation plus 5-6 specialist profiles:

- General/default
- Long legal documents
- Codebase Q&A
- Multi-hop wiki/news
- Conversational memory
- Low-latency production
- Low-cost production

Each recommendation should say:

- use this embedding
- use this chunker
- use this retrieval mode
- use this context strategy
- use this top-k/budget
- expected tradeoff vs baselines

### Audit Artifacts

For every case:

- question
- retrieved chunks/context
- selected docs
- settings/config label
- generated answer
- expected answer
- required facts
- judge verdict
- judge rationale
- supported/missing/contradicted facts
- timing
- token counts
- provider errors

`llm-judge` outputs should live under ignored run directories such as:

- `.llm-judge-runs/<run-id>/summary.md`
- `.llm-judge-runs/<run-id>/results.jsonl`
- `.llm-judge-runs/<run-id>/cases/*.md`

## Proposed Matrix Config Shape

```yaml
run:
  id: mhr-long-context-v1
  mode: smoke # smoke | regression | final
  output_dir: .matrix-runs/mhr-long-context-v1
  cache_dir: .matrix-runs/cache
  resume: true
  concurrency: 4

suite:
  namespace_prefix: mxreg

workloads:
  - name: mhr
    subset: 30
    seed: 42
    tags: [multi-hop, news]

ingest:
  reuse_existing_shapes: true
  refresh_shapes: false
  arms: [lede_spacy]
  embeddings:
    - label: bge-large
      model: BAAI/bge-large-en-v1.5
      dim: 1024
      provider: local
  chunk_strategies: [auto, hierarchy, chunkshop:sentence_aware]
  chunk_max_tokens: [512]
  chunk_overlap_tokens: [50]

retrieval:
  modes: [naive, hybrid, summary]
  retrieval_strategies: [weighted, pre_filter, vector_first]
  top_k: [10, 25, 50, 100]

context:
  strategies:
    - classic_chunks
    - full_selected_docs
    - doc_summary_facts
    - doc_summary_toc_facts
    - doc_summary_toc_facts_plus_chunk_summary

baselines:
  full_document:
    max_docs: 3
    max_context_tokens: 120000
  classic_rag:
    top_k: 25
    chunker: auto-512

answer:
  provider: openai
  model: gpt-4.1-mini
  api_key_env: OPENAI_API_KEY

judge:
  mode: accurate
  providers:
    - provider: openai
      model: gpt-4.1-mini
      api_key_env: OPENAI_API_KEY
```

## Fast Reload / Shape Reuse

The matrix harness treats an ingest shape as the expensive part:

- dataset
- arm / fact extractor
- embedding model + dimension
- chunk strategy
- chunk token and overlap settings

Each shape gets a deterministic namespace such as `mx_mhr_lede_spacy_bge_large_auto_512_50_<hash>`.
By default, `ingest.reuse_existing_shapes: true` means repeated runs skip
re-chunking and re-embedding when that namespace already has documents.

Use:

```bash
uv run python -m benchmarks.matrix.suite --config benchmarks/matrix/smoke.yaml --judge --report
```

For a stage-only cache warmup:

```bash
uv run python -m benchmarks.matrix.suite --config benchmarks/matrix/regression.yaml --prepare-only
```

Only set `ingest.refresh_shapes: true` when corpus contents, chunker behavior,
embedding model, embedding dimension, or extraction settings changed. Retrieval,
top-k, summarization, context assembly, answer models, judge models, and report
settings reuse the staged shapes.

Generated artifacts:

- `.matrix-runs/<run-id>/shape-manifest.json`
- `.matrix-runs/<run-id>/input.jsonl`
- `.matrix-runs/<run-id>/llm_judge.yaml`
- `.matrix-runs/<run-id>/llm-judge/results.jsonl`
- `.matrix-runs/<run-id>/llm-judge/cases/*.md`
- `.matrix-runs/<run-id>/matrix-report.md`

## Execution Modes

### Smoke

Purpose:

- Does the matrix run?
- Are outputs complete?
- Are costs sane?

Scale:

- 2-5 questions
- 2-4 cells
- quick judge

### Regression

Purpose:

- Catch changes in accuracy, retrieval, token use, and latency.

Scale:

- fixed subsets, usually 30-100 questions per workload
- selected known-good and known-risk cells
- quick or dual judge

### Final

Purpose:

- Publishable numbers and recommendation updates.

Scale:

- larger fixed subsets
- accurate judge
- 1-3 judges for disputed or high-value runs
- full audit preservation

## Implementation Plan

1. Keep `benchmarks/showcase/` focused on explainable comparisons.
2. Add `benchmarks/matrix/` for the beast harness.
3. Define a normalized case schema that can feed `llm-judge`.
4. Add workload adapters for existing e2e datasets first: MHR, MuSiQue, 2Wiki.
5. Add corpus adapters for SCOTUS and pg-raggraph source.
6. Add matrix execution with resume and cell-level `ERROR` rows.
7. Add baseline generation:
   - full selected docs
   - classic RAG
8. Add report generation:
   - aggregate tables
   - top configurations
   - specialist recommendations
   - regression deltas
9. Add snapshot comparison against previous runs.

The first useful version should compare:

- workloads: MHR subset 30
- chunkers: `auto`, `hierarchy`, `chunkshop:sentence_aware`
- retrieval: `hybrid`
- top-k: `10`, `25`, `50`
- context: `classic_chunks`, `full_selected_docs`, `doc_summary_toc_facts_plus_chunk_summary`
- judge: `llm-judge` quick for smoke, accurate for final

That is large enough to expose the baseline/cost tradeoffs without exploding into an unmanageable grid.
