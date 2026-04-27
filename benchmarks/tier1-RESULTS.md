# Tier 1 Sanity Benchmark — Results

**Run date:** 2026-04-27.
**Script:** `benchmarks/tier1-sanity.py`.
**Raw output:** `benchmarks/tier1-sanity-results.json`.

## What this is

A wiring smoke test for the Tier 1 evolution-aware retrieval and the
`tune_scoring_weights()` utility. It runs against the two largest synthetic
fixture corpora shipped with the repo:

| Corpus | Docs | Gold Qs |
|---|---|---|
| `medical_retraction` | 4 (2 retracted) | 3 |
| `policy_effective_dates` | 2 | 2 |

For each corpus, it Cartesian-products a 3 × 2 × 3 × 2 = **36-cell weight grid**
(w_sem × w_bm25 × w_recent × w_supersession) under `mode="naive"` and
`evolution_tier="structural"` with `retracted_behavior="hide"`, then reports the
best and worst cells.

## Results

```
medical_retraction (3 gold questions)
  best:    3/3   w_sem=0.3, w_bm25=0.1, w_recent=0.0, w_supersession=0.0
  worst:   3/3   w_sem=0.3, w_bm25=0.1, w_recent=0.0, w_supersession=0.0
  distribution: {3: 36}        ← every cell scored 3/3

policy_effective_dates (2 gold questions)
  best:    2/2   w_sem=0.3, w_bm25=0.1, w_recent=0.0, w_supersession=0.0
  worst:   2/2   w_sem=0.3, w_bm25=0.1, w_recent=0.0, w_supersession=0.0
  distribution: {2: 36}        ← every cell scored 2/2
```

## What this tells us

**The Tier 1 wiring works.** End-to-end ingest + retraction filtering + as_of
filtering + grid-search-over-weights all succeed against fixture corpora. The
medical retraction filter correctly hides the 2 retracted docs (the gold
questions about "is HRT cardioprotective?" return current guidance, not the
retracted observational studies).

**The corpora are too small for tuning to differentiate.** With only 2–4 docs
per corpus and 2–3 gold questions, every weight combination gets perfect recall.
A useful tune_scoring_weights run needs hundreds of docs and dozens of gold
questions — enough that some cells fail to retrieve the expected substring.

## What's NOT in this benchmark

- **Real-world retraction corpus.** No medical literature with actual retraction
  notices ingested at scale. Building one is a separate effort — likely needs a
  real-world dataset like PubMed Central retracted-papers index.
- **Real-world versioned-docs corpus.** Same caveat — Python docs across 3.10–3.12
  would be a candidate but isn't ingested.
- **Latency comparison.** This script measures retrieval correctness only, not
  query timing.
- **Comparison against `evolution_tier="off"`.** The fixtures are designed to
  fail without retraction filtering, so the contrast is in `test_evolution_tier1.py`
  (e.g., `test_retracted_behavior_hide_filters_retracted_docs`) rather than here.

## How to extend

To run a real-world Tier 1 benchmark, you need:

1. A corpus of 200+ documents where some are clearly superseded or retracted.
2. A `manifest.yaml` mapping each doc to its evolution metadata (effective_from,
   retracted, supersedes_document_id, version_label).
3. A `gold_questions.yaml` of 30+ questions where the *correct* answer is in
   the post-supersession or non-retracted docs.
4. Run with `mode="hybrid"` (or `naive`) and `evolution_tier="structural"`,
   then run `tune_scoring_weights` with a meaningful grid.

See `tests/fixtures/evolving/medical_retraction/` for the manifest schema and
`benchmarks/tier1-sanity.py` for the runner pattern.
