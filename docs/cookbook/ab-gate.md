# A/B Gate — graph vs. naive retrieval (chunkshop ↔ pg-raggraph)

This cookbook walks the operator through running pg-raggraph's A/B gate against a chunkshop-emitted corpus to answer the question: **does the graph leg actually beat naive vector retrieval on this corpus?**

The gate is a deterministic function of three metrics (recall@10 lift, MRR delta, LLM-judge win-rate delta) per [chunkshop emission contract §3](https://github.com/yonk-labs/chunkshop/blob/main/docs/superpowers/specs/2026-05-28-chunkshop-to-pg-raggraph-emission-contract.md#3-verdict-criteria--did-graph-beat-naive).

## Install

The judge runtime is an optional dependency:

```bash
pip install 'pg-raggraph[ab-gate]'
```

This pulls `llm-judge` (the LLM-as-judge engine). The base `pip install pg-raggraph` install is unchanged — no llm-judge sub-deps if you don't need the gate.

## Step 1 — Ingest the chunkshop A/B sample

Chunkshop ships A/B-ready ingest configs in its `docs/samples/` tree. The two pre-built corpora are `bakeoff-scotus-ab` and `bakeoff-ntsb-ab`. Each maps identity-equal to a pg-raggraph **namespace** of the same name.

```bash
# Assuming chunkshop is checked out alongside pg-raggraph:
chunkshop ingest --config /path/to/chunkshop/docs/samples/bakeoff-scotus/bakeoff-scotus-ab.yaml
```

Verify the namespace landed in pg-raggraph:

```bash
pgrg status --namespace bakeoff-scotus-ab
```

## Step 2 — Resolve entities for the gold-Q surfaces (uses #47)

The graph leg (#48 retrieval-mode harness) calls `resolve_entity_lookup` for each surface string that appears in a gold question. You can exercise the lookup directly:

```python
import asyncio
from pg_raggraph import GraphRAG, ResolvedEntity
from pg_raggraph.resolution import resolve_entity_lookup


async def lookup_demo() -> None:
    rag = GraphRAG(namespace="bakeoff-scotus-ab")
    await rag.connect()
    try:
        result: ResolvedEntity | None = await resolve_entity_lookup(
            "Marbury v. Madison",
            corpus_id="bakeoff-scotus-ab",
            db=rag.db,
            config=rag.config,
        )
        print(result)  # ResolvedEntity(id=…, …) or None
    finally:
        await rag.db.close()


asyncio.run(lookup_demo())
```

## Step 3 — Run #48 + #49 to produce runner output

> **Future tickets:** `pgrg ab-gate run` lands with [#48 retrieval-mode harness](https://github.com/yonk-labs/pg-raggraph/issues/48) + [#49 A/B runner](https://github.com/yonk-labs/pg-raggraph/issues/49). Until those ship, hand-craft an `ABRunnerOutput` JSON or use the test fixture at `tests/fixtures/ab_gate/runner_output_worked_example.json` to drive the writer.

The runner emits one JSON file per (corpus × mode) cell. Each file conforms to the `ABRunnerOutput` schema:

```python
from pg_raggraph.ab_gate import ABRunnerOutput

# Round-trips through json.dumps / json.loads via ABRunnerOutput.to_dict / .from_dict.
```

## Step 4 — Compute the verdict (#50)

```python
import json
from pathlib import Path

from pg_raggraph.ab_gate import compute_verdict, write_verdict_report

# Fixture path — exercise the verdict computation without #49.
with open("tests/fixtures/ab_gate/runner_output_worked_example.json") as fh:
    fixture = json.load(fh)["premeasured_metrics"]

verdict = compute_verdict.from_premeasured(fixture)
print(verdict.label)  # 'INCONCLUSIVE' for the §3.7 worked example.

write_verdict_report(verdict, out_dir=Path("./ab-gate-out"), latency_rows=[])
# Produces:
#   ./ab-gate-out/verdict.json — round-trippable dict
#   ./ab-gate-out/verdict.md   — human-readable summary (mirrors contract §3.7)
#   ./ab-gate-out/latency.json — informational; the verdict path never reads this file
```

The production path (`compute_verdict(runner_outputs, judge_config=...)`) lands when #49 emits real `ABRunnerOutput` files.

## Step 5 — Interpret the verdict

Per [chunkshop contract §3.8](https://github.com/yonk-labs/chunkshop/blob/main/docs/superpowers/specs/2026-05-28-chunkshop-to-pg-raggraph-emission-contract.md#38-what-inconclusive-means-for-chunkshops-roadmap):

- **GRAPH_WINS** → chunkshop greenlights Tier-2 LLM-validate edge writer + Rust RM-C code-aware port consumers.
- **NAIVE_WINS** → chunkshop freezes edge-tier work.
- **INCONCLUSIVE** → fix corpus / gold-Q coverage and re-run. Do not ship more edge tiers on inconclusive evidence.

## Tuning the gate

The thresholds are module constants — chunkshop and pg-raggraph share them by contract:

| Constant | Value | Source |
|---|---|---|
| `RECALL_AT_10_LIFT_PP` | 5.0 | contract §3.2 |
| `MRR_DELTA` | 0.05 | contract §3.2 |
| `JUDGE_WIN_RATE_DELTA` | 0.10 | contract §3.2 |

Changing any of them requires a coordinated PR per contract §5. A unit test (`tests/unit/test_ab_gate_writer.py::test_threshold_constants_match_contract`) catches silent drift.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ImportError: llm-judge is required for pg-raggraph A/B-gate verdict computation.` | The `ab-gate` optional extra isn't installed. | `pip install pg-raggraph[ab-gate]` |
| `resolve_entity_lookup` returns `None` for an obvious match | `config.resolution_threshold` (default 0.85) is too strict for the surface. | Inspect the trgm score with `psql … "SELECT similarity(name, '<surface>') FROM entities WHERE namespace = '<corpus_id>'"` and lower `resolution_threshold` if needed. |
| Verdict is always INCONCLUSIVE | Corpus is too small or gold-Q set doesn't exercise the graph leg. | Per §3.8 — fix coverage; don't loosen the thresholds. |

## Running the matrix

Once a corpus has been ingested with a chunkshop A/B config (e.g.
`bakeoff-scotus-ab.yaml`), run the retrieval-mode matrix:

```bash
pgrg --db postgresql://… ab-gate run \
    --corpus bakeoff-scotus-ab \
    --gold docs/samples/bakeoff-scotus/gold-scotus.yaml \
    --corpus bakeoff-ntsb-ab \
    --gold docs/samples/bakeoff-ntsb/gold-ntsb.yaml \
    --mode naive_vector \
    --mode graph_leg \
    --top-k 10 \
    --out runs/ab-gate-2026-05-28/
```

Pairing: pass `--corpus` and `--gold` in matched pairs (same count,
same order). Mismatched counts fail at parse time with a clear
`click.BadParameter` error.

Modes:

- **`naive_vector`** — pure ANN over chunks, fact rows excluded per
  chunkshop §4.2 (`WHERE metadata->>'kind' IS DISTINCT FROM 'fact'`).
- **`graph_leg`** — entity-resolve question terms via `resolve_entity_lookup`,
  walk fact triples and `metadata['cooccur']` edges, return the episode
  chunks carrying those facts. Only episode chunks are cited — never
  fact rows.
- **`hybrid`** — *deferred* per SC-007. Calling with `--mode hybrid`
  raises `NotImplementedError` naming issue #48. Combine
  `naive_vector` and `graph_leg` results in your downstream tooling
  if you need a blended leg today.

### Output layout

```
runs/ab-gate-2026-05-28/
├── manifest.json
├── bakeoff-scotus-ab__naive_vector.json
├── bakeoff-scotus-ab__graph_leg.json
├── bakeoff-ntsb-ab__naive_vector.json
└── bakeoff-ntsb-ab__graph_leg.json
```

The `__` separator (double-underscore) is intentional — it avoids
collisions with corpus names that contain a single underscore. Each
per-cell file follows the `ABRunnerOutput` schema in
`src/pg_raggraph/ab_gate/io.py`. The `manifest.json` lists every
file plus run timestamps and `pg_raggraph.__version__`.

### Handing off to the verdict computer

Once the matrix is written, feed the directory to the verdict computer
(from #50) to compute the GRAPH_WINS / NAIVE_WINS / INCONCLUSIVE
verdict per chunkshop §3. The verdict surface lives in
`pg_raggraph.ab_gate.compute_verdict` + `write_verdict_report`; see
the §4.1 (resolver) / §4.4 (writer) sections above.

### Reproducibility caveat

The matrix is deterministic within ANN tie-ordering noise: the same DB
state, same gold-Q files, and same modes produce the same retrieved-id
sets modulo HNSW tie shuffling. Repeated `pgrg ab-gate run` invocations
may reorder items within score ties. CI does NOT gate on bit-exact
reproducibility — too sensitive to pgvector index state and hardware.

### Optional live smoke

For an end-to-end check against a real chunkshop A/B corpus (after
ingesting via chunkshop's `bakeoff-scotus-ab.yaml`):

```bash
pgrg --db postgresql://… ab-gate run \
    --corpus bakeoff-scotus-ab \
    --gold docs/samples/bakeoff-scotus/gold-scotus.yaml \
    --mode naive_vector --mode graph_leg \
    --top-k 10 \
    --out runs/smoke/
ls runs/smoke/
cat runs/smoke/manifest.json | jq .
```

Document the result in the PR description.
