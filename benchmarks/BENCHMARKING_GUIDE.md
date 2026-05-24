# pg-raggraph Benchmarking & Testing Guide

How the benchmark harnesses work, how to set them up, the experiments they run,
and worked examples. This is the operational companion to
[`TESTING_STRATEGY.md`](TESTING_STRATEGY.md) (which covers the *why*); this doc
covers the *how*.

---

## 1. The two harnesses

| Harness | Path | What it's for |
|---|---|---|
| **e2e ladder** | `benchmarks/e2e/` | Stage a corpus once, sweep a fixed "retrieval ladder" (naive → naive_boost → local → global → hybrid → rerank → smart → summary) across whole datasets. Good for "which retrieval mode wins on this corpus." |
| **matrix** | `benchmarks/matrix/` | Config-driven cartesian sweep over *any* axes — embedder, chunker, mode, top_k, **context-packing strategy** — judged by llm-judge against two mandated baselines, then ranked into a report. Good for "which end-to-end recipe is best, and what does it cost." |

The deep runs described below use the **matrix** harness. Both share the dataset
loaders (`benchmarks/e2e/datasets/`) and frozen query subsets
(`benchmarks/e2e/subsets/`).

### Pipeline

```
config.yaml
   │  benchmarks.matrix.run         (prepare)   → input.jsonl  (one case per recipe×question)
   │                                              shape-manifest.json, llm_judge.yaml
   │  llm-judge evaluate            (judge)     → llm-judge/results.jsonl (+ per-case audit)
   │  benchmarks.matrix.report      (per-run)   → matrix-report.md
   ▼  benchmarks.matrix.analyze     (cross-run) → DEEP-REPORT.md
```

`benchmarks.matrix.suite` chains prepare → judge → report.
`benchmarks/matrix/run_deep.sh` chains the multi-phase deep run + `analyze`.

---

## 2. Setup / prerequisites

| Dependency | Value | Notes |
|---|---|---|
| Bench Postgres | `postgresql://postgres:postgres@localhost:5437/pg_raggraph_bench` | pgvector + pg_trgm; `docker compose up -d postgres-bench` |
| Embedder | `BAAI/bge-large-en-v1.5` (dim 1024) | pinned for reproducibility; fastembed (CPU) |
| Answer model | `Intel/Qwen3-Coder-Next-int4-AutoRound` @ `http://192.168.1.193:8000/v1` | local vLLM |
| Judges (dual) | Qwen @ `.193` + `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` @ `http://192.168.1.133:8000/v1` | llm-judge emits one ensemble row/case |
| lede | 0.4.5 | summary / key_facts / report mode |
| chunkshop | 0.5.0 (local editable) | `chunkshop:*` chunk strategies |
| llm-judge | `pip install "llm-judge @ git+https://github.com/yonk-labs/llm-judge.git"` | `uv run llm-judge --help` |
| OpenAI key (optional) | `../.openai` → `home_key=` | spec-primary judge for final numbers; local dual-judge is the cost-free default |

Fast reload: staged corpora are snapshotted via `benchmarks/e2e/snapshot.py`
(`dump`/`restore`) so you can skip the multi-hour ingest. Pre-staged namespaces:
`bench_mhr_lede_spacy`, `bench_musique_lede_spacy`, `bench_twowiki_lede_spacy`.

---

## 3. Datasets

| Dataset | Loader | Corpus | Gold | Notes |
|---|---|---|---|---|
| **MHR** (MultiHop-RAG) | `datasets/mhr.py` | 609 news articles (shared) | single answer | strata: `question_type` (inference/comparison/temporal/null_query) |
| **MuSiQue** | `datasets/musique.py` | per-query paragraphs | answer + support | strata: `n_hops` (2/3/4) |
| **2Wiki** | `datasets/twowiki.py` | per-query paragraphs | answer + support | strata: `type` |
| **SCOTUS** (custom) | `datasets/scotus.py` | 391 opinion summaries (shared) | `gold_answer` | strata: `bucket` (impossible/hard/medium/easy/layup) from the 50-query fixture |

Query subsets are **frozen** by `{dataset}-{n}-seed{seed}.json` so every run sees
the same questions. Curated subsets (e.g. `mhr-10-seed4224`, `scotus-10-seed4224`)
hand-pick answerable questions for focused experiments.

---

## 4. Use cases / experiments

### Two mandated baselines (every workload)
- **Classic RAG** — `classic_chunks @ top_k=25`: send the top-25 retrieved chunks raw. The operational baseline.
- **Full-document oracle** — `full_selected_docs`: send the whole selected document(s). The "expensive upper bound" — though it is *not* always the ceiling (see findings).

Every other recipe is reported as a delta against these two.

### Deep run (3rd-party benchmarks) — `run_deep.sh`
- **Phase A** (`deep_a_modes_context.yaml`): retrieval mode (`hybrid`,`smart`) × top_k (`10/25/50`) × 5 context-packings, on MHR/MuSiQue/2Wiki (30 frozen Qs each). Reuses staged `auto` shapes — no re-ingest.
- **Phase B** (`deep_b_chunkers.yaml`): chunker axis (`hierarchy`, `chunkshop:hierarchy/sentence_aware/semantic/neighbor_expand`) on MHR (structured corpus where chunking matters). `auto` comes from Phase A.

### Summary-density experiment — `deep_c_summary_density.yaml` (MHR) and `deep_c_scotus_summary_density.yaml` (SCOTUS)
Focused 10-question study answering three questions:
1. **Density** — `doc_summary_facts` at 1× / 1.5× / 2× / 3× the default char budget. Does more density buy accuracy?
2. **Summary source** — summarize the **full document** vs the **25 retrieved chunks** vs **both**. (Default `doc_summary_facts` summarizes the *full doc*.)
3. **"Beat classic RAG@25"** — a summary (+TOC headers +facts) of chunks/doc/both **plus the top-5 raw chunks**. Can a compressed context match 25 raw chunks at a fraction of the tokens?

### Context-packing strategies (the star axis)
| strategy | what it sends |
|---|---|
| `classic_chunks` | top-k retrieved chunks, raw |
| `full_selected_docs` | whole selected document(s) |
| `doc_summary_facts` | lede summary of the **full doc** + key facts |
| `doc_summary_facts_x1_5 / _x2 / _x3` | same, at 1.5/2/3× char budget |
| `chunk_summary_facts` | lede summary of the **retrieved chunks** + facts |
| `doc_and_chunk_summary_facts` | both summaries |
| `*_toc_facts_plus_top5` | summary(+TOC headers+facts) + the top-5 raw chunks |
| `toc_doc_summary_plus_chunk_summary` | full-doc summary (with TOC) + a summary of the chunks |

---

## 5. Metrics

Per recipe (a recipe = dataset × chunker × mode × top_k × context):
- **pass rate** — fraction judged CORRECT (ensemble of two judges).
- **avg score** — 1.0 correct / 0.5 partial / 0.0 wrong, averaged.
- **fact coverage** — `supported / (supported + missing)` facts (recall proxy), skipping "insufficient-info" golds.
- **avg context tokens** — what we pay per query.
- **token savings vs RAG / vs oracle** — the headline efficiency numbers.
- **latency** — answer + judge wall time.

Judging is **semantic**, not substring: paraphrases, aliases, reordered facts,
and partial names all count. The grading instruction lives in llm-judge; the
reference is the dataset gold answer (and required facts where present).

---

## 6. Worked examples

### Example A — token savings with no accuracy loss (MHR, hybrid @25)
> **Q:** "Considering the updates on Azure's AI capabilities from a Bloomberg article and the expansion of Azure's data center regions…"

| context strategy | verdict | context tokens |
|---|---|---:|
| `classic_chunks` (25 raw) | CORRECT | 10,905 |
| `doc_summary_facts` | CORRECT | **2,487** (−77%) |
| `doc_summary_toc_facts` | CORRECT | 2,515 |

Takeaway: the lede summary answered correctly on ~1/4 the tokens. This is the
core thesis the density experiment stress-tests.

### Example B — a correct multi-hop answer (MuSiQue, classic_chunks)
> **Q:** "Who does the narrator on How I Met Your Mother end up with?"
> **Gold:** Tracy McConnell
> **Answer:** "The narrator, Future Ted Mosby … ends up with Tracy McConnell, known as 'The Mother.'"
> **Verdict:** CORRECT (2/2 judges), score 1.0

### Example C — a retrieval miss the judge correctly fails (MuSiQue, classic_chunks)
> **Q:** "Who is the sibling of the actress who played Susan Walker in Miracle on 34th Street?"
> **Gold:** (a named sibling)
> **Answer:** "Mara Wilson played Susan Walker … no siblings mentioned. Insufficient information."
> **Verdict:** INCORRECT (2/2 judges), score 0.0

The model correctly identified the actress (hop 1) but the second hop's fact
was never retrieved — the judge fails it because the required fact *is* the
answer. This is the kind of case that distinguishes retrieval quality from
generation quality.

---

## 7. Running it

```bash
# One-time judge install
pip install "llm-judge @ git+https://github.com/yonk-labs/llm-judge.git"

# Smoke (2 questions, fast) — proves the pipeline is green
uv run python -m benchmarks.matrix.suite --config benchmarks/matrix/smoke.yaml --judge --report

# Full deep run (Phase A + B + consolidated report), idempotent/resumable
benchmarks/matrix/run_deep.sh
PHASES=a benchmarks/matrix/run_deep.sh    # one phase only

# Summary-density experiment
uv run python -m benchmarks.matrix.suite --config benchmarks/matrix/deep_c_summary_density.yaml --judge --report
uv run python -m benchmarks.matrix.suite --config benchmarks/matrix/deep_c_scotus_summary_density.yaml --judge --report

# Consolidate any set of runs into one report
uv run python -m benchmarks.matrix.analyze \
  --results '.matrix-runs/deep-a-modes-context/llm-judge/results.jsonl' \
  --results '.matrix-runs/deep-b-chunkers/llm-judge/results.jsonl' \
  --out .matrix-runs/DEEP-REPORT.md
```

**Repeatability:** all configs set `resume: true`. Re-running skips
already-prepared cases, reuses staged ingest shapes (`reuse_existing_shapes`),
and reuses cached judge calls. Set `refresh_shapes: true` only when the corpus,
chunker, or embedder changed. Use a different judge by editing `judge.providers`
(local dual-judge by default; add an OpenAI provider for spec-primary numbers).

---

## 8. Output layout

```
.matrix-runs/<run-id>/
  input.jsonl            # prepared cases (question, chunks, settings, tokens)
  shape-manifest.json    # ingest stats per shape
  llm_judge.yaml         # generated llm-judge config
  llm-judge/
    results.jsonl        # ensemble-judged rows (machine-readable)
    summary.md           # aggregate accuracy/latency
    cases/<id>.md        # per-question audit: chunks, answer, gold, verdict, rationale
  matrix-report.md       # per-run baseline-relative table
.matrix-runs/DEEP-REPORT.md   # cross-run: baselines, top recipes, specialist picks
```

Every reported number is backed by a per-case audit trail in `cases/` — question,
retrieved context, settings, generated answer, gold, judge verdict + rationale,
and per-call timing.
