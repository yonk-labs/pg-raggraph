# Typed graph traversal & dependent conjunctive joins

*New in 0.5.x (issue #95). API: `GraphRAG.find_entities()`, `GraphRAG.traverse()`, `GraphRAG.graph_join()` — all backed by `pg_raggraph.graph_join`.*

## The problem: join questions

Some questions are **joins**, not searches:

> "Recommend a restaurant for **Maria**."

The right answer requires binding facts *about Maria* first — she lives in
Portland (`LIVES_IN`), she craves ramen (`CRAVES`) — and then intersecting two
typed neighbor sets: restaurants `LOCATED_IN` Portland **∩** restaurants that
`SERVES` ramen. That's a *dependent conjunctive join*: the second stage's
inputs are the first stage's outputs.

The embedding-seeded retrieval modes can't express this, even when the graph
contains every edge in the answer path:

- **Seeds come from the whole-question embedding** — a blend of person + city +
  food. Nothing guarantees the person anchor is among the nearest entities.
- **Expansion is type-blind, undirected, and union-only** — it accumulates a
  neighborhood (often 10–20% of the graph at 2 hops); there is no way to walk
  `LIVES_IN` specifically, then intersect `LOCATED_IN(city)` with
  `SERVES(food)`.
- **The graph's contribution to chunk scoring is binary presence** — a chunk
  touching any neighborhood entity gets the same credit as the join answer.

The adjacency tables can execute the join as two indexed self-joins plus an
intersection. These primitives expose exactly that — pure SQL over the
existing `entities` / `relationships` / `*_chunks` tables, no schema changes,
no new extensions, no app-side loops.

## The join-question pattern

```python
from pg_raggraph import GraphRAG

async with GraphRAG(dsn) as rag:
    result = await rag.graph_join(
        "Maria Ashby",                       # anchor: exact + pg_trgm fuzzy bound
        bind=[
            ("LIVES_IN", "city"),            # anchor —LIVES_IN→ $city
            (["CRAVES", "LIKES"], "food"),   # synonym list, case-insensitive
        ],
        intersect=[
            ("LOCATED_IN", "$city"),         # candidate —LOCATED_IN→ $city
            ("SERVES", "$food"),             # candidate —SERVES→ $food
        ],
        namespace="demo",
    )

    result.anchor.name                # "Maria Ashby" (score, match_type carried)
    result.bindings["city"]           # [BoundValue(name="Portland", ...)]
    result.bindings["food"]           # [BoundValue(name="ramen", ...)]
    for m in result.matches:          # candidates satisfying EVERY constraint
        print(m.name)                 # "Noodle Haven"
        for ev in m.evidence:         # one supporting edge per constraint
            print(ev.rel_type, ev.var_name, ev.edge_chunk_ids)
    result.chunk_ids()                # all provenance chunk ids, deduped
```

The whole join — every bind step, every intersect constraint, all provenance
chunk ids — executes as **one SQL statement, one round-trip**. Anchor binding
is one additional (cheap) query so failures are explainable: `anchor=None`
means "no such person"; populated `bindings` with empty `matches` means
"person found, constraints eliminated every candidate — and here's what each
leg bound".

### Plan semantics

- **`bind`** — list of `(rel_types, var)` or `(rel_types, var, direction)`.
  Each step walks one typed hop from the anchor and binds *all* matching
  neighbors to `var` (a set — multi-candidate bindings intersect naturally).
- **`intersect`** — list of `(rel_types, "$var")` or
  `(rel_types, "$var", direction)`. Each constraint produces the typed
  neighbor set of a bound variable; a candidate must appear in **every**
  constraint's set.
- **`rel_types`** — a string or a synonym list (`["LIKES", "CRAVES"]`).
  Matching is case-insensitive (`likes` edges match `LIKES`).
- **`direction`** — `"out"` (default), `"in"`, or `"any"`, always from the
  perspective of the walk origin: the anchor for `bind` steps
  (`"out"` = anchor —rel→ neighbor), the candidate for `intersect` constraints
  (`"out"` = candidate —rel→ `$var`).
- Retracted edges (fact-level evolution) never match.
- `match_limit` (default 50) caps returned candidates.

## Anchor binding: `find_entities`

Seed on a *named* entity instead of a whole-question embedding. Exact match
first (score 1.0), then `pg_trgm` fuzzy (typo- and case-tolerant, floor
`config.min_trgm_score`):

```python
matches = await rag.find_entities("Maria Ashbee", entity_type="person")
# [EntityMatch(id=…, name="Maria Ashby", score=0.61, match_type="trgm"), …]
```

`graph_join(anchor=...)` uses the same binding internally — a typo'd anchor
still completes the join. Pass an `int` entity id to skip binding entirely.

## Typed, directed walks: `traverse`

The type-aware, direction-aware counterpart of local mode's neighborhood
expansion — a recursive CTE, one round-trip:

```python
hops = await rag.traverse(
    [maria_id],
    rel_types=["LIVES_IN"],   # None = all edge types
    direction="out",          # "out" | "in" | "any"
    max_hops=1,               # capped at 10
)
# [TraversalHop(name="Portland", depth=1, rel_type="LIVES_IN",
#               weight=1.0, from_id=…, chunk_ids=(…,))]
```

Each hop carries the edge that reached it plus the edge's provenance chunk ids
(`relationship_chunks`). The same entity can appear once per distinct path.

## Cost profile

Every step is an indexed scan on the existing indexes — no new indexes needed:

- bind steps: `relationships(src_id, rel_type)` / `(dst_id, rel_type)`
  (`idx_rel_src_type` / `idx_rel_dst_type`), anchored at one entity id;
- intersect constraints: an indexed nested-loop join from the bound set into
  the same indexes;
- the intersection: a hash/merge join over candidate ids (bounded by
  `match_limit`).

`tests/integration/test_graph_join_it.py::test_join_uses_relationship_indexes_at_scale`
EXPLAIN-verifies **no sequential scan on `relationships`** at 2×10⁴ edges.
Latency is a handful of index lookups — comparable to `naive` mode, far below
`local`/`hybrid`, because it never touches embeddings.

## Honest limits

- **You supply the plan.** There is no NL→plan compiler; the caller (you, or
  an LLM agent choosing tool arguments) decides the bind/intersect shape.
  This is deliberate — the primitive stays deterministic and explainable.
- **Joins only pay off when the edges exist.** On prose corpora, pair with an
  extraction prompt that keeps join-critical edges
  (`extraction_prompt="prose"`, `fact_extractor="llm+lede"`).
- **Bind steps are single-hop from the anchor.** Chained binds
  (`$city → region`) aren't supported yet; use `traverse()` for multi-hop
  exploration.
- Results carry chunk *ids*; fetch contents from `chunks` yourself if you need
  the text (the ids join directly against `chunks.id`).
