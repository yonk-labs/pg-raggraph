# RRF A/B benchmark — linear vs RRF fusion (MuSiQue, naive mode)

Measurement-driven comparison for issue #57 / SC-008: does **RRF**
(reciprocal-rank fusion) change `mode="naive"` retrieval quality versus the
default **linear** (weighted-sum) fusion? naive mode runs both a vector leg
(pgvector cosine) and a BM25 leg (PG full-text), so it's the place where a
scale-free rank fusion could matter most.

## What it measures

- **recall@k** (k = 3, 5, 10) — fraction of questions where ≥1 gold
  `supporting` doc lands in the top-k retrieved chunks.
- **rank-overlap** — mean Jaccard of the top-10 doc sets returned by linear vs
  rrf for the same question (1.0 = identical ordering set).

Deterministic retrieval metrics only — no LLM judge. Gold = MuSiQue
`supporting` doc filenames; a retrieved chunk maps to a gold doc via its
source-path stem.

## How to run

```bash
uv run python benchmarks/rrf-ab/run_rrf_ab.py
```

Idempotent: ingests a bounded subset (25 questions + their gold docs + capped
distractors ≈ 188 docs) into the throwaway `rrf_ab` namespace. Re-runs skip
the ingest if the doc count already matches. Embeddings are bge-small on CPU.

## Headline finding

On this 25-question / 188-doc MuSiQue subset, **linear and RRF are
recall-equivalent for naive mode**: both hit **recall@3 = recall@5 =
recall@10 = 1.000**. The gold paragraphs are distinctive enough that both
legs rank them at the top regardless of fusion math.

The only measurable difference is **ordering inside the top-k**: RRF reorders
the top-10 for **20/25** questions (mean Jaccard 0.802; only 5/25 produce an
identical set). That reordering never pushes a gold doc out of even the
top-3, so it does not move recall on this corpus.

Caveat: recall is saturated here because the corpus is small and clean. A
recall-moving difference, if it exists, would only surface on a larger/noisier
corpus or a metric sensitive to exact rank (MRR/nDCG). This run establishes
that RRF is a safe, recall-neutral swap for naive mode at this scale — not
that it is universally equivalent.

See `results-linear-vs-rrf.txt` for the captured run.
