# "Postgres 19 Has Graph Queries Now. Why Does Your Thing Exist?"

*Or: the LinkedIn DM I've gotten three times this month, answered once and for all.*

> **TL;DR.** PostgreSQL 19 ships **SQL/PGQ**: native property-graph pattern matching (`CREATE PROPERTY GRAPH` + `GRAPH_TABLE`). It is *not* GraphQL, and it is *not* a GraphRAG pipeline. It's a query syntax that gets rewritten into ordinary joins over your existing tables, which is the exact bet pg-raggraph made. So Postgres core didn't kill this project. It proved the point. The first release does fixed-depth patterns only, with no variable-length paths yet, and that happens to be the one trick our recursive-CTE traversal does that you can't write in SQL/PGQ today. Graph *syntax* was never the hard part anyway. Extraction, resolution, and hybrid retrieval are. pg-raggraph runs on **PostgreSQL 16+ today**, and when PG19 graph queries reach your managed cloud, this library gets better, not obsolete.

---

## The DM

Three different people pinged me on LinkedIn in the last couple weeks. Same question every time, give or take:

> "Hey, saw Postgres 19 is getting graph queries built in. Doesn't that make pg-raggraph kind of pointless?"

Fair question. If Postgres is growing a graph engine, why bolt a graph library onto it? I'd ask the same thing.

So let me answer it properly, with numbers to back it up. The short version is "no, and it's actually good news," but that needs about 1,500 words of unpacking. Grab a coffee.

## First, the thing everybody's mixing up

Two of those three DMs carried the same mistake. GraphQL and graph queries are not the same thing. They share four letters and nothing else.

- **GraphQL** is Facebook's API query language, an HTTP layer that sits over a schema. On Postgres you get it from extensions like `pg_graphql` (Supabase), or gateways like Hasura and PostgREST. It is not in PG19 core, and it has nothing to do with knowledge graphs.
- **SQL/PGQ**, short for "SQL Property Graph Queries" (ISO SQL:2023 Part 16), is what PG19 actually shipped. This one is graph pattern-matching *inside SQL*: `CREATE PROPERTY GRAPH`, then `GRAPH_TABLE (... MATCH (a)-[r]->(b) ...)`.

The DMs meant the second one. (One person genuinely meant GraphQL. That answer is even shorter: it's an API surface, pg-raggraph already speaks REST, MCP, and CLI, done.) SQL/PGQ is the one that lives in this project's neighborhood, so that's where we're headed.

## What SQL/PGQ actually does, and why I'm thrilled about it

The part that surprised the people DMing me? I love this feature. Not grudgingly. For real.

SQL/PGQ doesn't add a graph database to Postgres. It adds graph *syntax* that the planner turns into regular relational joins over tables you already have. Christophe Pettus described it well. A property graph is metadata that maps your existing vertex and edge tables into a node/edge view, and a `GRAPH_TABLE` pattern compiles down into a tree of joins and filters. Run `EXPLAIN` and you'll see a normal join plan. No separate engine. No new storage. Your existing indexes carry the load.

Sit with that for a second.

Adjacency tables plus joins are enough to do graph queries in Postgres. That's not my opinion. It's the official position of PostgreSQL core now, shipped in Beta 1 on June 4, 2026.

It is also, word for word, the premise this whole project was built on. Open the README. The tagline reads "no Neo4j, no Pinecone, no Apache AGE, just the Postgres you already run." pg-raggraph's graph traversal has always been recursive CTEs over an `entities`/`relationships` adjacency model. Postgres core just reached the same destination from the standards committee instead of from a benchmark harness.

Now for the part that matters most to anyone who followed the [Apache AGE saga](../../README.md#why-not-apache-age). SQL/PGQ lives **in core**. No `shared_preload_libraries`. No restart. It will run on RDS, Cloud SQL, Supabase, and Neon the moment they ship PG19, which is the one thing AGE could never pull off. SQL/PGQ is the in-core, cloud-friendly option AGE spent years failing to be. For what it's worth, I'd been telling anyone who asked that native Cypher-style graph queries weren't reaching managed Postgres through AGE. They reached it through the SQL standard instead.

So does any of this make pg-raggraph dead weight? My honest first reaction runs the other way. This is the loudest endorsement we could have hoped for. The platform we bet on just said it out loud.

## Okay then. Why does the library still need to exist?

Because graph *syntax* was never the hard part. Three reasons. The first one is the spicy one.

### 1. SQL/PGQ can't walk a variable-depth path yet

Stay with me, this is the technical heart of it.

The first PG19 release does fixed-depth patterns only. You can write "A to B to C." Three hops, three explicit arrows. What you cannot write yet is the quantified, variable-length kind: `-[:RELATES*1..5]->`, meaning "follow this edge somewhere between one and five times." That got pushed to a later release.

Here's what pg-raggraph's `local` retrieval mode does today. It lives in `src/pg_raggraph/retrieval.py` as a recursive CTE:

```sql
WITH RECURSIVE seeds AS (
    SELECT id, 1 - (embedding <=> :query_vec::vector) AS sim
    FROM entities WHERE namespace = :ns
    ORDER BY embedding <=> :query_vec::vector
    LIMIT :seed_k
),
neighborhood AS (
    SELECT id, 0 AS depth, ARRAY[id] AS path FROM seeds
  UNION ALL
    SELECT e2.id, n.depth + 1, n.path || e2.id
    FROM neighborhood n
    JOIN relationships r ON (r.src_id = n.id OR r.dst_id = n.id)
    JOIN entities e2 ON e2.id = CASE WHEN r.src_id = n.id THEN r.dst_id ELSE r.src_id END
    WHERE n.depth < :max_hops              -- variable depth: 1..N hops in ONE pass
      AND NOT (e2.id = ANY(n.path))        -- cycle guard
)
SELECT ... -- join expanded entities -> chunks -> hybrid score
```

See that `WHERE n.depth < :max_hops`? That's variable-length traversal. One query seeds from vector similarity, walks the graph an unknown number of hops with a cycle guard, then lands on the chunks to rank. SQL/PGQ can't express that shape yet. Try it in PG19 graph syntax and you'd write one `MATCH` for a single hop, another for two, another for three, then union them together. Strictly worse than the recursive CTE already sitting in the codebase.

What happens when variable-length paths finally land? Pettus again, lightly paraphrased: the rewrite will do what your recursive CTEs already do, at roughly the same speed. So the best case isn't "SQL/PGQ replaces our traversal." The best case is a prettier way to spell a traversal we already run, on a Postgres version most of you won't touch in production for a year or two.

I'll take it. It's a nice-to-have, not a tombstone.

### 2. A query language is not a pipeline

This is the reason I really want to stick, because the "isn't Postgres doing this now?" framing walks right past it.

SQL/PGQ gives you a way to *ask* a graph a question. It does not hand you the graph. Look at everything that has to happen between "here are 800 messy documents" and "here's a grounded, cited answer":

- **Chunking** that respects markdown, code, and prose boundaries.
- **Embedding** generation, local by default here, because not every workload needs to phone OpenAI.
- **Entity and relationship extraction**, where an LLM reads your text and pulls out the nodes and edges. *This is the step that creates the graph.* SQL/PGQ assumes it already exists.
- **Entity resolution**, the part that decides "Postgres," "PostgreSQL," and "the elephant database" are one node, using `pg_trgm` fuzzy matching plus vector similarity at ingest time.
- **Hybrid retrieval**, fusing vector similarity, BM25 full-text, and graph traversal into a single ranked result, with confidence routing that only escalates when the cheap path isn't sure.
- **Provenance** on every extracted fact, plus incremental updates and time and retraction awareness.

SQL/PGQ touches none of it. None.

It's the final five percent, the query you run once the graph has already been built, resolved, and embedded. pg-raggraph is the other ninety-five. I've said this for years to anyone who'll sit still: in AI land, the hard problem is always data engineering, not database choice. A tidy `MATCH` clause won't pull one entity out of one PDF.

### 3. You can't run it in production yet anyway

PG19 is in beta. GA lands around September or October 2026. Then your managed provider has to ship it, and if you've watched how slowly RDS and Cloud SQL pick up a new major version, you know that tail runs six to eighteen months. pg-raggraph runs on PostgreSQL 16 and up right now, on every provider, today. Pinning your retrieval stack to a feature that's both beta-grade and fixed-depth, and that won't reach your cloud for a year, would be a strange call.

## They don't compete. They stack.

Where I land on all this is simple, and it isn't a defensive crouch. It's the better story.

pg-raggraph's `entities` and `relationships` tables map one to one onto a `CREATE PROPERTY GRAPH` definition. Vertex table, `entities`. Edge table, `relationships`, with `src_id` and `dst_id` as the source and destination keys. The schema already has the exact shape SQL/PGQ wants. No accident, either. We both landed on the same primitive: adjacency tables.

So the roadmap more or less writes itself, and every line of it is upside:

- **Expose the knowledge graph as a property-graph view**, optionally, so power users can run their own `GRAPH_TABLE` queries against the graph pg-raggraph already built and resolved for them. We handle the messy extraction. You get standard graph syntax for free.
- **Reach for `GRAPH_TABLE` on the fixed-depth jobs** where it reads cleaner than a hand-written join, smart mode's cheap one-hop boost being the obvious candidate, behind a quick "are we on PG19?" check, with recursive CTEs still the default everywhere depth varies.
- **Ride the wave.** Every managed-Postgres vendor is about to publish some version of "you don't need a separate graph database." That sentence is our pitch. The whole market is about to spend its marketing budget warming up the exact idea this library stands on.

Convergence, not collision. Postgres core improves the foundation. pg-raggraph keeps owning the pipeline that turns raw documents into a graph worth querying in the first place.

## The honest version

I promised proof, not a pep rally, so here's the fair question turned around: where is SQL/PGQ actually better than what I've got? Ergonomics, on fixed-depth queries, once it's everywhere. A `MATCH` pattern reads nicer than a hand-rolled recursive CTE, and "the planner handles it" beats "I sure hope I got the cycle guard right." When variable-length paths ship and PG19 turns boring and ubiquitous, I'd be a bit of a fool not to offer a SQL/PGQ-backed path as an option. I won't pretend a 12-line recursive CTE is more fun to write than `-[r]->`. It isn't.

But "nicer syntax for the traversal, eventually, on a Postgres you don't have yet" is a very different sentence from "this library is obsolete." One is a feature request. The other is an obituary. We're a long way from needing one.

So, to the three of you in my DMs: no. Postgres 19 didn't make pg-raggraph redundant. It made the founding bet official, handed us a cleaner query syntax to grow into, and left the real work, building the graph in the first place, right where it has always been. Go run pg-raggraph on the Postgres 16 you've already got. And when PG19 graph queries finally surface in your RDS console? Come back. A property-graph view will be waiting.

Still want to fight about it? My DMs are open. Bring a benchmark.

---

*Related: [Why not Apache AGE?](../../README.md#why-not-apache-age) · [The A/B test that said "graph loses"](04-graph-vs-vector-the-empty-graph.md) · [What we learned building GraphRAG](00-what-we-learned-building-graphrag.md)*
