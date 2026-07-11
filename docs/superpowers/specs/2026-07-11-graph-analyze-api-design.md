# Design note: set-seeded, authority-scored graph retrieval API (#100)

Status: **proposal — awaiting greenlight.** Scoped from issue #100
(cap-gold-v1 Tier 3). This is API surface, not engine work: the SQL is proven.

## The gap

The cap-gold-v1 Tier 3 "composed analytics" slice needs, in one shot:

> semantic top-K seed → 2-hop typed expansion → citation-authority scoring
> (in-degree over the expanded set) → structured metadata filter → RRF-fused
> top-10 with provenance.

It expresses cleanly as **one** pg-raggraph SQL statement (proven in
`benchmarks/age-bakeoff/cap-gold-v1/run_pipelines.py`, `PGRG_TIER3`, lines
287–342). But no public API call runs it today:

| API | Why it can't | 
|---|---|
| `graph_join(anchor, bind, intersect, …)` | requires a **named** anchor entity; can't take a semantic top-K seed set |
| `traverse(entity_ids, rel_types, direction, max_hops, …)` | takes entity ids, returns hops; **no authority aggregation, no fusion** |
| `query(mode=…)` | no authority-scoring knob, no typed-expansion control |

So the benchmark hand-rolled the SQL. Users with the same shape (citation
graphs, dependency graphs, any "expand then rank by connectedness") would too.

## The proven statement (what any API must be able to emit)

From `PGRG_TIER3` — the shape, condensed:

```
seeds        := semantic top-K chunks (embedding <=> qvec)
seed_entities:= entities of a given type linked to those chunks
hop1, hop2   := typed directed expansion (rel_type = 'CITES') over seed_entities
hood         := seed_entities ∪ hop1 ∪ hop2
authority    := targeted in-degree over hood (count CITES edges into each node)
cand         := hood → chunks → documents, metadata filter (decision year ≥ N)
result       := RRF( rank(dist), rank(cite_count) ) → top-10 with provenance
```

Every leg is already indexed (`relationships(dst_id, rel_type)` drives the
in-degree; `entity_chunks` gives provenance). The engine does this fine — only
the **composition** has no front door.

## Two API shapes

### Option A — extend `traverse`/`graph_join` (smaller diff)

Give `traverse` a seed set that isn't just literal ids, plus an aggregation +
fusion spec:

```python
await rag.traverse(
    seed=SemanticSeed(question, top_k=60, entity_type="case"),  # or list[int]
    rel_types="CITES", direction="out", max_hops=2,
    aggregate="in_degree",           # authority weighting over the expanded set
    fuse=("semantic", "authority"),  # RRF the seed distance with the aggregate
    filter={"decision_year_min": 1990},
    top_k=10, namespace=ns,
)
```

- **Pro:** one method to learn; reuses the existing traversal SQL builder.
- **Con:** `traverse` grows from "edge walk" to "walk + aggregate + fuse +
  filter + rank" — its return type stops being `TraversalHop` and becomes a
  scored, provenance-bearing row. That's a different function wearing the same
  name; risk of a kitchen-sink signature.

### Option B — new `graph_analyze(...)` plan primitive (recommended)

A composable, plan-shaped call that names the five stages explicitly:

```python
await rag.graph_analyze(
    seed=SemanticSeed(question, top_k=60, entity_type="case"),  # semantic | ids | name
    expand=Expand(rel_types="CITES", direction="out", max_hops=2),
    score=Authority(metric="in_degree", rel_types="CITES"),
    filter=MetadataFilter({"decision_year_min": 1990}),
    fuse=RRF(("semantic", "authority"), k=60),
    top_k=10, namespace=ns,
) -> list[AnalyzedChunk]   # chunk_id, document_id, provenance, per-leg scores, fused score
```

- **Pro:** keeps `traverse`/`graph_join` small and single-purpose; the stages
  map 1:1 onto the proven CTEs, so it's a thin SQL-template assembler, not new
  engine work; leaves room for other `aggregate`/`fuse` strategies later
  without overloading an existing method.
- **Con:** one more public method + a few small dataclasses (`SemanticSeed`,
  `Expand`, `Authority`, `MetadataFilter`, `RRF`).

**Recommendation: Option B.** The composition is genuinely a new capability
(not a bigger edge-walk), and a named 5-stage plan is easier to document and
extend than a `traverse` that has quietly become a query planner. Ponytail
check: B is *more* code than A by ~5 dataclasses, but A smuggles the same
complexity into a signature that already means something else — B's cost is
honest and isolated. Start with exactly the stages Tier 3 needs; add
`aggregate` metrics / `fuse` strategies only when a second use case demands
one.

## Scope / effort

- **Engine:** none. The SQL is proven and indexed.
- **New:** `graph_analyze` in `__init__.py`, a SQL-template assembler in
  `graph_join.py` (or a new `graph_analyze.py`), the stage dataclasses, a
  `TraversalHop`-sibling result type, CLI/MCP surface parity (house rule), and
  an integration test mirroring `PGRG_TIER3` against the cap corpus.
- **Guardrails:** `SemanticSeed` embeds via the configured embedder; typed
  expansion and `rel_types` reuse the existing case-insensitive synonym
  matching; RRF reuses the `rrf_k` config + fusion code from #57.

## Citation-worthy context

Tier 3 also measured single-statement composability on both engines. Both pass,
but AGE's **targeted-traversal** variant needs 2 statements — `cypher()` can't
consume dynamic CTE seed ids, so it string-builds a VLE from literal ids fetched
in a first round-trip (`run_pipelines.py`, `age_pipeline_sql` + the 2-statement
targeted variant, lines 199–388). pg-raggraph does it in one because recursive
CTEs and pgvector share the same query. Worth citing when this API lands — it's
a concrete instance of the core "one database, one query" thesis.
