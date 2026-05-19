# Operations Guide — pg-raggraph for 100s of Users

Running pg-raggraph as a shared, multi-tenant service: the known issues
that bite at scale, and the best practices that prevent them. Grounded in
the current tree (`retrieval.py`, `db.py`, `__init__.py`, `schema.sql`,
`config.py`), not generic advice.

> Embedding-layer scaling has its own doc:
> [`deployment-embedding-scaling.md`](deployment-embedding-scaling.md).
> This guide covers everything else and references it where they meet.

---

## 1. Architecture in one paragraph

One PostgreSQL instance is the entire store (documents, chunks,
embeddings, entity/relationship graph, provenance). Access is async
(`psycopg_pool.AsyncConnectionPool`). Multi-tenancy is a **`namespace`
TEXT column** on every table — there is no schema/DB isolation by
default. Retrieval composes pgvector distance + BM25 (`ts_rank`) + graph
traversal (recursive CTEs) into a single weighted SQL score. Migrations
auto-apply on first connect under an advisory lock.

Every scaling property below follows from those choices.

---

## 2. Known issues at scale (prioritized by blast radius)

### K1 — CRITICAL: the primary semantic path does not use the vector index

`_build_naive_query` (and `hybrid`, and `smart`'s naive leg) rank by a
**composite expression**:

```sql
ORDER BY  w_sem*(1-(c.embedding <=> q)) + w_bm25*ts_rank(...) + w_graph*0  DESC
LIMIT top_k
```

pgvector's HNSW index (`idx_chunk_embed`) can only satisfy a **bare**
`ORDER BY embedding <=> q LIMIT k`. A weighted arithmetic ORDER BY cannot
be served by the index, so Postgres computes the distance for **every
chunk in the namespace** and sorts — an O(rows-in-namespace) scan per
query. (The `local`/`global` modes' *seed* CTEs do use a bare-distance
`ORDER BY embedding <=> q LIMIT seed_k` and can hit HNSW; their final
ranking is still composite.)

**Consequence:** query latency scales with the size of the *largest
namespace*, not with `top_k`. Small per-tenant namespaces are fine
(observed ~50–150 ms on LoCoMo-sized data). A single large-corpus tenant
— or a shared/global namespace — degrades linearly and will dominate p99.

**Verify on your data:** `EXPLAIN (ANALYZE, BUFFERS)` a `naive` query
against a prod-size namespace; look for `Seq Scan on chunks` /
`Index Scan using idx_doc_ns` + per-row distance, *not* an HNSW index
scan.

**Mitigations (operator):**
- Keep namespaces bounded (per-user / per-project), not one giant shared
  namespace. This is the most effective lever today.
- Cap effective corpus per namespace; archive cold data.
- Prefer `local` mode where the HNSW-backed seed CTE limits the candidate
  set before composite scoring.

**Mitigation (library, recommended):** two-stage retrieval — fetch a
candidate set via bare-distance HNSW (`ORDER BY embedding <=> q LIMIT
N`), *then* re-score that candidate set with the BM25 + graph weights.
This is the standard scalable hybrid pattern and would make latency
`O(N)` instead of `O(namespace)`. Track as a library fix.

### K2 — CRITICAL: tenant isolation is application-enforced only

`_validate_namespace()` runs on every public entrypoint, but isolation
is *only* the `WHERE namespace = %(ns)s` clause the query builders add.
There is **no Postgres RLS, no schema/DB separation, no session tenant
binding**. One missing filter in any future query path, or a caller
passing an attacker-influenced namespace, is a cross-tenant data leak
with no defense-in-depth.

**Best practice:**
- Treat `namespace` as a trust boundary: derive it server-side from the
  authenticated principal, never from client input. Validate/whitelist.
- For untrusted multi-tenant SaaS, add **Postgres RLS** keyed on a
  session GUC (`SET app.tenant = ...`) as defense-in-depth, or use
  **schema-per-tenant / DB-per-tenant** (see §4 tenancy table).
- Audit every code path that builds SQL for the namespace predicate;
  add a test that fails if any query omits it.
- Never log queries/answers/chunks without tenant scoping in the log
  pipeline.

### K3 — HIGH: connection scaling & auto-migrate contention

- `pool_max` default 10 × N processes → blows Postgres `max_connections`
  fast. Front with **pgbouncer (transaction pooling)**; keep
  `PGRG_POOL_MAX` small (2–4); size Postgres for the pgbouncer pool, not
  the app process count.
- Migrations auto-apply on first `connect()` under an advisory lock. At a
  100-process deploy, all processes race the lock on boot; a slow
  migration **blocks every process's startup**. Run migrations as an
  explicit pre-deploy step (one process), then start the fleet.
- Transaction-pooling caveat: avoid session-scoped state
  (server-side cursors, `SET` that must persist) on the hot path; it
  breaks under transaction pooling.

### K4 — HIGH: ingest is the heavy, contention-prone path

Per document: chunk → embed → (LLM extraction, 1 call/chunk) → entity
resolution (pg_trgm fuzzy + vector) → graph write, in a per-document
transaction.

- LLM extraction → provider rate limits, cost, latency, outages at fleet
  ingest volume.
- Embedding CPU → see the embedding-scaling doc (local in-process model
  is N× and unbatched).
- Entity resolution compares against existing entities per namespace →
  cost grows with the tenant's entity count.
- Long per-doc transactions hold locks / a pooled connection.

**Best practice:** dedicated, *bounded* ingest workers (a queue, not the
request path); per-tenant ingest rate limits + budget caps; backpressure;
`fact_extractor=none|lede_spacy` when the LLM graph isn't needed (removes
the rate-limit/cost dependency entirely); ingest in off-peak windows;
build/repair HNSW after big bulk loads, not during.

### K5 — HIGH: unbounded tail latency

`smart` mode escalates to recursive-CTE graph expansion;
`rerank=True` adds a CPU cross-encoder (measured: a single rerank cell
over long docs took **619 s** vs ~60 s for non-rerank). Combined with K1
seq-scan, a single query's cost is highly variable.

**Best practice:** set Postgres `statement_timeout`; cap `max_hops`
(2 is usually enough); keep `rerank=False` on the hot path or bound the
candidate pool (`rerank_factor` small); per-tenant circuit-breaking so
one tenant's expensive queries can't starve the pool.

### K6 — MED: HNSW operational characteristics

- Indexes are created with **default parameters** (no `m` /
  `ef_construction` set) and there is no exposed `ef_search` tuning —
  recall/latency are un-tuned.
- The HNSW index is **global**, not per-namespace. Even where it *is*
  used (local-mode seed), filtered ANN over a multi-tenant index has the
  classic pgvector "filter + approximate search" recall problem.
- Evolution (`retract`/`supersede`) issues UPDATEs → table/index churn
  and bloat; HNSW degrades with heavy update/delete.

**Best practice:** tune `m`/`ef_construction` for your recall target
(needs a schema/index change); raise `ef_search` per session for recall;
size `maintenance_work_mem` for index builds; aggressive `autovacuum` on
`chunks`/`entities`/`relationships` (high churn under evolution);
periodic `REINDEX CONCURRENTLY` for churned HNSW indexes.

### K7 — MED: no per-tenant quotas, rate limiting, or per-tenant metrics

Nothing in the library bounds a noisy neighbor. One tenant's huge ingest
or pathological query degrades everyone (shared pool, shared CPU for
embedding/rerank, shared Postgres).

**Best practice:** enforce quotas/rate limits at your service layer
(requests/min, ingest docs/min, max corpus size per namespace); emit
per-namespace metrics (see §5) so noisy tenants are visible.

### K8 — MED: data lifecycle & compliance

Multi-tenant SaaS needs per-tenant delete/export (GDPR "delete tenant
X"). `namespace` makes targeted delete possible (`delete()` exists);
verify it cascades chunks/entities/relationships/versions. Soft-delete
via evolution accumulates rows → schedule hard GC. Backups are
whole-DB; per-namespace point-in-time export needs an app-level job.

### K9 — known ceiling: single-writer Postgres

Ingest (writes) is primary-only. Scale path: vertical first; **read
replicas for the query path** (retrieval is read-only) with the writer
reserved for ingest; eventually shard by tenant across DBs (see §4).

---

## 3. Tenancy model — the central decision

| Model | Isolation | Blast radius of K1/K2 | Ops cost | Use when |
|---|---|---|---|---|
| **Namespace column** (default) | logical only | shared seq-scan & shared blast radius; leak risk if a filter is missed | lowest (1 DB) | trusted tenants, modest per-tenant corpora, internal use |
| **Schema-per-tenant** | strong (search_path) | per-tenant tables → smaller scans, RLS-free isolation | medium (migration fan-out) | many untrusted tenants, moderate count |
| **DB-per-tenant / shard** | hardest | fully isolated perf & data | highest (fleet of DBs, routing) | large/regulated tenants, noisy-neighbor-sensitive |

For "100s of users": namespace-per-user on a few well-sized DBs, with the
biggest/regulated tenants promoted to their own DB, is the usual sweet
spot. Decide this **before** ingest — `embedding_dim` and tenancy are
both effectively immutable post-load (`schema.sql` locks `vector(dim)`
per DB; re-keying tenancy means a migration + re-ingest).

---

## 4. Deployment blueprint

```
many query workers ─┐                         ┌─ shared embedding service (TEI/Infinity)
(pg-raggraph lib,   ├─ pgbouncer ─ Postgres ──┤  (see embedding-scaling doc)
 read path)         │  (pgvector) primary     │
few ingest workers ─┘        └─ read replicas ─┘  (query path → replicas)
(queue-fed, bounded)
```

Baseline config (env), per process:

```bash
PGRG_DSN="postgresql://app:***@pgbouncer:6432/pg_raggraph"
PGRG_POOL_MAX=4                         # × workers ≤ pgbouncer pool
PGRG_EMBEDDING_PROVIDER=ollama          # shared endpoint; see embedding doc
PGRG_LLM_BASE_URL="http://embedder:80/v1"
PGRG_EMBEDDING_MODEL="BAAI/bge-base-en-v1.5"
PGRG_EMBEDDING_DIM=768
PGRG_ENV=production                     # trips the default-credential guard
# Postgres: statement_timeout, sane autovacuum, maintenance_work_mem
```

Postgres tuning checklist: `statement_timeout` (K5); `max_connections`
sized for pgbouncer not app procs (K3); `shared_buffers`/`work_mem` for
the seq-scan vector path (K1); `maintenance_work_mem` for HNSW builds
(K6); aggressive `autovacuum` on high-churn tables (K6); migrations as a
pre-deploy step (K3).

Operational discipline:
- **Migrations**: expand/contract, never edit a released migration (add a
  new numbered file — the runner tracks by filename); apply
  `CREATE INDEX CONCURRENTLY` out of band; test on prod-size data.
- **Ingest/serve split**: never run ingest (embed-heavy, long txns) on
  the request fleet.
- **Capacity model** per tenant: rows × (embedding_dim × 4 bytes + text)
  + graph rows + HNSW memory; LLM cost ≈ chunks × 1 extraction call.

---

## 5. Observability — what to watch

| Signal | Why | Alert when |
|---|---|---|
| Query p50/p99 **by mode & namespace** | K1/K5 tail; noisy tenant | p99 ≫ p50, or rising with corpus growth |
| Pool checkout wait / saturation | K3 | sustained waits |
| Postgres active conns vs pgbouncer pool | K3 | near pool ceiling |
| Ingest queue depth / lag | K4 | growing unbounded |
| LLM call rate / error / spend | K4 | rate-limit errors, budget breach |
| Rows & index size per namespace | K1/K6/K7 | a tenant dominating |
| Autovacuum / dead tuples on chunks/entities | K6 | bloat under evolution churn |
| `EXPLAIN` plan regression on naive query | K1 | seq-scan cost growth |

Per-namespace tagging is essential — without it a single noisy tenant is
invisible until it pages someone.

---

## 6. Runbook seeds

- **Latency spike** → check K1 (namespace size / plan), K5 (a `smart`/
  `rerank` query), pool saturation. Mitigate: `statement_timeout`,
  bound the offending tenant.
- **`too many connections`** → K3: pgbouncer down/misconfigured or
  `PGRG_POOL_MAX` too high; never point apps straight at Postgres.
- **Ingest backlog** → K4: LLM rate-limited or embedding CPU-bound;
  scale embedding service / throttle ingest / switch to
  `lede_spacy`/`none`.
- **Suspected cross-tenant data** → K2: audit the query path for a
  missing namespace predicate; treat as a security incident.
- **Slow deploy / stuck startup** → K3: 100 procs racing the migration
  advisory lock; move migration to a pre-deploy step.

---

## 7. Status & accuracy

- §1–§3 are verified against the current source. **K1 (composite
  ORDER BY defeats HNSW)** is a code-level mechanism; quantify the impact
  on your data with `EXPLAIN (ANALYZE, BUFFERS)` before sizing.
- Library-side fixes implied here (two-stage retrieval for K1; RLS hook
  for K2; HNSW param/`ef_search` exposure for K6; ingest backpressure for
  K4) are recommendations, not yet implemented — companion to the F-list
  in [`deployment-embedding-scaling.md`](deployment-embedding-scaling.md).
- Nothing here changes runtime behavior; it is operational guidance.
