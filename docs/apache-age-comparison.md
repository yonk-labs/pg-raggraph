# pg-raggraph vs Apache AGE — a balanced comparison

**What this doc is.** An honest, feature-level comparison of pg-raggraph (adjacency tables + recursive CTEs + pgvector) and Apache AGE (Cypher graph inside Postgres), grounded in the [SCOTUS bake-off](../benchmarks/age-bakeoff/results/REPORT-VERDICT.md) where both engines ran the same inputs and were measured under identical conditions. It covers what AGE does better, what pg-raggraph is missing, when each is the right choice, and what a migration in either direction looks like.

**What this doc is not.** The advocacy pitch for our choice. That's [`why-not-apache-age.md`](why-not-apache-age.md) — the short version of our rationale. The deep architectural evaluation is [`research/apache-age-evaluation.md`](../research/apache-age-evaluation.md). This doc assumes you want to understand trade-offs, not be sold on one answer.

---

## 1. Executive summary

| axis | pg-raggraph | Apache AGE | who wins |
|---|---|---|---|
| Accuracy on SCOTUS (30 Q × 3 runs, hierarchy chunker) | 17–18 / 30 across 6 modes | 17–18 / 30 across 6 modes | tie |
| Retrieval p50 latency | 32–73 ms | 3,078–3,906 ms | **pg-raggraph (42–111×)** |
| Managed Postgres support | Every provider | Azure only | **pg-raggraph** |
| Cypher / openCypher query language | No (recursive CTEs instead) | Yes (subset) | **AGE** |
| Variable-length path syntax `[*1..N]` | No (manual CTE) | Yes | **AGE** |
| Bidirectional pattern matching ergonomics | Verbose SQL | Clean Cypher | **AGE** |
| pgvector + graph in one query | Yes, natively | No — two round-trips | **pg-raggraph** |
| Property-graph tooling ecosystem | PostgreSQL's | AGE's (smaller) | **AGE has a graph ecosystem; pg-raggraph has Postgres's full ecosystem** |
| Graph-modeling primitives (labeled multi-edges, vertex labels, etc.) | You build them in SQL | First-class | **AGE** |
| Backup / monitoring / ops tooling | Standard Postgres | Standard Postgres (same DB) | tie |
| Time to first query on a fresh managed instance | `CREATE EXTENSION pgvector, pg_trgm` — minutes | `shared_preload_libraries` + restart; only on self-host or Azure | **pg-raggraph** |
| GraphRAG-specific semantics (entity resolution, incremental ingest, chunk provenance) | Built in | You build them yourself | **pg-raggraph** |

**The short version.** AGE is genuinely better at expressing graph patterns in a query language. pg-raggraph is better at running fast, running everywhere, and combining graph traversal with vector search. On the workload we actually measured — GraphRAG retrieval on a realistic corpus — the two engines produced the same answers, but pg-raggraph did so 42–111× faster and on every managed Postgres.

Pick AGE when your workload is genuinely graph-shaped and you control the Postgres deployment. Pick pg-raggraph when you're doing GraphRAG specifically, or when you need to run on somebody else's Postgres.

---

## 2. Where AGE is genuinely better

These are the real, honest wins AGE has. None of them are small; some are decisive in specific contexts.

### 2.1 Query language for graph patterns

Cypher is a better notation for graphs than SQL. Compare finding all entities within 3 hops of a seed node:

**AGE / Cypher:**
```sql
SELECT * FROM cypher('bakeoff', $$
    MATCH (start:Entity {name: 'Miranda v. Arizona'})-[*1..3]-(connected)
    RETURN DISTINCT connected.name, connected.type
$$) AS (name agtype, type agtype);
```

**pg-raggraph / recursive CTE:**
```sql
WITH RECURSIVE graph_walk AS (
    SELECT e.id, e.name, e.entity_type, 0 AS depth, ARRAY[e.id] AS path
    FROM entities e
    WHERE e.name = 'Miranda v. Arizona'
    UNION ALL
    SELECT e2.id, e2.name, e2.entity_type, gw.depth + 1, gw.path || e2.id
    FROM graph_walk gw
    JOIN relationships r ON (r.src_id = gw.id OR r.dst_id = gw.id)
    JOIN entities e2 ON e2.id = CASE WHEN r.src_id = gw.id THEN r.dst_id ELSE r.src_id END
    WHERE gw.depth < 3
      AND e2.id != ALL(gw.path)  -- cycle detection
)
SELECT DISTINCT name, entity_type FROM graph_walk WHERE depth > 0;
```

For teams who already think in Cypher (ex-Neo4j shops, graph-first dev teams), that readability gap matters. Recursive CTEs have a learning curve, the bidirectional `(r.src_id = gw.id OR r.dst_id = gw.id)` dance is easy to get wrong, and manual cycle detection (`e2.id != ALL(gw.path)`) is a footgun.

### 2.2 Variable-length paths as a first-class operator

`[*1..N]` is genuinely elegant. Named subgraph patterns (`MATCH p = (a)-[*1..3]-(b) RETURN p`), shortest-path queries, and multi-directional bridging queries are all clean one-liners in Cypher. In SQL you write a new recursive CTE each time and carry the path around manually.

Most GraphRAG queries are 1–3 hops from a seed entity — the narrow case where recursive CTEs remain tractable. If your workload involves **arbitrary-length pattern matching across a subgraph** (e.g., "find any path, of any length, between these two topics"), AGE's primitive is the right abstraction.

### 2.3 Labeled multi-edges with typed properties

AGE's graph model has first-class labels on both vertices and edges, with `agtype` properties on each. Creating a new edge type is `MATCH (a), (b) CREATE (a)-[:NEW_LABEL {weight: 0.8}]->(b)`. In pg-raggraph's adjacency schema, edge "labels" are a `rel_type TEXT` column — you can filter on it and JSONB-store arbitrary properties, but there's no SQL-level validation that a given edge type has a given property shape. If you want typed graph schemas, AGE gives you more scaffolding to build on.

### 2.4 Bidirectional pattern matching

A query like "find entities that are a 2-hop common neighbor of both X and Y" is one line in Cypher:

```cypher
MATCH (x:Entity {name: 'X'})-[*1..2]-(shared)-[*1..2]-(y:Entity {name: 'Y'})
RETURN DISTINCT shared.name
```

In pg-raggraph, you write two recursive CTEs, INTERSECT them, and filter. It works; it's not elegant.

### 2.5 Ecosystem: tools that speak Cypher

- **Azure's managed GraphRAG solution** uses AGE; their MCP tooling assumes Cypher.
- **LightRAG** has AGE as a first-party storage backend (with known issues — see the LightRAG issue in §4).
- **Neo4j migration paths** — if you have Neo4j Cypher you want to move to Postgres, AGE is the lowest-friction path. pg-raggraph would require rewriting every query.
- **Microsoft AGEFreighter** is a data-loading library purpose-built for AGE.

pg-raggraph has **Postgres's full ecosystem** (every ORM, every driver, every observability tool), but zero graph-specific tooling. Which ecosystem matters depends on what you're building.

### 2.6 "It's a real graph database"

If you're not doing GraphRAG, if you're building a general-purpose graph application with heavy pattern matching, arbitrary-hop traversals, community detection, centrality algorithms, and a small blast radius of cloud-provider choices — AGE is a graph database living inside Postgres, and that's genuinely what you want. pg-raggraph is a retrieval library. Different problems.

---

## 3. Where pg-raggraph is genuinely better

### 3.1 Runs on every managed Postgres

| provider | AGE | pg-raggraph |
|---|---|---|
| AWS RDS | no | yes |
| Google Cloud SQL | no | yes |
| Azure Database for PostgreSQL | yes (preview) | yes |
| Supabase | no | yes |
| Neon | no | yes |
| Crunchy Bridge | unconfirmed | yes |
| Self-hosted / Docker / Railway | yes | yes |

AGE requires `shared_preload_libraries` and a Postgres restart. Only Azure supports it among major managed providers. For a library that wants to meet users where they already run, this is the single biggest architectural advantage.

### 3.2 pgvector + graph traversal in one query

This is the single most important technical reason for GraphRAG specifically. The canonical GraphRAG query is:

> Expand the subgraph around a seed entity, rank the resulting chunks by vector similarity to the user's question, return top-K.

**pg-raggraph does this in one SQL statement:**
```sql
WITH RECURSIVE neighborhood AS (
    SELECT id, 0 AS depth FROM entities WHERE name = 'quantum computing'
    UNION ALL
    SELECT e2.id, n.depth + 1
    FROM neighborhood n
    JOIN relationships r ON r.src_id = n.id OR r.dst_id = n.id
    JOIN entities e2 ON e2.id = CASE WHEN r.src_id = n.id THEN r.dst_id ELSE r.src_id END
    WHERE n.depth < 2
)
SELECT c.content, 1 - (c.embedding <=> $1::vector) AS similarity
FROM chunks c
WHERE c.entity_id IN (SELECT id FROM neighborhood)
ORDER BY c.embedding <=> $1::vector
LIMIT 20;
```

**AGE can't.** `cypher(...)` returns `agtype`; `<=>` wants typed vector columns. There's no native bridge. You run the Cypher to get node IDs, extract them in app code, then issue a second pgvector query. [AGE issue #1121](https://github.com/apache/age/issues/1121) proposes vector handling inside AGE; it's not implemented.

For a library whose entire point is "graph + vector in Postgres," this alone would be disqualifying.

### 3.3 Measured speed on realistic corpora

From the [bake-off](../benchmarks/age-bakeoff/results/REPORT-VERDICT.md), retrieval p50 on SCOTUS under the hierarchy chunker:

| mode | pg-raggraph p50 | AGE p50 | ratio |
|---|---|---|---|
| hybrid | 73 ms | 3,088 ms | 42× |
| smart | 32 ms | 3,226 ms | 101× |
| local | 65 ms | 3,079 ms | 47× |
| global | 43 ms | 3,906 ms | 91× |
| naive | 35 ms | 3,873 ms | 111× |
| naive_boost | 40 ms | 3,895 ms | 98× |

Even pg-raggraph's slowest mode (hybrid p95 = 90 ms) is **34× faster than AGE's fastest mode** (hybrid p50 = 3,088 ms). The reasons are mundane: AGE doesn't auto-create indexes, `agtype` property access is slower than typed columns, Cypher patterns often compile to sequential scans, and the planner struggles to estimate cardinality for AGE's compiled query trees.

### 3.4 Predictable query plans

Standard `EXPLAIN ANALYZE` works on our queries. The plan shows index scans on `src_id` and `dst_id`, a recursive worktable, and the pgvector HNSW/IVFFlat index. You can tune it with familiar Postgres tools. AGE's `EXPLAIN` shows its internal executor ops mixed with PostgreSQL ones — the mental model is harder. The [LightRAG #2255](https://github.com/HKUDS/LightRAG/issues/2255) incident (49.8 billion estimated rows, 17-hour migration) is a real tail risk for AGE under load; the underlying Postgres planner struggles with AGE's compiled graph patterns.

### 3.5 GraphRAG semantics out of the box

pg-raggraph ships with things AGE doesn't have opinions about — because AGE is a graph engine, not a RAG library:

- **Entity resolution** at ingest (pg_trgm fuzzy + vector cosine scoring)
- **Chunk provenance** — every fact carries `extracted | inferred | ambiguous` classification with source chunk ID
- **Hybrid retrieval modes** (naive, naive_boost, local, global, hybrid, smart) — six options tuned for different question shapes
- **Content-addressed incremental ingest** — change one doc, re-embed only its chunks, no full re-index
- **Namespace isolation** for multi-tenant deployments
- **Multiple chunker strategies** (sentence-aware, hierarchy, code-boundary) with plug-in embedders
- **Answer generation grounded in retrieved context** with LLM-provider abstraction

If you build on AGE, you write all of this yourself. That's a multi-thousand-line undertaking the bake-off data says isn't worth the investment for GraphRAG retrieval specifically.

---

## 4. What pg-raggraph is missing (honest gap list)

This is the part that's usually left out of the comparison. Here's what AGE actually has that pg-raggraph does not, in priority order.

### 4.1 Variable-length path syntax

**AGE:** `MATCH (a)-[*1..N]-(b)` is one token.
**pg-raggraph:** You write a new recursive CTE and track depth manually, with explicit cycle detection via `path` arrays. No syntactic sugar. Every new traversal shape is a new query.

**When it bites:** Deep exploratory queries, shortest-path computations, graph analytics (betweenness, centrality) beyond simple neighborhood expansion.

**Close-the-gap plan:** We could ship a small Python DSL or a set of parameterized CTE templates (`pgrg.traverse(seed=..., max_hops=3, bidirectional=True)`) that generates the recursive CTE for common cases. That's ~150 LOC and 90% of the ergonomic win. Not shipped yet; not blocked; not obviously urgent given the bake-off results.

### 4.2 Rich pattern matching (multi-directional, named subgraphs)

**AGE:** `MATCH p = (a:Author)-[:WROTE]->(paper)-[:CITES]->(other_paper)<-[:WROTE]-(b:Author)` is readable.
**pg-raggraph:** This is doable — 4 JOINs against the relationships table with explicit direction predicates — but verbose and easy to get wrong. Named subgraph patterns (capturing the whole `p`) have no equivalent; you'd aggregate arrays of IDs in the recursive term.

**When it bites:** Pattern-heavy analytical queries ("find X where pattern P exists"), not retrieval queries (which are mostly neighborhood expansion).

### 4.3 Schema-typed edges

**AGE:** Edge labels are first-class. You create tables like `bakeoff."CITES"` and `bakeoff."OVERRULES"`. The label IS the type.
**pg-raggraph:** Edges live in one `relationships` table with a `rel_type TEXT` column. No per-type table, no per-type indexes, no schema-level validation. If two edge types need different property shapes, you rely on JSONB discipline.

**When it bites:** Mixed-type heavy-write workloads where per-edge-type indexes would pay off; schemas where per-type property validation matters.

**Close-the-gap plan:** You can already add a CHECK constraint on `rel_type` and a partial index per type. We haven't productized "per-edge-type" as a first-class concept because the bake-off's 9-edge-type graph retrieved fine from one table with a `(src_id)` index.

### 4.4 A graph query language

**AGE:** openCypher (subset). Dedicated language; lots of Neo4j tutorials apply.
**pg-raggraph:** SQL. Period. Your developers write SQL, not Cypher.

This is a real cultural/team-experience consideration. If your team is mostly fluent in Cypher, pg-raggraph forces a language switch.

**There is no plan to ship a Cypher layer.** If you need Cypher, use AGE — or embed AGE alongside pg-raggraph (see §6).

### 4.5 Graph algorithms library

**AGE:** No, actually — AGE doesn't ship GDS-style algorithms (PageRank, community detection, shortest-path, centrality). You'd still build them.
**pg-raggraph:** Same. No built-in GDS equivalents.

This is a gap in both, not a differentiator. If you need community detection (Leiden, Louvain) as a *library feature*, both engines require a bring-your-own-algorithm approach or a side-car like Graphology/NetworkX.

### 4.6 Neo4j tool compatibility

**AGE:** Partial — AGE implements a subset of Cypher, so Neo4j visualization tools (Neo4j Browser, Bloom) won't work out of the box, but CLI-style Cypher developers can move over with minor changes. AGE provides the Apache AGE Viewer.
**pg-raggraph:** None. Neo4j tools don't know about us.

If you want to visualize your graph with a graph-native UI, neither engine ships that, but AGE is closer to the ecosystem.

### 4.7 The one thing pg-raggraph does better than the bake-off numbers

The bake-off measured retrieval latency and answer accuracy — it didn't measure **tail operational behavior under load**. pg-raggraph has a better story here too, but we haven't benchmarked it against AGE head-to-head. Pushing both engines to saturation, measuring throughput under concurrent reads + writes, and observing recovery from query storms is a follow-up experiment. Left out of this comparison; flagging it as a gap in the data, not a gap in the library.

---

## 5. Trade-offs: when AGE is actually the right choice

These aren't hypothetical. For each of these profiles, AGE is probably the better pick.

### 5.1 You're on Azure and doing GraphRAG

Azure Database for PostgreSQL supports AGE (in preview). You're not going to multi-cloud. Your team likes Cypher. You want Microsoft's reference architecture and managed AGE tooling. Pick AGE.

### 5.2 Your team has deep Neo4j experience and you're migrating to Postgres

Rewriting Cypher → recursive CTEs is a real engineering lift. If your codebase is 80% Cypher queries, AGE preserves most of them (allowing for the openCypher subset gaps). That's worth money.

### 5.3 You're building graph analytics, not retrieval

Community detection. Betweenness centrality. Shortest paths across large subgraphs. Recommendation-engine-style collaborative filtering via graph walks. These are pattern-heavy, multi-hop, path-shape-varied workloads. AGE's primitives are better-fit. pg-raggraph was built for RAG retrieval; we wouldn't recommend it as a GDS stand-in.

### 5.4 You genuinely need openCypher as an API surface

If you're building a system that other teams connect to with Cypher, or you want to expose a Neo4j-compatible Bolt driver, AGE is the bridge.

### 5.5 Your graph is tiny or you're prototyping

At 100 nodes, AGE and pg-raggraph are both sub-millisecond on simple queries. The latency gap only matters at scale. If you're prototyping, write whichever feels right; perf cost is rounding error.

---

## 6. Could AGE be added alongside pg-raggraph?

Yes. This is actually a reasonable architecture if you need both worlds.

The `entities` and `relationships` tables that pg-raggraph writes are **data-compatible with AGE's vertex/edge model**. A future version of pg-raggraph could ingest into BOTH schemas (adjacency tables for pgvector-composable retrieval, AGE's label tables for Cypher analytics) as an optional feature. The write cost is O(2×) at ingest; read performance is unaffected because each query path picks its own backend.

**Today:** not shipped. The design doesn't walk through the door, but it leaves it open.

**Suggested setup if you want both:**
1. Install pgvector + pg_trgm + AGE on your self-hosted or Azure Postgres.
2. Point pg-raggraph at the database; run `CREATE EXTENSION` as normal.
3. Write a small dual-write script that reads pg-raggraph's `entities` and `relationships` tables and mirrors them into an AGE graph (`bakeoff` namespace).
4. Use pg-raggraph's retrieval API for GraphRAG; drop down to Cypher for analytics queries.

We're open to upstreaming this as an optional `pgrg_age` backend if there's demand — file an issue.

---

## 7. Migration: from AGE to pg-raggraph

If you have an existing AGE-backed graph and want to move to pg-raggraph, here's the rough shape:

1. **Export vertices:** `COPY (SELECT id, properties FROM bakeoff."Entity") TO 'entities.csv' CSV HEADER;`
2. **Export edges:** similar per edge label.
3. **Transform properties:** `agtype` → standard JSON (easy — it's JSON-like already).
4. **Load into pg-raggraph's schema:** `entities(id, name, entity_type, description, properties JSONB)` and `relationships(src_id, dst_id, rel_type, weight, description, properties JSONB)`.
5. **Rewrite queries:** Cypher MATCH patterns → SQL JOINs or recursive CTEs. The [`docs/modes.md`](modes.md) explains pg-raggraph's retrieval patterns; most RAG queries won't need custom Cypher replacements.

Expected engineer-days: 2–5 for a corpus with <5 edge labels and straightforward pattern-matching queries. More if you're relying on Cypher-specific features (variable-length path queries, `OPTIONAL MATCH`, complex `WITH` pipelines).

---

## 8. Migration: from pg-raggraph to AGE

Less common, but possible. pg-raggraph's tables map cleanly to AGE labels. You'd:

1. Install AGE and create a graph namespace.
2. For each distinct `entity_type`, create a vertex label and load matching rows.
3. For each distinct `rel_type`, create an edge label and load matching rows.
4. Build equivalent indexes manually (AGE does NOT auto-index — critical).
5. Rewrite retrieval to go through Cypher, accepting the pgvector composition overhead.

We'd ask: why? The bake-off measured no accuracy benefit, and you'd trade 42–111× retrieval speed for Cypher ergonomics. Reasonable only if Cypher is genuinely more valuable to your team than latency.

---

## 9. See also

- [`why-not-apache-age.md`](why-not-apache-age.md) — the short advocacy version of this doc
- [`research/apache-age-evaluation.md`](../research/apache-age-evaluation.md) — the full architectural evaluation (pre-bake-off)
- [`benchmarks/age-bakeoff/results/REPORT.md`](../benchmarks/age-bakeoff/results/REPORT.md) — raw bake-off numbers
- [`benchmarks/age-bakeoff/results/REPORT-VERDICT.md`](../benchmarks/age-bakeoff/results/REPORT-VERDICT.md) — the mission-brief closer
- [`benchmarks/age-bakeoff/results/GRAPH-AUGMENTATION-VERDICT.md`](../benchmarks/age-bakeoff/results/GRAPH-AUGMENTATION-VERDICT.md) — the adjacent "does graph augmentation add signal?" analysis
- [`modes.md`](modes.md) — how pg-raggraph uses recursive CTEs in each retrieval mode
- [LightRAG issue #2255](https://github.com/HKUDS/LightRAG/issues/2255) — the 17-hour AGE migration cautionary tale
- [AGE issue #1121](https://github.com/apache/age/issues/1121) — the open (unimplemented) proposal for pgvector integration
