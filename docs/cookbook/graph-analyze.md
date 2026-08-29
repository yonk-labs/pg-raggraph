# graph_analyze: set-seeded, authority-scored graph retrieval

`find_entities` binds names, `traverse` walks edges, `graph_join` intersects
typed neighbor sets. What none of them could express (issue #100) is the
"expand then rank by connectedness" shape — citation graphs, dependency
graphs, org charts:

> semantic top-K seed → typed multi-hop expansion → authority scoring
> (in-degree over the expanded set) → structured metadata filter →
> RRF-fused top-N with provenance.

`graph_analyze` runs that as **one SQL statement** (one round-trip; the
embedding call for a semantic seed is the only extra work). It is a plan
with five named stages:

```python
from pg_raggraph.graph_analyze import SemanticSeed, Expand, Authority, MetadataFilter, RRF

rows = await rag.graph_analyze(
    seed=SemanticSeed("standard for preliminary injunctive relief",
                      top_k=60, entity_type="case"),
    expand=Expand(rel_types="CITES", direction="out", max_hops=2),
    score=Authority(metric="in_degree", rel_types="CITES"),
    filter=MetadataFilter({"decision_year": ("gte", 1990)}),
    fuse=RRF(legs=("semantic", "authority")),
    top_k=10,
)
for r in rows:  # list[AnalyzedChunk], best fused score first
    print(r.chunk_id, r.document_id, r.source_path,
          r.semantic_score, r.authority, r.score)
```

## Stage semantics

- **`seed`** — where the neighborhood starts. Three forms:
  - `SemanticSeed(query, top_k=60, entity_type=None)` — the `top_k` nearest
    chunks to the (embedder-embedded) query, mapped to their linked
    entities, optionally restricted to one entity type. Entities whose
    *name* appears (near-)verbatim in the query also join the seed set
    directly via a lexical anchor leg (issue #115) — so opaque
    identifiers ("CASE-2024-0117") and near-duplicate names anchor the
    plan even when pure cosine ranking would miss them. The
    `entity_type` restriction applies to both legs;
  - `list[int]` — literal entity ids (compose with `find_entities` /
    `traverse` output);
  - `NameSeed(name, entity_type=None, fuzzy=True, limit=5)` — exact +
    `pg_trgm` fuzzy binding, the same resolution `graph_join` anchors use.
    Unbindable names return `[]` rather than raising.
- **`expand`** — typed, directed expansion, unrolled one indexed join per
  hop (`max_hops` capped at 10). `rel_types` accepts a synonym list,
  matched case-insensitively, or `None` (the default) to expand over ALL
  live edge types — the safe choice when you don't know the extraction
  vocabulary. Retracted edges never match. **Vocabulary guard (issue
  #112):** if the requested `rel_types` match zero live edges in a
  namespace that has live edges, the plan raises `ValueError` naming the
  real edge vocabulary instead of silently returning seed-only chunks.
- **`score`** — authority weighting over the expanded set. Only
  `in_degree` today: a targeted count of live `rel_types` edges INTO each
  neighborhood entity, driven by the `relationships(dst_id, rel_type)`
  index. Defaults to the `expand` types.
- **`filter`** — hard `WHERE` over `documents.metadata`, **structured
  fields only** (same guard as `query(metadata_filters={"hard": ...})`).
  Equality by default; `("gte"|"gt"|"lte"|"lt", value)` tuples for ranges.
  Numeric values compare numerically; strings as text.
- **`fuse`** — reciprocal-rank fusion of the per-leg ranks
  (`k=None` uses `config.rrf_k`). `semantic` requires a `SemanticSeed`;
  id/name-seeded plans fuse on `authority` alone.

Each result carries provenance (`chunk_id`, `document_id`, `source_path`,
document metadata) and the per-leg scores next to the fused `score` — rank
explanations don't require a second query.

## Why one statement matters

This is the cap-gold-v1 Tier 3 pipeline
(`benchmarks/age-bakeoff/cap-gold-v1/run_pipelines.py`, `PGRG_TIER3`)
promoted to API. The equivalent on Apache AGE needs **two** statements —
`cypher()` cannot consume dynamic seed ids from a CTE, so the targeted
variant string-builds a VLE from literal ids fetched in a first round-trip.
Recursive CTEs and pgvector share one query engine, so pg-raggraph composes
seed, expansion, aggregation, filter, and fusion in a single statement — a
concrete instance of the one-database, one-query thesis.

## Honest limits

- **You supply the plan.** No NL→plan compiler, same as `graph_join`.
- **`in_degree` is the only authority metric and RRF the only fusion.**
  Both are stage parameters precisely so a second metric (out-degree,
  weighted degree) can land without touching the call shape — file an
  issue with the use case.
- **Untyped expansion is broader, not smarter.** `rel_types=None` walks
  every edge type, so dense graphs pull larger neighborhoods per hop —
  type the expansion once you know the vocabulary (the vocabulary-guard
  error message lists it).
- **Authority counts edges into the *expanded set only*.** That is the
  Tier 3 semantics (rank what the seed neighborhood cites), not global
  PageRank.
