# RRF fusion (rank fusion vs the linear weighted sum)

> **Status:** new in [issue #57](https://github.com/yonk-labs/pg-raggraph/issues/57). Optional, **default-off**. Applies to `naive` and `hybrid` modes — `local` / `global` / `smart` / `summary` / `naive_boost` are unchanged in this version.

pg-raggraph fuses two retrieval legs — pgvector cosine similarity and BM25 full-text — into one ranked list. By default it does this with a **linear weighted sum**: `w_sem · cosine_score + w_bm25 · bm25_score`. That works, but it adds two scores that live on different scales (cosine is bounded `[0, 1]`-ish; BM25 is an unbounded log-frequency score). A tiny weight change, or a corpus where one leg's scores happen to be larger, can quietly dominate the other.

**Reciprocal Rank Fusion (RRF)** sidesteps the scale problem. Instead of summing the raw scores, it sums the *reciprocal ranks*:

```
score(d) = Σ_legs  w_i / (rrf_k + rank_i(d))
```

A document's contribution depends only on *where it placed* in each leg, not on the magnitude of its score. That makes RRF **scale-free** — the cosine leg and the BM25 leg are compared on equal footing no matter how their raw scores are distributed.

## The two config knobs

```python
from pg_raggraph import PGRGConfig

PGRGConfig(fusion="linear")   # default — the existing weighted-sum path
PGRGConfig(fusion="rrf")      # opt in to rank fusion
PGRGConfig(rrf_k=60)          # the RRF smoothing constant (default 60)
```

`rrf_k` dampens the influence of top ranks: larger `k` flattens the curve so the #1 and #2 hits matter less relative to the tail. `60` is the value from the original Cormack et al. RRF paper and a sane default.

## Per-call override

Like the other retrieval knobs, `fusion` is overridable per call (race-safe, multi-tenant friendly):

```python
# Most queries: config default (linear)
result = await rag.query(q, mode="naive")

# This one call: fuse by rank instead
result = await rag.query(q, mode="naive", fusion="rrf")
result = await rag.ask(q, mode="hybrid", fusion="rrf")
```

Pass `None` (the default) and the call falls back to `config.fusion`.

## Default-off and byte-identical

When `fusion="linear"` (the default) the SQL is byte-identical to the pre-#57 path — no ranked CTE, no `rank()` windows, nothing changed. RRF is purely additive; existing call sites get exactly the behavior they had.

## One semantic note: `mf_soft` is dropped under RRF

The `mf_soft` metadata-bias term is a small nudge applied to the *score scale* (a soft additive bump for metadata-matched chunks). Once legs are fused by **rank**, a score-scale nudge has no meaning — it can't move a document's rank without being large enough to be a different mechanism entirely. So under `fusion="rrf"` the `mf_soft` term is dropped. The hard metadata filter (`mf_hard`) still applies — that's a WHERE clause, not a score nudge.

## See also

- [`per-call-kwargs.md`](per-call-kwargs.md) — the full set of per-call overrides, including `fusion`
- [`retrieval-strategy.md`](retrieval-strategy.md) — the orthogonal `retrieval_strategy` knob (SQL shape, not fusion math)
