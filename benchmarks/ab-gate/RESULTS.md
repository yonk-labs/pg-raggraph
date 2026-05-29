# A/B Gate — Complete Verdict (chunkshop ↔ pg-raggraph)

**Date:** 2026-05-28 (3-mode run; supersedes the earlier 2-mode provisional)
**Verdict:** **NAIVE WINS** — across *both* graph modes, graph never wins a
single metric. But the two modes tell very different stories (see below).
**Pipeline:** pg-raggraph `feat/ab-gate-real-verdict`

This run tests **all three** modes the chunkshop emission contract §4.2 defines
— `naive_vector`, `graph_leg` (graph-as-primary), and `hybrid`
(graph-as-augmentation: vector seeds candidates, graph reranks them by entity
overlap). The earlier run tested only the first two; chunkshop correctly flagged
that the production-shaped `hybrid` mode — the one the facts/cooccur emission was
designed to feed — was missing. It's now implemented and tested.

## Headline: two graph modes, two stories

| Comparison | Recall@10 Δ | MRR Δ | Judge Δ | §3.3 verdict |
|---|---:|---:|---:|---|
| naive vs **`graph_leg`** (graph-as-primary) | **−75.0pp** | **−0.535** | **−0.667** | NAIVE_WINS 3–0 (blowout) |
| naive vs **`hybrid`** (graph-as-augmentation) | −12.5pp | −0.113 | **−0.042 → TIE** | NAIVE_WINS 2–0–1 (near-parity) |

**The nuance that matters for §3.8:** `graph_leg` loses catastrophically, but
`hybrid` is *near parity* — it **ties on answer quality** (the LLM judge: 0.875
vs 0.917 combined; SCOTUS exactly 0.833 = 0.833) and loses retrieval only
slightly. So the honest reading is **not** "graph is useless/harmful" — it's
"**graph doesn't earn its cost on these corpora.**" Even in its best mode the
graph layer is, at most, neutral here; the simple centrality reranker slightly
drags recall by demoting a few gold docs that vector alone ranked higher.

## naive vs `hybrid` (the decisive, production-shaped comparison)

`hybrid` = `naive_vector` seeds the top-30 candidates, then they're reranked by
graph centrality (how many fact/cooccur nodes each candidate's doc shares with
*other* retrieved docs). It never entity-resolves the question — so it has full
12/12 coverage on both corpora, unlike `graph_leg`.

| Scope | Metric | naive | hybrid | Δ | Label |
|---|---|---:|---:|---:|---|
| **combined** | Recall@10 | 0.875 | 0.750 | −12.5pp | NAIVE_WINS |
| **combined** | MRR | 0.623 | 0.510 | −0.113 | NAIVE_WINS |
| **combined** | Judge win-rate | 0.917 | 0.875 | −0.042 | **TIE** |
| scotus | Recall@10 | 0.750 | 0.583 | −16.7pp | NAIVE_WINS |
| scotus | MRR | 0.406 | 0.306 | −0.100 | NAIVE_WINS |
| scotus | Judge win-rate | 0.833 | 0.833 | ±0.000 | **TIE** |
| ntsb | Recall@10 | 1.000 | 0.917 | −8.3pp | NAIVE_WINS |
| ntsb | MRR | 0.840 | 0.715 | −0.125 | NAIVE_WINS |
| ntsb | Judge win-rate | 1.000 | 0.917 | −0.083 | **TIE** |

Combiner: naive wins recall + MRR, judge ties → NAIVE_WINS, but by small
margins and with answer quality tied. **Hybrid did not beat naive on any
metric — but it didn't lose answer quality either.**

## naive vs `graph_leg` (graph-as-primary)

| Scope | Metric | naive | graph_leg | Δ | Label |
|---|---|---:|---:|---:|---|
| **combined** | Recall@10 | 0.875 | 0.125 | −75.0pp | NAIVE_WINS |
| **combined** | MRR | 0.623 | 0.088 | −0.535 | NAIVE_WINS |
| **combined** | Judge win-rate | 0.917 | 0.250 | −0.667 | NAIVE_WINS |

`graph_leg` must entity-resolve the *question* to seed its walk, so it fails by
construction on weak-NER questions (NTSB descriptive queries; ~3/12 SCOTUS even
after the query-encoder fix). Coverage: SCOTUS 9/12, NTSB 6/12. This is graph in
its worst-fit mode — the −75pp gap is largely that artifact, which is exactly
why `hybrid` (no question NER) was the comparison that mattered.

**Latency (§3.6, informational):** naive p50 51 ms, graph_leg 105 ms, hybrid
~110 ms (two queries + rerank).

## What this licenses for §3.8

§3.8 maps NAIVE WINS → "freeze edge-tier work; deprioritize Rust RM-C consumers;
reconsider whether facts/cooccur are worth maintaining." The complete 3-mode
run **supports** that direction — naive wins or ties every metric in both
comparisons; graph wins nothing. But weight the nuance honestly:

- It is **not** evidence that facts/cooccur are *harmful* — hybrid ties on
  answer quality. It's evidence they don't *help enough to justify the cost* on
  these two clean technical corpora.
- The `hybrid` reranker is a **simple, untuned centrality heuristic** (entity
  overlap among retrieved docs). A relevance-tuned graph reranker, or a
  larger/messier corpus with real cross-document entity reasoning, could shift
  the hybrid result. This run does not rule that out.
- n = 24 questions. The hybrid deltas (−12.5pp, −0.11) are small enough to be
  partly noise; the judge tie is the most robust signal and it says "parity."

Consistent with pg-raggraph's prior benchmarks (AGE bake-off, pg-agents): on
clean technical corpora a single vector ranking matches or beats graph. The
new contribution here is showing it holds in the *production-shaped hybrid mode*,
not just graph-as-primary — and that hybrid's loss is parity-grade, not a rout.

## How the run was produced

```bash
# corpora already emitted by chunkshop into schemas ab_scotus / ab_ntsb and
# imported into pg_raggraph_768 (namespaces bakeoff-scotus-ab / -ntsb-ab),
# entities materialized (3851 + 22). Then:
export PGRG_DSN=postgresql://postgres:postgres@localhost:5434/pg_raggraph_768
export PGRG_EMBEDDING_DIM=768 PGRG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
pgrg ab-gate run \
  --corpus bakeoff-scotus-ab --gold .../gold-scotus.yaml \
  --corpus bakeoff-ntsb-ab   --gold .../gold-ntsb.yaml \
  --mode naive_vector --mode graph_leg --mode hybrid --top-k 10 --out runs/

export OPENAI_API_KEY=...   # gpt-4o-mini judge
pgrg ab-gate verdict --runs runs/ --out v-hybrid   --graph-mode hybrid   --judge-provider openai --judge-model gpt-4o-mini --judge-api-key-env OPENAI_API_KEY
pgrg ab-gate verdict --runs runs/ --out v-graphleg --graph-mode graph_leg --judge-provider openai --judge-model gpt-4o-mini --judge-api-key-env OPENAI_API_KEY
```

Embedder: chunkshop emits + pg-raggraph queries with the same `BAAI/bge-base-en-v1.5`
(768-d), so naive_vector compares vectors in one space.

## Caveats

1. **Small gold sets** — 12 Q/corpus; treat direction as solid, exact deltas as
   noisy. The hybrid judge tie is the most robust signal.
2. **`hybrid` reranker is a v1 heuristic** — entity-overlap centrality, untuned.
   Not the last word on graph-as-augmentation; a relevance-aware reranker is the
   obvious next experiment.
3. **2/12 SCOTUS gold docs absent** (content-hash dedup at import) — symmetric
   across all modes; caps SCOTUS recall at 10/12 for everyone.
4. **`graph_leg` materialization is 1:1** (favors graph reachability). It still
   lost — in its worst-fit mode.

## Artifacts

- `results/verdict-naive-vs-hybrid.{json,md}` — the decisive comparison.
- `results/verdict-naive-vs-graphleg.{json,md}` — graph-as-primary.
- `results/<corpus>__<mode>.json` — raw per-cell runner output (3 modes × 2 corpora).
- `results/latency.json`, `results/manifest.json`.
- `scotus-ab.yaml` / `ntsb-ab.yaml` — chunkshop ingest configs.
