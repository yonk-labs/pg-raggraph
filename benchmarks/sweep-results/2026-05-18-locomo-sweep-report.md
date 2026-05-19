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

Marginal lift is vs **L1 (naive = vector+BM25 fusion)**, the lexical/vector base.

| Level | Pathway | I1_none | I2_lede | Δ vs L1 | p50 ms | avg chunks |
|---|---|---:|---:|---:|---:|---:|
| L0 | FTS/BM25 only (raw `ts_rank`) | 51.9 | 51.9 | +0.8 | ~0 | 20 |
| **L1** | **naive (vec+BM25)** | **51.1** | **51.1** | **—** | 47–56 | 20 |
| L2 | naive_boost · gbf 1.2 | 51.1 | 51.1 | **+0.0** | 43–55 | 20 |
| L2 | naive_boost · gbf 1.5 | 51.1 | 51.1 | **+0.0** | 46–55 | 20 |
| L2 | naive_boost · gbf 2.0 | 51.1 | 51.1 | **+0.0** | 43–55 | 20 |
| L3 | smart · b0.7/e0.4 (default) | 9.9 | 41.6 | −9.5 to −41.2 | 53–110 | 3.5 / 20 |
| L3 | smart · b0.6/e0.3 | 49.8 | 50.6 | −0.5 to −1.3 | 50–64 | ~20 |
| L3 | smart · b0.8/e0.5 | 0.0 | 37.8 | −13.3 to −51.1 | 59–120 | 0 / 20 |
| **L4** | **rerank · naive_boost gbf1.5** | **53.2** | **53.2** | **+2.1** | 72–85 | 20 |
| L4 | rerank · smart default | 9.9 | 43.8 | −7.3 to −41.2 | 79–166 | 3.5 / 20 |
| GP | local · h1/h2 | 0.0 | 37.8 | −13.3 to −51.1 | 7 / 60 | 0 / 20 |
| GP | global · h1/h2 | 0.0 | 24.9 | −26.2 to −51.1 | 7 / 58 | 0 / 14 |
| GP | hybrid · h1/h2 | 0.0 | 37.8 | −13.3 to −51.1 | 14 / 64 | 0 / 20 |

(I1_none has no graph, so all graph-dependent arms collapse to 0 — expected,
and a useful negative control.)

## H1 verdict

> **H1 (pre-registered):** a strong lexical/vector base retrieved FIRST with
> the graph applied only as a re-rank/expansion ENHANCER on top
> (`naive_boost`/`smart`) beats **both** graph-primary retrieval **and**
> lexical-only — on LoCoMo answer-span.

**Verdict: split — CONFIRMED vs graph-primary; REFUTED vs lexical-only; and
the re-rank-enhancer clause is INCONCLUSIVE BY METRIC CONSTRUCTION.**

1. **Enhancer topology ≫ graph-primary — CONFIRMED, decisively.**
   naive_boost 51.1% vs graph-primary 24.9–37.8% (I2_lede). Using the graph
   as an enhancer on a lexical base is +13 to +26pp over making the graph the
   primary retriever. The corollary H1 implies — *graph-primary is the wrong
   topology* — is strongly supported.

2. **Enhancer vs lexical-only — REFUTED on the merits available.**
   `(L2 − L1) = +0.0pp` for **every** `graph_boost_factor` (1.2/1.5/2.0) on
   **both** ingest configs, including the real lede graph (I2). The graph
   enhancer adds nothing over the lexical base. The only lift over L1 is
   **L4 = +2.1pp**, and that lift is the **cross-encoder reranker — not the
   graph**.

3. **Why clause 2 is really "inconclusive by construction," not a clean
   refutation.** `_answer_hit` tests whether the gold span appears *anywhere*
   in the concatenated top-k context — it is **set-membership, order-blind**.
   `naive_boost` only **re-ranks the same candidate set** it inherits from
   `naive`; it does not change set membership at `k=20`. Therefore the metric
   is **provably incapable** of registering a pure re-rank enhancer. The exact
   `L2 ≡ L1` flatline across 3 boost factors × 2 ingest configs is structural
   proof, not noise. Only **set-changing** operations move the number:
   - the reranker (fetches `top_k×rerank_factor`, re-trims → different set):
     **+2.1pp**;
   - smart's expansion escalation (changes the set): here it **collapses**.

   So the graph enhancer's only plausible value on this metric — ranking
   quality — is invisible to answer-span@k. H1's re-rank clause cannot be
   decided with this scorer; it is not evidence the graph is useless.

**Net:** the topology H1 advocates is the correct one (graph-primary is far
worse), but on the pre-registered primary metric the re-rank enhancer's
contribution is unmeasurable-and-zero, and the only real lift is a non-graph
cross-encoder. No spin: the graph did not earn answer-span points here.

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

- **Smart mode is a regression on this workload.** Default thresholds
  (b0.7/e0.4) tank to 9.9% (I1) / 41.6% (I2); b0.8/e0.5 → 0% (I1). Its
  escalation routes *away* from a strong naive result into graph expansion
  that loses answer-span. b0.6/e0.3 is least-bad but still ≤ naive. Smart
  should not be the default on LoCoMo-like conversational recall.
- **The primary metric cannot see re-rank enhancers** (the central finding
  above). Any future "does the graph help ranking" question on LoCoMo needs a
  rank-sensitive metric (MRR / nDCG / answer-in-top-1), not answer-span@k.
- **Graph-primary underperformance is partly the scorer artifact** the brief
  pre-registered: graph modes return entity neighborhoods, not verbatim
  spans, so a substring/token-overlap scorer structurally penalizes them.
  24.9–37.8% is not "graph is useless" — it is "answer-span can't grade
  neighborhoods." This is *why* graph-as-enhancer ≠ graph-primary.
- **lede_spacy graph did not change any answer-span number vs none.** L0–L4
  are byte-identical between I1_none and I2_lede. Consistent with the metric
  blindness — the lede graph only feeds boost/expansion, which the metric
  can't see (boost) or which collapses (expand).
- **LLM arm (I3/I4) cannot change the H1 primary-metric verdict.**
  answer-span@k's blindness to re-rank is independent of extraction quality;
  better entities only help graph-primary (already disqualified by topology)
  and smart-expansion (already collapsing). I3 (gpt-4o-mini) is being
  completed for a confirmatory contrast row. **I4 (gpt-4o) is gated**:
  spending the larger model's budget to re-confirm a metric-construction
  result is not justified by the data — recommend skipping unless a
  rank-sensitive metric is added first.
- **Subset scale.** Wide pass is the disclosed 2-sample subset (233
  answerable Qs). A full-10 narrow pass is unlikely to overturn an effect
  this structural (exact 0.0pp flatline, not a small-n wobble), but the
  recommended pathways should be re-validated on the full set before any
  external claim.

## Status

- ✅ Wide-pass ablation ladder, I1_none + I2_lede, k=20 — 32 cells persisted.
- ⏳ I3_llm_mini re-staging (tracked `bblai609x`); I3 sweep then folds in.
- ⛔ I4_llm_4o gated on cost/value (see Honest Negatives).
- ⏳ Narrow pass (top-3/objective × full 1540-Q × k∈{10,20,40}) — pending; the
  H1 verdict above is already robust without it (structural, not small-n).
