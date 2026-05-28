# A/B Gate — Live Verdict (chunkshop ↔ pg-raggraph)

**Date:** 2026-05-28
**Verdict:** **NAIVE_WINS** (3 metrics to 0, both corpora)
**Pipeline version:** pg-raggraph `feat/ab-gate-real-verdict` (post-v0.5.0a4)

This is the real run the chunkshop emission contract §3 was written to settle:
does the graph leg (chunkshop's `lede_spacy` facts + cooccur edges, resolved
through pg-raggraph entities) beat naive vector retrieval? It does not.

## Verdict (contract §3)

| Scope | Metric | naive | graph | Δ | Label |
|---|---|---:|---:|---:|---|
| **combined** | Recall@10 | 0.875 | 0.042 | **−83.3pp** | NAIVE_WINS |
| **combined** | MRR | 0.623 | 0.042 | **−0.581** | NAIVE_WINS |
| **combined** | Judge win-rate | 0.917 | 0.208 | **−0.708** | NAIVE_WINS |
| scotus | Recall@10 | 0.750 | 0.000 | −75.0pp | NAIVE_WINS |
| scotus | MRR | 0.406 | 0.000 | −0.406 | NAIVE_WINS |
| scotus | Judge win-rate | 0.833 | 0.333 | −0.500 | NAIVE_WINS |
| ntsb | Recall@10 | 1.000 | 0.083 | −91.7pp | NAIVE_WINS |
| ntsb | MRR | 0.840 | 0.083 | −0.757 | NAIVE_WINS |
| ntsb | Judge win-rate | 1.000 | 0.083 | −0.917 | NAIVE_WINS |

§3.3 combiner: graph wins 0 of 3, naive wins 3 → **NAIVE_WINS**. §3.4 asymmetry
guard not triggered (graph loses both corpora too). All three metrics agree —
this is the least ambiguous verdict shape the contract defines.

**Latency (§3.6, informational):** naive p50 51 ms, graph p50 105 ms. Graph is
~2× slower AND lower quality, so latency doesn't change the call.

## Per §3.8 — what this means for chunkshop's roadmap

> NAIVE WINS → freeze edge-tier work; deprioritize Rust RM-C consumers;
> reconsider whether the existing facts/cooccur are worth maintaining.

This reinforces pg-raggraph's prior benchmarks (AGE bake-off, pg-agents) where
naive vector matched or beat graph traversal on clean technical corpora.

## How the run was produced

```bash
# 1. chunkshop emits facts + cooccur into its own pgvector schema (per corpus)
cd ../chunkshop/python
export CHUNKSHOP_TEST_DSN=postgresql://postgres:postgres@localhost:5434/chunkshop_test
uv run --no-sync chunkshop ingest --config <pg-raggraph>/benchmarks/ab-gate/scotus-ab.yaml
uv run --no-sync chunkshop ingest --config <pg-raggraph>/benchmarks/ab-gate/ntsb-ab.yaml

# 2. import into pg-raggraph (dim-768 DB, metadata preserved), per corpus
export PGRG_DSN=postgresql://postgres:postgres@localhost:5434/pg_raggraph_768
export PGRG_EMBEDDING_DIM=768 PGRG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
pgrg ingest-chunkshop-table --chunkshop-dsn $CHUNKSHOP_TEST_DSN --schema ab_scotus --table scotus_ab -n bakeoff-scotus-ab --skip-llm
pgrg ingest-chunkshop-table --chunkshop-dsn $CHUNKSHOP_TEST_DSN --schema ab_ntsb   --table ntsb_ab   -n bakeoff-ntsb-ab   --skip-llm

# 3. materialize graph entities from fact endpoints + cooccur nodes
pgrg ab-gate materialize -n bakeoff-scotus-ab -n bakeoff-ntsb-ab

# 4. run the matrix
pgrg ab-gate run \
  --corpus bakeoff-scotus-ab --gold ../chunkshop/docs/samples/bakeoff-scotus/gold-scotus.yaml \
  --corpus bakeoff-ntsb-ab   --gold ../chunkshop/docs/samples/bakeoff-ntsb/gold-ntsb.yaml \
  --mode naive_vector --mode graph_leg --top-k 10 --out /tmp/ab-runs

# 5. verdict with an LLM judge
export OPENAI_API_KEY=...   # gpt-4o-mini
pgrg ab-gate verdict --runs /tmp/ab-runs --out /tmp/ab-verdict \
  --judge-provider openai --judge-model gpt-4o-mini --judge-api-key-env OPENAI_API_KEY
```

Embedder note: chunkshop emits with `BAAI/bge-base-en-v1.5` (768-d) and the
pg-raggraph query side uses the same model, so naive_vector compares vectors in
one embedding space (no int8-vs-fp handicap to the baseline).

## Honest caveats (why this is "directional", not a tournament result)

These do **not** flip the verdict (a −83pp recall gap is not a measurement
artifact), but they bound how hard to lean on the magnitude:

1. **Small gold sets.** 12 questions per corpus. The contract's own gold-ntsb
   note flags this: one query flips aggregate recall@1 by ~0.08. Treat the
   *direction* as solid, the *exact deltas* as noisy.
2. **graph_leg covered only 5/12 questions per corpus.** When `lede_spacy` NER
   found no named entities in a question (common for NTSB's descriptive
   keyword queries), the harness fell back to whitespace tokens, which resolve
   poorly. The graph leg's recall ceiling was self-limited by question-term
   encoding, not just by the fact graph. A stronger query-side entity encoder
   would raise graph recall — but it starts so far behind (0.04 vs 0.88
   combined) that closing an 83pp gap is implausible without a redesign.
3. **2/12 SCOTUS gold docs absent.** The `bostock-...-decision` doc was dropped
   by pg-raggraph's content-hash dedup at import (identical concatenated text
   to a sibling doc). Symmetric across both legs (neither can retrieve it), so
   the comparison stays fair; it just caps SCOTUS recall at 10/12 for both.
4. **Materialization is 1:1 (no fuzzy collapse).** Maximizes graph reachability
   under the harness's `subject = ANY(canonical_names)` join — i.e. it favors
   graph. Graph still lost decisively.

## Artifacts

- `results/verdict.json` / `results/verdict.md` — the computed verdict.
- `results/<corpus>__<mode>.json` — raw per-cell runner output (retrieved lists).
- `results/latency.json` — per-question latency.
- `scotus-ab.yaml` / `ntsb-ab.yaml` — the chunkshop ingest configs used.
