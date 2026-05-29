# A/B Gate — PROVISIONAL Verdict (chunkshop ↔ pg-raggraph)

**Date:** 2026-05-28
**Verdict:** **NAIVE WINS vs `graph_leg`** — but ⚠️ **INCOMPLETE**: the third
contract mode (`hybrid`) was never tested. See "Scope limitation" below.
**Pipeline version:** pg-raggraph `feat/ab-gate-real-verdict` (post-v0.5.0a4)

This run answers a narrower question than the contract's §3 gate: does
**graph-as-primary retrieval** (`graph_leg` — entity-resolve the question, then
walk facts/cooccur) beat naive vector? No. But the contract (§4.2) defines
**three** modes, and the production-shaped one — `hybrid` (vector seeds the
candidate set, graph expands/reranks) — is `NotImplementedError` in the harness
and was not run. **The §3.8 directive must not be honored on this evidence.**

> ## ⚠️ Scope limitation — `hybrid` mode untested
>
> Contract §4.2 lists three modes: `naive_vector`, `graph_leg`, `hybrid`. This
> run tested the first two — the extremes of the design space (vector-only vs
> graph-only). It did **not** test `hybrid`, which is the mode chunkshop's
> facts/cooccur emission was designed to feed.
>
> Why this is decisive, not cosmetic: `graph_leg` fails by construction when
> question NER is weak — it must entity-resolve the *question* to seed the
> walk, and NTSB's descriptive keyword queries (and ~3/12 SCOTUS questions even
> after the query-encoder fix) yield no resolvable entities → forced misses.
> `hybrid` has a completely different failure profile: the vector leg seeds
> candidates, so the graph never has to entity-resolve the question — it only
> expands/reranks what vector already found. A large part of the −75pp gap is
> an artifact of "graph-as-primary needs entity-rich queries," **not** an
> indictment of the facts/cooccur data.
>
> Tracking: pg-raggraph issue (implement + A/B-test `hybrid`). Until that lands,
> this verdict is "naive beats graph-as-primary," NOT "naive beats graph."

## Results vs `graph_leg` (contract §3 metrics, 2 of 3 modes)

These numbers use the improved query-term encoder (`_expand_entity_terms`,
2026-05-28) which lifted `graph_leg` SCOTUS coverage from 5/12 → 9/12 questions.

| Scope | Metric | naive | graph_leg | Δ | Label |
|---|---|---:|---:|---:|---|
| **combined** | Recall@10 | 0.875 | 0.125 | **−75.0pp** | NAIVE_WINS |
| **combined** | MRR | 0.623 | 0.088 | **−0.535** | NAIVE_WINS |
| **combined** | Judge win-rate | 0.917 | 0.250 | **−0.667** | NAIVE_WINS |
| scotus | Recall@10 | 0.750 | 0.167 | −58.3pp | NAIVE_WINS |
| scotus | MRR | 0.406 | 0.093 | −0.313 | NAIVE_WINS |
| scotus | Judge win-rate | 0.833 | 0.417 | −0.417 | NAIVE_WINS |
| ntsb | Recall@10 | 1.000 | 0.083 | −91.7pp | NAIVE_WINS |
| ntsb | MRR | 0.840 | 0.083 | −0.757 | NAIVE_WINS |
| ntsb | Judge win-rate | 1.000 | 0.083 | −0.917 | NAIVE_WINS |

§3.3 combiner (naive vs graph_leg): graph wins 0 of 3 → NAIVE_WINS. But this is
a 2-mode comparison; the contract's gate is over all three modes.

**Latency (§3.6, informational):** naive p50 51 ms, graph_leg p50 105 ms.

> _Earlier run (pre-encoder-fix) reported combined recall −83.3pp / graph_leg
> 5/12 SCOTUS coverage. The encoder fix narrowed it to −75pp / 9/12 — direction
> unchanged, magnitude reduced. Both predate the hybrid mode being tested._

## Per §3.8 — what this does and does NOT license

§3.8 maps NAIVE WINS → "freeze edge-tier work; deprioritize Rust RM-C consumers;
reconsider whether facts/cooccur are worth maintaining." **That directive is
NOT triggered by this run**, because the experiment didn't test `hybrid` — the
mode where the emission was designed to win. Discarding CS-5 provenance, CS-1
extractor coverage, or RM-C ports on this evidence would be acting on an
incomplete experiment. The directional finding (graph-as-primary < naive) is
consistent with pg-raggraph's prior benchmarks (AGE bake-off, pg-agents), but
the roadmap call waits on the `hybrid` result.

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

## Honest caveats

**The headline caveat is the untested `hybrid` mode (top of doc) — that's what
makes this verdict provisional, not just "directional."** The rest bound the
magnitude of the `naive` vs `graph_leg` comparison that WAS run:

1. **Small gold sets.** 12 questions per corpus. The contract's own gold-ntsb
   note flags this: one query flips aggregate recall@1 by ~0.08. Treat the
   *direction* as solid, the *exact deltas* as noisy.
2. **`graph_leg` is graph-as-PRIMARY — wrong mode for the data.** It must
   entity-resolve the *question* to seed the walk. After the query-encoder fix
   (`_expand_entity_terms`) coverage rose to 9/12 (SCOTUS) and 6/12 (NTSB), but
   descriptive keyword questions still yield no resolvable entities → forced
   misses. This is exactly the failure `hybrid` avoids (vector seeds the
   candidates; graph only expands them). The −75pp gap is substantially an
   artifact of testing graph in its worst-fit mode.
3. **2/12 SCOTUS gold docs absent.** The `bostock-...-decision` doc was dropped
   by pg-raggraph's content-hash dedup at import (identical concatenated text
   to a sibling doc). Symmetric across both legs, so the comparison stays fair;
   it just caps SCOTUS recall at 10/12 for both.
4. **Materialization is 1:1 (no fuzzy collapse).** Maximizes graph reachability
   under the harness's `subject = ANY(canonical_names)` join — i.e. it favors
   graph. graph_leg still lost — but again, in its worst-fit mode.

## Artifacts

- `results/verdict.json` / `results/verdict.md` — the computed verdict.
- `results/<corpus>__<mode>.json` — raw per-cell runner output (retrieved lists).
- `results/latency.json` — per-question latency.
- `scotus-ab.yaml` / `ntsb-ab.yaml` — the chunkshop ingest configs used.
