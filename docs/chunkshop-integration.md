# chunkshop integration

> Closes TODO **T-07** (direction decision) and **T-08** (documentation + lineage). Written 2026-04-20.

## The short version

- **chunkshop** (`github.com/yonk-labs/chunkshop`) is a sibling project. It is a standalone source → chunker → embedder → extractor → pgvector ingest tool.
- **pg-raggraph** does not depend on chunkshop at runtime. It has its own chunker (`src/pg_raggraph/chunking.py`) and its own embedder (`src/pg_raggraph/embedding.py`). This is deliberate — see below.
- The **age-bakeoff** (`benchmarks/age-bakeoff/`) consumes chunkshop as a uv path dep for factorial chunker × embedder experiments. That coupling is scoped to the benchmark harness only.
- When a chunker variant wins a bakeoff, port it into pg-raggraph under a `chunk_strategy` value and annotate the lineage in the code. The hierarchy chunker (shipped in `bb4dc23`) is the first instance of this.

If you're a pg-raggraph user, you do not need chunkshop. Everything works out of the box.

If you're doing benchmark or corpus-staging work, read the rest.

---

## Why two libraries, not one

**chunkshop is experimentation territory.** Its job is to let someone answer questions like "which chunker × which embedder × which int8 variant wins on this corpus" in a configurable, reproducible way. It has five chunkers, five source types, fastembed int8 + fp32, parallel orchestration, a factorial-benchmark schema. It is changing faster than pg-raggraph and has a narrower, more mechanical API surface (YAML-driven).

**pg-raggraph is product territory.** Its job is to ship a stable Python library with a clean public API (`GraphRAG.connect/ingest/query/ask/status/delete`) to app developers. It adds the graph layer (entity/relationship extraction, resolution, multi-mode retrieval) on top of whatever chunks it gets. It has an MCP server, a FastAPI reference server, a dev-knowledge-base CLI, and a CHANGELOG that a downstream user relies on not to break their setup.

These are two different use profiles. Fusing them would either:

- Drag chunkshop's chunker/embedder churn into pg-raggraph's release line (bad for stability), or
- Freeze chunkshop's experimentation pace to pg-raggraph's release cadence (bad for benchmark velocity).

Keeping them separate, with a documented port policy, preserves both.

---

## The port policy

When a chunker variant proves itself in chunkshop's factorial harness, port it into pg-raggraph. The port is **a copy, not a dependency** — chunkshop's classes are not a stable public API and we don't want pg-raggraph breaking on chunkshop's internal refactors.

The lineage lives in the code:

```python
# src/pg_raggraph/chunking.py
# Hierarchy strategy constants — ported byte-for-byte from age-bakeoff so the
# +8 SCOTUS lift reproduces. Char-based on purpose; no token-budget split.
```

For a new port, annotate the source commit and date:

```python
# Ported from chunkshop <chunkshop-sha> on <YYYY-MM-DD>; see
# chunkshop/python/src/chunkshop/chunkers/<name>.py. Kept byte-identical so
# benchmark results reproduce.
```

When chunkshop diverges from pg-raggraph's copy, the divergence is a project decision, not an accidental drift — port-forward the improvement in a pull request that names the chunkshop commit being picked up.

---

## Using chunkshop alongside pg-raggraph

### Case 1 — standard pg-raggraph workflow (recommended)

`pgrg ingest ./docs/` uses pg-raggraph's built-in chunker. Use `chunk_strategy="hierarchy"` when per-doc titles are concrete (see [user-guide § Chunking](user-guide.md#chunking)). Nothing to do with chunkshop.

### Case 2 — benchmarking a new chunker variant

Run chunkshop's factorial harness to compare variants:

```bash
cd /path/to/chunkshop/python
uv sync --extra dev
chunkshop orchestrate configs/factorial/*.yaml
chunkshop report
```

If a variant wins, open a PR against pg-raggraph that ports the chunker logic into `src/pg_raggraph/chunking.py` under a new `chunk_strategy` value, with the lineage annotation above.

### Case 3 — staging a large external corpus for bakeoff use

Chunkshop's source plugins (`files`, `json_corpus`, `pg_table`, `http`, `s3`) handle the boring part of pulling text + metadata from wherever it lives. Use chunkshop to land chunks + embeddings in a pgvector table, then hand that table off to the age-bakeoff's existing ingest path.

This is the intended workflow for the upcoming **MS workload** and **pg code (pg-src)** bakeoff additions:

1. Point chunkshop's `json_corpus` or `files` source at the raw corpus.
2. Run chunkshop's orchestrator to produce a chunked + embedded pgvector table.
3. The age-bakeoff's ingest path consumes that table for pg-raggraph and (via a similar adapter) for Apache AGE.
4. Run the standard bakeoff (`age-bakeoff run --corpus <name>` + `judge` + `report`).

No pg-raggraph library changes are required for this workflow. If future work shows we need a `GraphRAG.ingest_from_pgvector_table(...)` adapter so library users (not just bakeoff callers) can consume chunkshop output directly, that's a small addition — but it's not built today because nobody's asked for it.

### Case 4 — running chunkshop standalone

If all you want is "put chunks + embeddings into a pgvector table", use chunkshop directly. You don't need pg-raggraph at all. That's a feature, not a bug.

---

## What's NOT integrated (and why)

- **pg-raggraph does not import from chunkshop.** Deliberate. See "Why two libraries, not one" above.
- **No `GraphRAG.ingest_from_chunkshop_table()` API** — not built; YAGNI until someone asks.
- **No shared test fixtures.** Each project tests its own surface; benchmark-level equivalence is enforced by the age-bakeoff.
- **No shared release cadence.** Chunkshop ships on its own schedule. pg-raggraph ships on its own. The port policy is the synchronization mechanism.

---

## FAQ

**Q: If chunkshop's hierarchy chunker changes, does pg-raggraph's change automatically?**
No. pg-raggraph has its own copy, ported at `bb4dc23`. A chunkshop improvement is picked up by an explicit PR against pg-raggraph.

**Q: Can I use a chunkshop-produced pgvector table with pg-raggraph's retrieval?**
Not through the public SDK today. The retrieval modes query pg-raggraph's own `chunks` / `entities` / `relationships` schema. To bridge, you'd need an adapter that maps chunkshop's table schema onto pg-raggraph's — straightforward but not built.

**Q: Is chunkshop going to become part of pg-raggraph?**
No current plan. If benchmark cadence slows significantly and chunkshop's API stabilizes to the point where it's a ~free dependency, we might revisit, but the starting assumption is they stay separate.

**Q: Which chunker should I actually use?**
For pg-raggraph: `chunk_strategy="auto"` (default) handles markdown / code / prose. Switch to `chunk_strategy="hierarchy"` when per-doc titles are concrete, disambiguating nouns (see user-guide). Don't reach for chunkshop unless you're doing benchmark work or staging an external corpus.

---

## See also

- `docs/graph-direction-decision.md` — T-G1 graph-approach decision. The chunking story matters here because that decision argues good chunks do most of the retrieval work.
- `docs/user-guide.md#chunking` — user-facing documentation for `chunk_strategy`.
- `benchmarks/age-bakeoff/results/GRAPH-AUGMENTATION-VERDICT.md` — the bakeoff evidence this policy is grounded in.
- `/home/yonk/yonk-tools/chunkshop/README.md` — chunkshop's own README.
