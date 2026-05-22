# E2E Benchmark Harness — Design

**Date:** 2026-05-20
**Status:** approved (brainstorming → handoff to writing-plans)
**Author:** brainstormed with the user; codified from 2026-05-19 findings doc
**Successor of:** `benchmarks/sweep-results/2026-05-19-benchmark-findings-and-next-run.md` §5
**Lives in:** `benchmarks/e2e/` (new), entry point `python -m benchmarks.e2e.run`

---

## 1. Purpose

A reproducible, in-repo benchmark harness that ingests three multi-hop QA corpora,
runs the pg-raggraph retrieval ladder against each, and emits both accuracy and
performance metrics. Self-contained — no dependency on the `stele-phase6-7` sweep
harness.

The headline question this run is designed to answer:
**On corpora with explicit multi-hop supervision, does graph-primary retrieval
beat lexical+rerank on the multi-hop question types specifically (not just in
aggregate)?**

This is the §5.1 pre-registered hypothesis from the findings doc.

---

## 2. Scope

### In scope
- Three datasets: MultiHop-RAG, MuSiQue (dev), 2WikiMultiHopQA (dev).
- Two ingest arms per dataset: `lede_spacy` (fast, deterministic) and `llm` (Qwen vLLM).
- One embedder pinned: `bge-large-1024` (the rank-metric winner from the embed sweep).
- Full retrieval ladder per cell: L0 / L1 / L2 / GP_local / GP_global / GP_hybrid / L4_rerank / smart.
- Dual scorer: LLM-judge (gpt-5-mini primary, local Qwen fallback) + answer-span recall + rank metrics (MRR, nDCG@k, hit@1).
- Per-query performance: server-side latency p50/p95, end-to-end latency, candidate set size before/after rerank.
- Per-arm ingest metrics: wall-clock, atoms/entities/relationships counts.
- Stratified reporting by `question_type` (MHR) and by `n_hops` (MuSiQue, 2Wiki).

### Out of scope
- Embedder/extractor sweep. Pin both; that's a different matrix and mixing them is
  what §3 of the findings doc warned against.
- A pytest layer with CI gates. Harness only; pytest gates can be added once we know
  what numbers to gate on.
- Blocking on K1 (two-stage retrieval). The doc flags that retrieval numbers will
  shift after K1 lands; the harness records `git_sha` and `schema_version` per cell
  so we can re-baseline cleanly.
- LoCoMo, LME, HotpotQA, SCOTUS, NTSB, SEC, PG-docs. Existing benchmarks under
  `benchmarks/` are not touched.

---

## 3. Datasets

| Dataset | Corpus | Query subset | Stratification | Loader notes |
|---|---|---|---|---|
| MultiHop-RAG | 609 news docs | 500 of ~2.5k | by `question_type` (inference / comparison / temporal / null) | HF dataset `yixuantt/MultiHopRAG`, MIT |
| MuSiQue (dev) | ~2.4k Wikipedia paragraphs | 500 | by `n_hops` (2/3/4) | github.com/StonyBrookNLP/musique, CC-BY-4.0 |
| 2WikiMultiHopQA (dev) | dev set | 500 | by `type` (compositional / inference / comparison / bridge_comparison) | github.com/Alab-NII/2wikimultihop, MIT |

**Subset sizing rationale.** 500 queries gives ≥30 per stratum on MHR's smallest
type after class balancing, enough power to call a 5pp shift. Pre-registered:
deterministic seed (42) for subset selection; subset query IDs frozen and
committed to `benchmarks/e2e/subsets/`.

**Cache.** Raw downloads cache to `~/.cache/pg_raggraph_bench/{dataset}/` and are
referenced by content hash. Loaders are idempotent — re-run hits cache.

**Normalization.** Every loader emits the same shape:

```python
DatasetBundle(
    name: str,
    corpus_docs: list[CorpusDoc],   # {source_id, text, metadata?}
    queries: list[Query],            # {qid, question, answers: list[str], strata: dict[str, str]}
    license_notice: str,
)
```

`strata` is open-ended so each dataset reports its own dimensions without a
shared schema.

---

## 4. Ingest arms

Two arms run per dataset. Each arm gets its own namespace:
`bench_{dataset}_{arm}`. Stage once, sweep many — namespaces are not dropped
between retrieval cells.

| Arm | Extractor | Embedder | LLM | Notes |
|---|---|---|---|---|
| `lede_spacy` | deterministic NER + co-occurrence | bge-large-1024 | none | Fast baseline; tests "is the graph worth the LLM cost?" |
| `llm` | LLM extraction via Qwen vLLM | bge-large-1024 | Qwen3-Coder (local) | The conventional GraphRAG path |

Embedder is pinned to `bge-large-1024` because the 2026-05-18 rank-embed sweep
showed it dominated on MRR/hit@1 while the cheap baseline hid the effect under
span-recall.

**Dedup safety.** Each arm namespace is deleted and re-created at the start of
its ingest if `--reingest` is passed; otherwise it short-circuits on existing
documents (content_hash dedup).

---

## 5. Retrieval ladder

Per query, in this order (one `GraphRAG` instance, one `.query()` call per mode):

| Rung | Mode | What it tests |
|---|---|---|
| `L0_fts` | (raw BM25, helper) | Lexical floor — no embeddings, no graph |
| `L1_naive` | `naive` | vec + BM25 hybrid; current default |
| `L2_naive_boost` | `naive_boost` | L1 + 1-hop graph re-rank |
| `GP_local` | `local` | Graph-primary, local community |
| `GP_global` | `global` | Graph-primary, global summaries |
| `GP_hybrid` | `hybrid` | Graph-primary, both |
| `L4_rerank` | `naive` + cross-encoder | The universal lever from findings §3.1 |
| `smart` | `smart` | Confidence-routed default |

The reranker for L4 is `bge-reranker-base` (or whatever the existing
`naive_boost` reranker config points at — single source of truth).

---

## 6. Scoring

### Three scorers per query

1. **LLM-judge (primary).** `gpt-5-mini`, `reasoning_effort=minimal`. Two prompts:
   one to answer the question from the retrieved chunks, one to grade that
   answer against the reference. Same model for both — internally consistent
   across cells. The findings doc flagged self-grading as a known caveat;
   recorded with the run, not hidden.
2. **Answer-span recall@k (floor).** Set-membership of any reference answer
   token in the concatenated top-k. Never quoted alone (the "chunkshop
   verbatim-span artifact" — ~2× overstatement vs LLM-judge).
3. **Rank metrics.** MRR, nDCG@k (k=10), hit@1. These exposed the embedder
   effect that span-recall hid.

### Judge fallback

If `OPENAI_API_KEY` is unset or the call fails, fall back to the local Qwen
provider. The harness logs a `judge_provider` field per cell and emits a
warning at run start; absolute scores will not be comparable across providers,
but per-cell rankings within a run will be valid.

### Reporting per cell

Every (dataset, arm, mode, query) cell records: all three scores, the strata
dict from the query, latency p50/p95 (server-side), candidate set sizes,
`git_sha`, `schema_version`, `judge_provider`, timestamp.

### Stratified rollups

For each dataset, the report tables answer:
- Overall score per (arm × mode), with 95% CI from the per-query distribution
- Score per (arm × mode × stratum) — the headline view
- Δ vs `L1_naive` for each (arm × mode), the deployment-decision view

---

## 7. Performance metrics

### Per ingest
- Wall-clock seconds
- Atoms (chunks) created
- Entities created
- Relationships created
- Peak Postgres connections held (sampled via pg_stat_activity)
- Embedding tokens billed (if remote embedder ever used)

### Per query
- Server-side latency: time inside `.query()` from entry to return
- End-to-end latency: includes scorer + LLM-judge round-trip (reported
  separately so the retrieval number isn't polluted)
- Candidate set size: single value for non-rerank rungs; before/after for L4

### Aggregate
- p50, p95, p99 per (arm, mode)
- Ingest throughput (chunks/sec, entities/sec) per arm

---

## 8. Outputs

```
benchmarks/e2e/results/
  2026-05-20-mhr-lede_spacy.json        # per-query cells
  2026-05-20-mhr-llm.json
  2026-05-20-musique-lede_spacy.json
  2026-05-20-musique-llm.json
  2026-05-20-twowiki-lede_spacy.json
  2026-05-20-twowiki-llm.json
  2026-05-20-summary.json               # aggregate pivot tables
  2026-05-20-summary.md                 # findings doc, pre-filled template
```

The markdown summary uses the same shape as `2026-05-19-benchmark-findings-and-next-run.md`:
*Scope of what ran → Headline finding → Robust conclusions → What NOT to trust →
Next steps.* Filled by the harness; the human authors the §2 headline interpretation
after reading the tables.

---

## 9. Layout

```
benchmarks/e2e/
  __init__.py
  run.py                    # entry: --dataset {mhr,musique,twowiki,all}
                            #        --arms {lede_spacy,llm,all}
                            #        --subset N
                            #        --reingest / --skip-ingest
                            #        --modes {all,L1,L2,GP_*,L4,smart}
                            #        --judge {auto,openai,local}
  config.py                 # subset sizes, ladder, arms — overridable
  datasets/
    __init__.py             # registry: {name: loader_module}
    mhr.py                  # download + normalize + stratify
    musique.py
    twowiki.py
    _common.py              # CorpusDoc / Query / DatasetBundle DTOs
  ingest.py                 # per-arm stage; namespace mgmt; dedup
  retrieve.py               # ladder runner
  score.py                  # span recall + judge + rank metrics
  judge.py                  # gpt-5-mini client + local Qwen fallback
  report.py                 # markdown summary + summary.json
  subsets/
    mhr-500-seed42.json     # frozen subset query IDs (committed)
    musique-500-seed42.json
    twowiki-500-seed42.json
  results/                  # gitignored; one run = one date prefix
```

`benchmarks/e2e/results/` added to `.gitignore`.

---

## 10. Constraints (Always / Ask First / Never)

**Always:**
- Pre-register the hypothesis at the top of the summary markdown
- Record `git_sha` + `schema_version` + `judge_provider` on every cell
- Dual-scorer every cell (span + judge); never publish span alone
- Stratify the headline table by `question_type` / `n_hops`
- Freeze and commit subset query IDs (deterministic seed=42)

**Ask first:**
- Adding a fourth dataset (re-runs the design conversation)
- Changing the embedder (it's pinned for a reason)
- Quoting any single-dataset number as a general claim
- Sweeping a new dimension (extractor, chunker, top_k) — that's a separate matrix

**Never:**
- Publish span-recall as the headline metric
- Sweep multiple dimensions in one run (embedder × extractor × dataset is what
  the findings doc explicitly cautioned against)
- Re-ingest within a sweep (stage once)
- Commit `~/.cache/pg_raggraph_bench/` or `benchmarks/e2e/results/`
- Drop a dataset namespace without `--reingest`

---

## 11. Success criteria

- **SC-1.** `python -m benchmarks.e2e.run --dataset all` runs end-to-end on a
  clean machine with `OPENAI_API_KEY` set and produces all six per-arm JSON
  files plus the summary md/json.
- **SC-2.** `python -m benchmarks.e2e.run --dataset mhr --judge local` runs
  end-to-end with no OpenAI key and emits a `judge_provider=local` warning.
- **SC-3.** The summary markdown's "Headline" table shows graph-primary modes
  vs L1_naive vs L4_rerank, stratified by question_type, for MHR specifically.
- **SC-4.** Subset query IDs are deterministic across runs on the same seed.
- **SC-5.** Every cell carries `git_sha`, `schema_version`, `judge_provider`,
  `timestamp` — enough metadata to diff against a post-K1 re-baseline.
- **SC-6.** Ingest is idempotent: re-running without `--reingest` short-circuits
  on existing documents (no double-stage).
- **SC-7.** Per-arm wall-clock and per-mode latency p50/p95 land in the summary.

---

## 12. Drift checkpoints

- **DC-1 (after loaders land).** Each loader emits a `DatasetBundle` whose
  shape can be printed as a one-line summary. Verify normalization is uniform
  before building the ingest layer on top.
- **DC-2 (after ingest layer lands).** Confirm namespace-per-arm pattern works
  end-to-end on the smallest dataset (2Wiki) before scaling to MHR.
- **DC-3 (after retrieval layer lands).** Run one query through all eight ladder
  rungs on a single staged arm; verify no mode crashes before scaling to the
  full 500-query subset.
- **DC-4 (after scorer lands).** Run a 10-query slice with all three scorers
  on one arm. Confirm span-recall ≈ 2× judge (the documented artifact); confirm
  rank metrics produce sane values. If span and judge agree, something is wrong
  with the judge prompt.
- **DC-5 (before declaring done).** Re-read this design doc and check every
  SC-X has evidence in the summary output, not just the code.

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| 2WikiMultiHopQA / MuSiQue loaders take longer than expected (format quirks, missing gold paths in dev set) | Build MHR end-to-end first; reuse the `_common.py` DTOs and ingest layer; ship MHR alone if the other two slip |
| LLM-judge cost overruns | Cache (qid, top_k_hash) → judge_result in `~/.cache/pg_raggraph_bench/judge/`; subsequent runs re-use unchanged cells |
| Pre-K1 sequential scan makes the full sweep too slow | Subset sizes (500/dataset) are deliberately conservative; document the expected wall-clock budget; add `--skip-ingest` so retrieval can re-run cheaply |
| Local Qwen judge drifts vs gpt-5-mini | Logged per-cell as `judge_provider`; report excludes cross-provider comparisons |
| Embedder pinning hides an effect | Out of scope by design; documented in §2 Out of scope; the embed sweep already happened (2026-05-18) |

---

## 14. References

- `benchmarks/sweep-results/2026-05-19-benchmark-findings-and-next-run.md` — the
  motivating findings doc; this design implements its §5 recommendations
- `benchmarks/sweep-results/2026-05-18-locomo-rank-embed.json` — the embedder
  sweep that justifies pinning `bge-large-1024`
- `benchmarks/DATASETS.md` — existing dataset inventory (does not yet include
  MuSiQue / 2Wiki)
- `docs/operations-guide.md` — K1 retrieval fix; this harness records enough
  metadata to re-baseline cleanly after K1 lands

---

## 15. Open items for the writing-plans pass

These are intentional gaps for the plan to resolve:

- Exact MuSiQue and 2Wiki HF/GitHub URLs + license file copy (loaders should
  copy LICENSE to `~/.cache/pg_raggraph_bench/{dataset}/LICENSE`).
- The `L0_fts` helper — does pg-raggraph expose a raw-FTS path or does the
  harness need to issue raw SQL? (Quick read of `src/pg_raggraph/retrieval.py`
  during the planning pass.)
- The cross-encoder reranker config — where it lives and how to wire L4 from
  the harness without duplicating model loading.
- Whether `judge.py` reuses the existing `extraction.py` HTTPx LLM client or
  gets its own minimal client (a judge call is not an extraction call).
