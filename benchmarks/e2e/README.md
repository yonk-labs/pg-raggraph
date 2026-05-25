# E2E Benchmark Harness

In-repo benchmark harness for pg-raggraph. Stages three multi-hop QA
corpora (**MultiHop-RAG**, **MuSiQue**, **2WikiMultiHopQA**) and sweeps
each through the full retrieval ladder, emitting accuracy + performance
metrics.

**Design doc:** `docs/superpowers/specs/2026-05-20-e2e-benchmark-harness-design.md`

**Headline question:** does graph-primary retrieval beat lexical+rerank
on multi-hop strata specifically (not just in aggregate)?

## One-time setup

```bash
# Install bench extras
uv pip install -e '.[bench,lede_spacy]'

# (lede_spacy arm only) spaCy model
uv run python -m spacy download en_core_web_sm

# Start the dedicated bench Postgres (port 5437, dim=1024)
docker compose up -d postgres-bench

# Optional: judge endpoints
export OPENAI_API_KEY=sk-...                       # gpt-5-mini (primary)
# OR
export PGRG_BENCH_LOCAL_LLM_BASE=http://localhost:8000/v1
export PGRG_BENCH_LOCAL_LLM_MODEL=Qwen/Qwen3-Coder-30B
```

## Run it

```bash
# Full run — all 3 datasets, 500-query subsets, default lede_spacy arm
uv run python -m benchmarks.e2e.run

# One dataset, fast smoke (5 queries, no LLM judge)
uv run python -m benchmarks.e2e.run --dataset twowiki --subset 5 --judge none

# Both arms, with LLM extraction (Qwen vLLM required)
uv run python -m benchmarks.e2e.run --arms lede_spacy,llm

# Re-run retrieval against an already-staged namespace (cheap iteration)
uv run python -m benchmarks.e2e.run --dataset mhr --skip-ingest

# Just one ladder rung
uv run python -m benchmarks.e2e.run --dataset mhr --modes L4_rerank
```

## Output

Lands in `benchmarks/e2e/results/` (gitignored):

- `YYYY-MM-DD-{dataset}-{arm}.json` — one record per (query, rung) with
  full scoring + provenance (`git_sha`, `pgrg_version`, `judge_provider`,
  `timestamp`).
- `YYYY-MM-DD-summary.json` — machine-readable aggregate (pooled +
  per-stratum + latency pivots).
- `YYYY-MM-DD-summary.md` — pre-filled findings-doc template; human
  writes the headline interpretation.

## Subsets

Subset query IDs are frozen by `(dataset, n, seed)` and committed to
`benchmarks/e2e/subsets/`. Re-running with the same `--subset` and
`--seed` always picks the same queries. First run with a new pair
generates and commits a new subset file.

## What this harness is and isn't

**Is:** a reproducible, in-repo benchmark for the multi-hop graph
question. Replaces ad-hoc scripts; emits the dual-scorer (span + judge +
rank) discipline the 2026-05-19 findings doc landed on.

**Isn't:** an embedder/extractor sweep. The embedder is pinned
(`bge-large-en-v1.5`, dim=1024); the extractor varies only between
`lede_spacy` and `llm`. Sweeping more dimensions in one run is what the
findings doc cautioned against.

## Adding a dataset

1. Add a loader module under `datasets/` that exposes `load(subset, seed)
   → DatasetBundle`.
2. Call `register("name", load)` at module bottom.
3. Add the name to the import line in `datasets/__init__.py`.
4. Run with `--dataset name --subset 5 --judge none` to smoke-test.
