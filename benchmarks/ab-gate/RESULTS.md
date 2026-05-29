# A/B Gate — Verdict (chunkshop ↔ pg-raggraph)

> ## ⚠️ CORRECTION (2026-05-29) — read this first
>
> An earlier version of this doc claimed **"vector is never beaten across three
> corpora (SCOTUS / NTSB / MHR)."** That conclusion was **wrong for MHR and is
> retracted.** Root cause: the MHR namespace had **zero `relationships` rows** —
> the A/B materializer only ever inserted *entities*, never edges — so the
> "graph" modes there walked an **empty graph**. The MHR "graph loses / ties"
> numbers measured an empty edge table, not graph retrieval. They prove nothing.
>
> Separately, chunkshop's `lede_spacy` facts are grammatical subject-verb-object
> fragments (pronouns, truncated nouns, singletons), **not** an entity-resolved,
> traversable knowledge graph — so building edges from them wouldn't have fixed
> it either. That's a finding about *that emission*, not about GraphRAG.
>
> **The real test, on a real graph:** re-run on `bench_musique` — an
> LLM-extracted KG (9,809 typed edges: `PART_OF` / `LOCATED_IN` /
> `PARTICIPATED_IN`…; avg degree 2.25), 100 compositional 2/3/4-hop questions —
> using the library's **actual** recursive-traversal mode (`local`, `max_hops=2`).
> **Result: graph traversal BEATS pure vector by ~4-5pp** end-to-end, stable
> across two independent answer-generation runs and two judges (gemma + gpt-5-mini,
> 82% agreement): `local` 44-47% vs `naive` 39-43%. See "Real-graph multi-hop
> (MuSiQue)" below. The blogs' "graph helps multi-hop" thesis is **corroborated**,
> with honest caveats (flat retrieval recall; the lift is answer-context, not
> recall; modest magnitude). The SCOTUS / NTSB rows below stand — those are
> clean single-domain prose where single-doc lookup suffices and graph isn't
> expected to help.

**Date:** 2026-05-28/29. **Pipeline:** pg-raggraph `feat/ab-gate-real-verdict`.

## Cross-corpus summary (the headline)

| Corpus | shape | graph vs vector | reading |
|---|---|---|---|
| SCOTUS | clean legal prose | NAIVE wins / ties | single-doc lookup; graph not expected to help. Valid. |
| NTSB | clean accident reports | NAIVE wins / ties | same. Valid. |
| ~~MHR (ab-gate)~~ | ~~multi-hop news~~ | ~~"NAIVE wins"~~ | **RETRACTED — empty graph (0 edges). Measured nothing.** |
| **MuSiQue** (real KG) | **multi-hop, LLM-extracted graph** | **GRAPH (`local`) WINS +4-5pp** | the real test — graph traversal beats vector. |

## Two different harnesses — don't conflate them

There are two distinct experiments in this story, and the early confusion came
from treating the first as if it answered the second:

1. **The ab-gate harness** (`ab_gate/harness.py`) tests *chunkshop's emission*
   (`fact` rows + `cooccur` edges) via **shallow** ops only — `graph_leg`
   (1-hop: question entities → fact/cooccur naming them → parent chunk) and
   `hybrid` (rerank vector candidates by entity-overlap centrality). It has **no
   recursive CTE walk**. On clean prose (SCOTUS / NTSB) it shows shallow
   chunkshop-emission augmentation doesn't beat vector — a valid, narrow result.

2. **Deep multi-hop traversal** — follow a fact edge A→B→C across documents,
   assembling evidence along the chain — is the operation GraphRAG's thesis (and
   the yonk.dev blogs) is really about. The ab-gate harness does **not** do it.
   It IS implemented in the library (`retrieval.py:_build_local_query`,
   `WITH RECURSIVE … WHERE depth < max_hops`), tested above on `bench_musique`
   via `local` mode — and there it **beats vector by ~4-5pp**.

The retracted MHR ab-gate run failed because it combined the worst of both: it
pointed the *shallow* harness at a namespace whose edge table was *empty*. The
corrected MuSiQue run uses the *deep* library traversal on a *real* graph — and
that is the run that answers the thesis question.

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

## ~~MHR / MultiHop-RAG (ab-gate)~~ — RETRACTED (empty graph)

**This section's numbers are invalid and retracted.** The MHR namespace
(`bakeoff-mhr-ab`) had **2,288 entities but 0 `relationships`** — the A/B
materializer (`ab_gate/ingest.py:materialize_entities_from_corpus`) only ever
inserted entity nodes, never edges. The library's recursive-traversal modes
walk the `relationships` table; with zero edges there was nothing to walk, so
the harness fell back to a *shallow 1-hop metadata peek* and called it
`graph_leg`. The reported "naive 0.74 vs graph 0.40 / hybrid tie 0.74" measured
**an empty edge table against vector**, not graph retrieval. It proves nothing
about graph-vs-vector and must not be cited.

The fix is **not** "build edges from chunkshop facts" — `lede_spacy` facts are
grammatical SVO fragments (pronouns like "He"/"They", truncated objects,
~1:1 distinct surfaces), not an entity-resolved KG. The fix is a real
LLM-extracted graph + the library's real traversal → see below.

## Real-graph multi-hop (MuSiQue) — the corrected test (2026-05-29)

`bench_musique`: a genuine LLM-extracted knowledge graph — **9,809 typed edges**
(`PART_OF`, `LOCATED_IN`, `MEMBER_OF`, `PARTICIPATED_IN`, `WON`, `BORDERS`…),
8,723 nodes, avg degree 2.25, 11,792 `entity_chunks` links. 100 compositional
2/3/4-hop MuSiQue questions with gold answers. Modes run via the **library's
real** `rag.ask()` (`benchmarks/musique/run.py`): `naive` (pure vector) vs
`local` (recursive entity traversal, `max_hops=2`) + `global`/`hybrid`/
`naive_boost`/`smart`. Answer-gen: Qwen @ 192.168.1.193. Dual judge: gemma @
192.168.1.133 + gpt-5-mini (82% binarized agreement).

**EM/F1 are dead metrics here** (verbose answers; a prior run found 27% of EM=0
answers were judged fully-correct). The metrics are **support_recall**
(retrieval) and **LLM judge** (end-to-end answer quality, 0-3 → %).

| Mode | support_recall | judge (gemma) | judge (gpt-5-mini) |
|---|---:|---:|---:|
| **naive** (pure vector) | 59.3% | 40.3% | 39.0% |
| naive_boost (1-hop rerank) | 59.3% | 42.0% | 40.7% |
| **`local`** (recursive traversal) | 57.8% | **45.3%** | **44.0%** |
| global | 58.4% | 44.0% | 38.0% |
| hybrid (vector+traversal) | 59.3% | 47.7% | 39.7% |
| smart | 56.5% | 42.7% | 41.7% |

**Robust finding — `local` beats `naive` by ~4-5pp, both judges, two runs:**
gemma 45.3 vs 40.3 (+5.0), gpt-5-mini 44.0 vs 39.0 (+5.0); an earlier
independent answer-gen run had gemma 47.0 vs 43.3 (+3.7). On a real graph with
real recursive traversal, **graph traversal beats pure vector on multi-hop QA.**

**Honest caveats (do not over-claim):**
1. **Retrieval recall is FLAT** (~58-59% every mode). Graph does NOT surface
   more gold paragraphs — the lift comes from better entity-neighborhood
   *answer-context*, a softer effect than a recall win.
2. **Per-hop splits (n=33) are noise** — the two runs disagree on *which* hop
   benefits. Do NOT claim "graph helps 2-hop specifically." Only the overall
   `local` > `naive` lift is stable.
3. **Only `local` is judge-robust.** gemma rates `hybrid` best (47.7);
   gpt-5-mini rates it near-worst (39.7). `global` similar. `local` is the one
   mode both judges put above naive.
4. **Modest magnitude** (+4-5pp at ~40-45% absolute). Real, not a blowout.

Artifacts: `benchmarks/musique/_results/results-full-6mode-dual-judge.json`.
(The retracted `results-mhr/` empty-graph artifacts are kept only as the
cautionary example of materializing nodes without edges.)

## What this licenses for §3.8

§3.8 maps NAIVE WINS → "freeze edge-tier work; deprioritize Rust RM-C consumers;
reconsider whether facts/cooccur are worth maintaining." Re-weighted after the
corrected MuSiQue run, the picture splits cleanly by **what graph you build**:

- **chunkshop's `lede_spacy` facts/cooccur** (the ab-gate subject): on clean
  prose, the *shallow* ops over them don't beat vector — and the facts aren't an
  entity-resolved graph anyway. So freezing **edge-tier investment over the
  lede_spacy emission** stays defensible. That is a narrow claim about *that
  emission*, not about graph retrieval.
- **A real LLM-extracted graph + deep traversal** (MuSiQue / `local`): graph
  **does** beat vector on multi-hop (+4-5pp, both judges). So do **not**
  generalize "freeze edge work" into "graph doesn't help" — for the workload
  graph is actually for (multi-hop over a resolved KG), it helps.
- **Keep RM-C / emission primitives.** The thing that would most improve the
  win is a *better graph* (resolved entities, typed edges), which is exactly
  what RM-C-style consumers + LLM extraction produce. Retiring them would
  remove the substrate that made `local` win.

Consistent with pg-raggraph's prior benchmarks on *clean technical* corpora
(AGE bake-off, pg-agents): single vector ranking matches/beats graph there. The
corrected contribution: on a **real multi-hop KG**, recursive traversal
(`local`) beats vector — modestly, via answer-context rather than recall.

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
