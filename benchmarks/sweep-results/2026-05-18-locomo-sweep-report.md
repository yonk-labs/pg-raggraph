# LoCoMo Optimal-Pathway Sweep — pg-raggraph (MODE A)

**Date:** 2026-05-18 · **Harness:** `stele-phase6-7/benchmarks/external/pgrg_sweep.py`
**Raw matrix:** `benchmarks/sweep-results/2026-05-18-locomo-sweep.json` (deterministic; qid_digest `cefabdb0b805a4e4`)

## Mode & provenance

**MODE A** — the real LoCoMo dataset (`snap-research/locomo`, `locomo10.json`,
cached in `stele-phase6-7/benchmarks/.cache/`) driven through the consumer's
own loader + normalization + scorer, with pg-raggraph as the retrieval
backend.

- **Reused verbatim from the consumer (`stele-phase6-7`):** `loaders.load_locomo()`,
  `bakeoff.locomo_cases()` (atom/question normalization, disclosed subset),
  `harness._answer_hit()` (the scorer — identical to stele's committed bake-off).
- **What differs vs stele's committed `graph` engine:** retrieval goes
  **directly** to `pg_raggraph.GraphRAG.query(mode=…, rerank=…)` with a swept
  `PGRGConfig`, instead of through Stele's `recall(strategy="graph_search")`
  Revisor wrapper. This was **required**: the committed path only exposes
  graph-*primary* retrieval with refs re-keyed by the Revisor, so it
  structurally cannot test H1. The Revisor path (incl. its `lede_spacy`
  variant) is retained conceptually as the graph-primary contrast.
- **pg-raggraph build:** dev source `0.3.0a3` editable-installed into the
  stele venv. The venv's pre-existing `0.3.0a3` *wheel* had **zero lede
  wiring** (stale pre-release rebuild) and silently degraded; the dev source
  fails loud. Sweeping the wheel would have measured dead code.

## Disclosed subset (apples-to-apples — identical every cell)

| | |
|---|---|
| LoCoMo samples | 2 (`conv-26`, `conv-30`) |
| Atoms ingested | 788 (419 + 369 dialogue turns) |
| Answerable questions | 233 |
| Abstention questions | (category-5, scored separately) |
| Recall depth `k` | 20 |
| Scorer | `_answer_hit`: normalize `[a-z0-9]+`, substring OR ≥60% multi-word token overlap |
| Determinism | no RNG in path; qid set hashed (`cefabdb0b805a4e4`) |
| Corpus cap | none (full per-sample turn set) |

## Ingest manifest

| Key | fact_extractor | model | graph built (conv-26 / conv-30) | status |
|---|---|---|---|---|
| **I1_none** | none (`skip_llm`) | — | 0 ent / 0 rel | swept |
| **I2_lede** | lede_spacy (spaCy NER + sentence co-occurrence, no LLM) | en_core_web_sm | 41 ent/74 rel · 19 ent/1 rel | swept |
| I3_llm_mini | llm | gpt-4o-mini (OpenAI; Ollama down) | pending re-stage | pending |
| I4_llm_4o | llm | gpt-4o | **gated — see Honest Negatives** | not run |

> "Coder vs instruct" extractor split is **unavailable** (Ollama down; OpenAI
> exposes no distinct coder chat model). I3/I4 substitute small-vs-large
> instruct (gpt-4o-mini / gpt-4o), recorded as a deviation.

## Ablation ladder — answer-span recall@20 (%)

Marginal lift is vs **L1 (naive = vector+BM25 fusion)**, the lexical/vector
base. Three ingest configs: I1_none (no graph), I2_lede (thin spaCy
co-occurrence graph: 41/19 ent), I3_llm (rich gpt-4o-mini graph: 184/103
ent, 476/396 rel).

| Level | Pathway | I1_none | I2_lede | I3_llm | p50 ms |
|---|---|---:|---:|---:|---:|
| L0 | FTS/BM25 only (raw `ts_rank`) | 51.9 | 51.9 | 52.8 | ~0 |
| **L1** | **naive (vec+BM25)** | **51.1** | **51.1** | **51.1** | 47–89 |
| L2 | naive_boost · gbf 1.2/1.5/2.0 | 51.1 | 51.1 | 51.1 | 43–88 |
| L3 | smart · b0.7/e0.4 (default) | 9.9 | 41.6 | **51.1** | 53–187 |
| L3 | smart · b0.6/e0.3 | 49.8 | 50.6 | **51.1** | 50–93 |
| L3 | smart · b0.8/e0.5 | 0.0 | 37.8 | **51.1** | 59–194 |
| **L4** | **rerank · naive_boost gbf1.5** | **53.2** | **53.2** | **52.8** | 72–117 |
| L4 | rerank · smart default | 9.9 | 43.8 | 52.8 | 79–244 |
| GP | local · h1/h2 | 0.0 | 37.8 | **50.2–51.1** | 7–107 |
| GP | global · h1/h2 | 0.0 | 24.9 | **49.8** | 7–89 |
| GP | hybrid · h1/h2 | 0.0 | 37.8 | **50.2–51.1** | 14–110 |

Marginal lifts vs L1 (51.1, all configs): **L2 = +0.0** (every gbf, every
ingest); **L4 = +1.7 to +2.1** (the only positive lift; it is the
cross-encoder, not the graph); **smart ≤ 0**; **graph-primary** = −13 to
−26pp on the thin lede graph but **≈ parity (−1pp)** on the rich LLM graph.

(I1_none has no graph, so all graph-dependent arms collapse to 0 — an
intentional negative control. The I1→I2→I3 progression *is* the
graph-quality axis.)

## H1 verdict

> **H1 (pre-registered):** a strong lexical/vector base retrieved FIRST with
> the graph applied only as a re-rank/expansion ENHANCER on top
> (`naive_boost`/`smart`) beats **both** graph-primary retrieval **and**
> lexical-only — on LoCoMo answer-span.

**Verdict: REFUTED as stated. The re-rank-enhancer clause is INCONCLUSIVE
BY METRIC CONSTRUCTION. The "≫ graph-primary" claim holds only when the
graph is weak — it collapses to parity once the graph is good, which is
the opposite of what H1 predicts.**

1. **Enhancer ≫ graph-primary — only an artifact of graph quality, NOT a
   topology law.** On the thin lede graph, naive_boost 51.1% vs
   graph-primary 24.9–37.8% (+13 to +26pp — looks like H1 confirmed). But
   on the **rich LLM graph (I3)**, graph-primary rises to **49.8–51.1%** —
   statistical parity with the lexical base and the enhancer. The
   enhancer's apparent dominance was the lede graph being too sparse to
   traverse, not a structural advantage of the enhancer topology. With a
   good graph there is **no meaningful gap** between graph-primary and
   enhancer on this metric. H1's "beats graph-primary" is **not robust**.

2. **Enhancer vs lexical-only — REFUTED.** `(L2 − L1) = +0.0pp` for
   **every** `graph_boost_factor` (1.2/1.5/2.0) on **all three** ingest
   configs, including the rich LLM graph. The graph enhancer adds nothing
   over the lexical base. The only lift over L1 is **L4 = +1.7 to +2.1pp**,
   and that lift is the **cross-encoder reranker — not the graph**.

3. **Why clause 2 is "inconclusive by construction," not a clean
   refutation.** `_answer_hit` tests whether the gold span appears
   *anywhere* in the concatenated top-k context — it is **set-membership,
   order-blind**. `naive_boost` only **re-ranks the same candidate set** it
   inherits from `naive`; it does not change set membership at `k=20`.
   The metric is **provably incapable** of registering a pure re-rank
   enhancer. The exact `L2 ≡ L1` flatline across 3 boost factors × **3**
   ingest configs is structural proof, not noise. Only **set-changing**
   ops move the number: the reranker (different candidate pool → +~2pp);
   smart's expansion (changes the set — collapses on thin graphs, harmless
   on the rich one).

4. **The deeper finding: the metric saturates — strategy barely matters
   at k=20.** FTS-only (51.9–52.8), naive (51.1), naive_boost (51.1),
   smart-on-rich-graph (51.1), and graph-primary-on-rich-graph
   (49.8–51.1) **all land in a ~51 ± 1.5 band**. At depth 20 the 20-chunk
   set contains the gold span ~51% of the time almost regardless of how
   it was selected. The only lever that escapes the band is the
   cross-encoder reranker, and only by ~2pp. "Optimal pathway by
   answer-span@k on LoCoMo" is **largely not differentiable** at this k.

**Net:** no spin. The pre-registered topology hypothesis does not survive
contact with a good graph: graph-primary catches up to the enhancer once
extraction is decent, and the enhancer never beat the plain lexical base
on this metric in the first place. The single robust, positive lever is a
non-graph cross-encoder reranker (+~2pp). The graph earned **zero**
answer-span points in any configuration.

## Recommended pathways

### Objective 1 — max answer-span recall@k (PRIMARY)

**`L4_rerank_naive_boost` (gbf 1.5) — 53.2%, p50 ~72–85 ms.** The only cell
that beats the lexical base. Ingest config is irrelevant to the number
(I1==I2); use `none` to avoid extraction cost.

```python
from pg_raggraph import GraphRAG
rag = GraphRAG(
    dsn,
    namespace=ns,
    fact_extractor="none",        # graph adds 0 on this metric; skip the cost
    skip_extraction=True,
    embedding_provider="local",
    evolution_tier="off",
    top_k=20,
    rerank_factor=2,
    enable_graph_boost=True,
    graph_boost_factor=1.5,
)
# per query:
res = await rag.query(question, mode="naive_boost", namespace=ns, rerank=True)
```

### Objective 2 — max abstention-not-misled WITHOUT recall collapse

**No improvement is available without recall collapse — do not chase this.**
Every high-abstention cell is an **under-retrieval artifact**, not precision:
`smart b0.8/e0.5` → 100% not-misled but **0% recall, 0 chunks retrieved**;
all I1 graph-primary → 100%/0%/0 chunks. The honest operating point is the
naive base: **~28% not-misled at 51.1% recall**. Selling the 100% cells as
"precision" would be exactly the artifact the brief warned against.

```python
# Honest abstention/recall operating point — same as Objective 3 base:
res = await rag.query(question, mode="naive", namespace=ns)   # ~28% abst-ok @ 51.1%
```

### Objective 3 — best quality under latency budget (p50 ≤ 5 s)

**Budget is non-binding** — every useful cell is < 170 ms p50 (graph-primary
is ~7 ms but 0–38%). Latency-optimal *useful* pathway:

**`L1_naive` — 51.1%, p50 ~47–56 ms.** Take L4 only if +2.1pp is worth ~+25 ms.

```python
res = await rag.query(question, mode="naive", namespace=ns)   # 51.1% @ ~50 ms
```

## Honest negatives & caveats

- **Smart-mode collapse is a graph-sparsity artifact, not universal.** On
  no/thin graphs smart tanks (I1: 0–9.9% at default/high thresholds; I2:
  37.8–41.6%) because escalation routes into a graph that can't be
  traversed. On the **rich LLM graph it does not collapse** — steady 51.1%
  at every threshold. So the honest statement is: *smart is unsafe unless
  the graph is dense; even then it only matches naive (never beats it) at
  higher latency.* Default thresholds remain a poor choice on
  conversational recall regardless.
- **The primary metric cannot see re-rank enhancers** (the central finding).
  Any future "does the graph help ranking" question on LoCoMo needs a
  rank-sensitive metric (MRR / nDCG / answer-in-top-1), not answer-span@k.
- **Graph-primary underperformance is graph-quality first, scorer-artifact
  second.** The brief pre-registered the scorer artifact (graph returns
  neighborhoods, not verbatim spans). True — but the I1→I2→I3 progression
  shows the *dominant* factor is graph density: thin lede graph 24.9–37.8%,
  rich LLM graph 49.8–51.1%. Most of the gap closes with better extraction,
  not a better scorer. Do not over-attribute to the scorer.
- **Graph contributed zero answer-span points in every configuration.**
  L0–L4 are identical across I1_none / I2_lede / I3_llm at the enhancer
  levels. The graph only feeds boost (metric-blind) or expansion
  (collapses on thin, harmless on rich). Better extraction bought graph-
  *primary* parity, not any *enhancer* lift.
- **I4_llm_4o intentionally NOT run — gated on data, surfaced to user.**
  I3 (gpt-4o-mini) already drove graph-primary to lexical parity; gpt-4o
  could at best nudge ~50→~51%, still inside the ±1.5 saturation band and
  still below the reranked 52.8%. No verdict-changing power. Spending the
  larger-model budget to re-confirm a metric-construction result is not
  justified. Recommend a rank-sensitive metric instead of I4.
- **Subset scale.** Wide pass is the disclosed 2-sample subset (233
  answerable Qs, 3 ingest configs). The core effects are structural (exact
  0.0pp enhancer flatline across 3×3; saturation band) — not small-n
  wobble. Narrow pass (below) re-validates on the full set and probes
  whether a tighter `k` finally differentiates strategy.

## Status

- ✅ Wide-pass ablation ladder — I1_none + I2_lede + I3_llm_mini, k=20 —
  48 cells persisted + committed.
- ⛔ I4_llm_4o gated on data/cost (see Honest Negatives) — awaiting user
  call; recommendation is to skip in favor of a rank-sensitive metric.
- ⏳ Narrow pass: full 10-sample, k∈{10,20,40}, on I1_none + I2_lede
  (zero extra LLM spend) — re-validates pathways and tests whether smaller
  `k` escapes the saturation band. Verdict above is already robust.
