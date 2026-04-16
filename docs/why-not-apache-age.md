# Why Not Apache AGE?

Apache AGE is the obvious-looking answer for "graph database in PostgreSQL." It adds Cypher and a graph data model on top of standard PostgreSQL tables. We evaluated it carefully and chose **adjacency tables + recursive CTEs** instead. This guide explains why.

For the full evaluation with benchmarks, query plans, and source links, see [`research/apache-age-evaluation.md`](../research/apache-age-evaluation.md). This doc is the short version.

## TL;DR

| | Apache AGE | Adjacency + Recursive CTEs |
|---|---|---|
| Cloud providers (managed PG) | Azure only | All of them |
| Install | Restart PG, edit `shared_preload_libraries` | None — standard SQL |
| pgvector in the same query | No (two round-trips) | Yes (one query) |
| 1–3 hop traversal speed | 2–40× slower | Fast with normal indexes |
| Query debugging | `agtype`, custom errors | Standard `EXPLAIN` |
| Required for GraphRAG | No | — |

For the query patterns GraphRAG actually runs — seed entity → expand 1–3 hops → rank chunks by vector similarity — AGE is slower, less portable, and harder to integrate with pgvector than plain SQL. It is a real graph database; it is the wrong tool for this job.

## 1. Cloud Compatibility Is a Hard Wall

AGE installs as a `shared_preload_libraries` extension, which requires a PostgreSQL restart and a config edit. That excludes almost every managed PostgreSQL service:

| Provider | AGE? |
|---|---|
| Azure Database for PostgreSQL | Yes (Public Preview) |
| AWS RDS | No |
| Google Cloud SQL | No |
| Supabase | No |
| Neon | No |
| Crunchy Bridge | Unconfirmed |
| Self-hosted / Docker / Railway | Yes |

pg-raggraph aims to be a library you can drop into any PostgreSQL deployment. A hard dependency on AGE would make it unusable for anyone on RDS, Cloud SQL, Supabase, or Neon — which is most of the market. pgvector, by contrast, is supported almost everywhere.

## 2. AGE and pgvector Don't Compose

This is the single most important technical reason for a GraphRAG library specifically.

The core GraphRAG operation is:

> Find entities related to X within N hops, then rank associated text chunks by vector similarity to the query.

With recursive CTEs, this is one SQL query:

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

One round-trip. PostgreSQL plans the whole thing.

With AGE, you cannot mix `MATCH ... RETURN` with `ORDER BY <pgvector_distance>`. Cypher results are wrapped in `agtype`, vector operators want plain columns, and there is no native bridge. You end up running a Cypher query, extracting node IDs in application code, and then issuing a second pgvector query — or wrapping AGE's output in SQL and paying for the conversion. There is an open proposal ([AGE issue #1121](https://github.com/apache/age/issues/1121)) for vector handling inside AGE; it is not implemented.

For a library whose entire reason for existing is "pgvector + graph traversal in one place," that is disqualifying.

## 3. Performance Is Not What You'd Expect

People assume "purpose-built graph engine" means "faster traversals." For 1–3 hop queries on a properly indexed adjacency table, the opposite is true.

Published benchmarks show recursive CTEs beating AGE Cypher by **2–4× on small datasets** for simple traversals, and one social-graph benchmark found them **40× faster** for 4-hop queries. The reasons are mundane:

- AGE does **not** auto-create indexes. You must manually create BTREE indexes on `id`, `start_id`, `end_id`, plus GIN indexes on `properties`, for every label table.
- `agtype` property access goes through `agtype_access_operator`, which is slower than touching a typed column.
- Cypher patterns frequently compile into nested loops with sequential scans on vertex tables.
- The PostgreSQL planner has trouble estimating cardinality for AGE's compiled query trees.

The most public failure mode is [LightRAG issue #2255](https://github.com/HKUDS/LightRAG/issues/2255): a routine `get_all_edges()` migration produced a query plan with **49.8 billion estimated rows** for ~681K actual results, and the migration ran for **17+ hours** with the server down. The issue is still open. This is exactly the kind of operational risk a library should not impose on its users.

GraphRAG queries are 1–3 hops on graphs with a few hundred to a few hundred thousand nodes. That is not the regime where a graph engine pulls ahead. It's the regime where a `JOIN` on an indexed integer column is hard to beat.

## 4. Cypher Looks Nice. The Rest Doesn't.

The honest case for AGE is readability. This:

```sql
SELECT * FROM cypher('knowledge', $$
    MATCH (start:Entity {name: 'quantum computing'})-[*1..3]-(connected)
    RETURN DISTINCT connected.name
$$) AS (name agtype);
```

is genuinely nicer than the equivalent recursive CTE. If your team thinks in Cypher, that matters.

But the rest of the experience is rough:

- AGE implements a **subset** of openCypher. `ON MATCH SET`, `datetime()`, `EXISTS { subquery }`, `NOT (pattern)` in `WHERE`, and several other Neo4j-isms aren't supported. You get syntax errors when following Neo4j tutorials.
- Errors reference internal AGE function names, not your Cypher.
- `EXPLAIN` output shows PostgreSQL nested loops, not graph operations.
- `agtype` serialization adds friction at every API boundary.
- `ag_catalog` must be in your `search_path` per session.
- `agtype_build_map` caps at 50 fields per call. Vertices with more than 50 properties need workarounds.
- Project health signals are mixed: inconsistent release cadence, an "AGE in Production" issue closed as `not planned` after 74 days of silence, and unanswered questions about PG17/PG18 support timelines.

For most GraphRAG queries, the cleaner Cypher syntax is not worth the surrounding tax.

## 5. The Adjacency-Table Approach Is Already Proven

The [`postgres-graph-rag`](https://github.com/h4gen/postgres-graph-rag) library by h4gen implements full GraphRAG using nothing but standard tables, JSONB, recursive CTEs, and pgvector. It claims 10× speedups over LLM-agent traversal approaches and supports atomic incremental ingestion. It exists. It works. It validates the architecture pg-raggraph uses.

Our schema is the same shape AGE uses internally — `entities` and `relationships` tables with JSONB `properties` and proper indexes on `src_id`, `dst_id`, `name`, `entity_type`, plus an HNSW/IVFFlat index on the embedding column. The only difference is that we never go through Cypher compilation, never serialize through `agtype`, and never give up the ability to run on RDS.

## When AGE Would Make Sense

To be fair, AGE is a real project solving real problems. Reach for it if:

- You're already deploying on Azure Database for PostgreSQL.
- Your queries involve genuinely complex pattern matching — bidirectional variable-length paths with edge-type filters, named subgraph patterns, that kind of thing.
- You're building a general-purpose graph application, not GraphRAG specifically.
- Your team has deeper Cypher experience than SQL experience and finds recursive CTEs unreadable.

For a GraphRAG library aiming at broad PostgreSQL support and tight pgvector integration, none of those apply.

## Could AGE Be Added Later?

Yes, optionally. The adjacency table schema is data-compatible with AGE's vertex/edge model. If a future use case demanded complex Cypher patterns, AGE could be wired in as an optional backend over the same physical tables — without forcing it on anyone who runs on RDS, Supabase, or Neon. The current design leaves that door open. It just doesn't walk through it by default.

## See Also

- [`research/apache-age-evaluation.md`](../research/apache-age-evaluation.md) — the full evaluation with benchmark numbers and source links
- [`modes.md`](modes.md) — how the recursive-CTE traversal is actually used in pg-raggraph's retrieval modes
- [LightRAG issue #2255](https://github.com/HKUDS/LightRAG/issues/2255) — the 17-hour migration cautionary tale
- [AGE issue #1121](https://github.com/apache/age/issues/1121) — the open (unimplemented) proposal for pgvector integration
