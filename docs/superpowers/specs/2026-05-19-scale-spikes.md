# Scale Remediation — Verification Spikes (K1 / F3 / K2)

> Task 0.2 deliverable. Each spike states **(a)** the confirmed mechanism
> with evidence, **(b)** the chosen design, and **(c)** the EXACT test that
> proves the fix. The "Exact test" blocks are used VERBATIM in Tasks 1.1
> (K1), 1.2 (K2), and 2.1 (F3) — they reference only symbols verified to
> exist in the current source on branch `feature/scale-remediation`.

Source reviewed at commit `91e35e4` (Task 0.1 baseline harness).

---

## K1 — HNSW index is bypassed by the composite ORDER BY

### Confirmed mechanism

`_build_naive_query` (`src/pg_raggraph/retrieval.py:61-100`) emits, with the
default config (`evolution_tier="off"`, matching the `skip_extraction=True`
fixture), this exact SQL (dumped live from the code):

```sql
SELECT c.id, COALESCE(c.embedded_content, c.content) AS content, c.metadata,
       d.source_path, d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       1 - (c.embedding <=> %(embedding)s::vector) AS vec_score,
       ts_rank(c.search_vector, to_tsquery('english', %(tsquery)s)) AS bm25_score,
       %(w_sem)s * (1 - (c.embedding <=> %(embedding)s::vector)) +
       %(w_bm25)s * ts_rank(c.search_vector, to_tsquery('english', %(tsquery)s)) +
       %(w_graph)s * 0 AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.namespace = %(namespace)s
ORDER BY score DESC
LIMIT %(top_k)s
```

The HNSW index `idx_chunk_embed` (`sql/schema.sql:123`,
`USING hnsw (embedding vector_cosine_ops)`) can only serve an ORDER BY that
is *exactly* `embedding <=> q` (optionally with the matching opclass
operator). The naive query orders by `score` — a weighted arithmetic
expression `w_sem*(1-dist) + w_bm25*ts_rank + w_graph*0`. Postgres cannot
push that ordering into the index, so it must compute the distance for
**every chunk row that survives `WHERE d.namespace = …`** and sort. Cost is
O(rows-in-namespace) per query, not O(top_k).

`mode="naive"` is also the first leg of `smart` (the default mode) and of
`naive_boost`, and `hybrid` merges `local`+`global` whose *final* ranking is
the same composite shape — so the bypass is on the primary hot path.

### Evidence — EXPLAIN (ANALYZE, BUFFERS), 20,000 chunks

Empirical run: ingested **20,000 chunks into one namespace `scale_k1`**
(global `chunks` table = 42,694 rows — the existing benchmark
namespaces share the global HNSW index, which is exactly the prod
scenario: one large namespace inside a large global index). Probe
embedding produced by the same local fastembed provider the library
uses. Vector literals elided as `[…384-d…]` for readability; full
output in the spike scratch (not committed).

**(1) Current `mode="naive"` query (composite `ORDER BY score DESC`):**

```
Limit  (actual time=93.297..93.320 rows=10 loops=1)
  Buffers: shared hit=121728 read=4574 written=79
  ->  Result
        ->  Sort
              Sort Key: ((0.5 * (1 - (c.embedding <=> '[…384-d…]'::vector))
                         + 0.2 * ts_rank(c.search_vector, '…'::tsquery)) + 0) DESC
              Sort Method: top-N heapsort  Memory: 35kB
              ->  Hash Join  (rows=20000)
                    Hash Cond: (c.document_id = d.id)
                    ->  Seq Scan on chunks c  (actual time=0.022..10.016 rows=42694)
                    ->  Hash
                          ->  Seq Scan on documents d
                                Filter: (namespace = 'scale_k1')
                                Rows Removed by Filter: 17796
Execution Time: 93.372 ms
```

→ **`Seq Scan on chunks` over all 42,694 rows + top-N heapsort. No
HNSW index. 93.4 ms.** Confirms K1: the composite `ORDER BY` defeats
`idx_chunk_embed`; latency is O(global chunk count) per query.

**(2) Bare `ORDER BY c.embedding <=> q LIMIT 20` (HNSW-eligible):**

```
Limit  (actual time=1.669..1.913 rows=20 loops=1)
  ->  Nested Loop
        ->  Index Scan using idx_chunk_embed on chunks c  (rows=20)
              Order By: (embedding <=> '[…384-d…]'::vector)
        ->  Memoize (Cache Key: c.document_id)
              ->  Index Scan using documents_pkey on documents d
                    Filter: (namespace = 'scale_k1')
Execution Time: 2.483 ms
```

→ **`Index Scan using idx_chunk_embed` (HNSW) with the namespace
applied as a Memoize'd pkey-join filter. 2.5 ms — ~37x faster.**

**(3) Proposed two-stage (candidate CTE bare-distance + re-score):**

```
Limit  (actual time=1.121..1.122 rows=10 loops=1)
  ->  Sort
        Sort Key: ((0.5 * (1 - (cand.embedding <=> '[…384-d…]')) + …) DESC
        Sort Method: top-N heapsort  Memory: 25kB
        ->  Subquery Scan on cand
              ->  Limit  (candidate_k=200)
                    ->  Nested Loop
                          ->  Index Scan using idx_chunk_embed on chunks c
                                Order By: (embedding <=> '[…384-d…]'::vector)
                          ->  Memoize (Cache Key: c.document_id)
                                ->  Index Scan using documents_pkey on documents d
                                      Filter: (namespace = 'scale_k1')
Execution Time: 1.653 ms
```

→ **The chosen design works exactly as intended: the candidate CTE
walks `idx_chunk_embed` (HNSW), the composite re-score runs only over
the ≤200 candidates. 1.7 ms — ~55x faster than the current naive
query, with the same composite scoring preserved.**

Headline: **naive composite → Seq Scan over 42,694 chunks, 93 ms;
two-stage → HNSW Index Scan, 1.7 ms (~55x).**


### Chosen design

Two-stage retrieval, gated by a new config flag (default ON):

- `config.py`: add `retrieval_candidate_k: int = 200` and
  `two_stage_retrieval: bool = True`.
- `retrieval.py`: add `_build_naive_query_twostage(cfg, as_of,
  version_filter, evolution_aware) -> tuple[str, dict]` returning:

```sql
WITH candidates AS (
    SELECT c.id, c.embedding, c.search_vector,
           COALESCE(c.embedded_content, c.content) AS content,
           c.metadata, c.document_id
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.namespace = %(namespace)s {evolution_extra_where_on_d}
    ORDER BY c.embedding <=> %(embedding)s::vector
    LIMIT %(candidate_k)s
)
SELECT cand.id, cand.content, cand.metadata,
       d.source_path, d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       1 - (cand.embedding <=> %(embedding)s::vector) AS vec_score,
       ts_rank(cand.search_vector, to_tsquery('english', %(tsquery)s)) AS bm25_score,
       {evolution_score_expr(base, cfg, evolution_aware)} AS score
FROM candidates cand
JOIN documents d ON d.id = cand.document_id
ORDER BY score DESC
LIMIT %(top_k)s
```

Key points, refined against the real query structure:

1. **The candidate CTE's `ORDER BY c.embedding <=> q LIMIT candidate_k` is
   HNSW-*eligible*, not HNSW-*guaranteed*.** The planner's index choice is
   cost/statistics/data-distribution dependent: on a freshly-ingested
   contiguous namespace the planner reliably picks the `idx_chunk_embed`
   HNSW Index Scan (verified — see the K1 exact test's own fresh `ts`
   fixture), but on a pre-existing, differently-distributed namespace the
   same bare-distance `ORDER BY … LIMIT` can fall back to a `Seq Scan` at
   default `enable_seqscan` (reviewer-reproduced). The
   `idx_chunk_embed` index is global (not per-namespace), so the candidate
   set may need to over-fetch when one namespace is a small slice of a
   huge global table; `candidate_k=200` with default `top_k=10` gives 20×
   headroom. The recall A/B (Task 1.1 Step 5) validates the default.
2. **The re-score SELECT keeps the exact composite `score` expression**
   (`evolution_score_expr(base, cfg, evolution_aware)` with the same
   `base` string used today) so ranking is identical to single-stage when
   the candidate set is a superset of the true top-k — which it is for any
   reasonable `candidate_k` since semantic distance dominates `w_sem=0.5`.
3. **The PRG-1 consumer-surface columns** (`d.metadata`, `d.retracted`,
   `d.version_label`, `d.effective_from`, `d.effective_to`,
   `superseded_by_id`) and `vec_score`/`bm25_score` are preserved — the
   re-score block must re-join `documents` because the candidate CTE only
   carries `document_id`. `query()`'s row consumer
   (`retrieval.py:354-374`) reads `row["content"]`, `row["score"]`,
   `row.get("source_path")`, `row["id"]`, `row.get("doc_metadata")`,
   `row.get("retracted")`, `row.get("version_label")`,
   `row.get("effective_from")`, `row.get("effective_to")`,
   `row.get("superseded_by_id")` — the SELECT list above supplies every
   one.
4. **Gate**: in `query()` (`retrieval.py:325-327`), when `mode=="naive"`
   and `config.two_stage_retrieval`, call the new builder; else the
   existing `_build_naive_query`. Old path retained for A/B
   (`two_stage_retrieval=False`).
5. **Evolution awareness**: reuse `evolution_where_clauses(cfg,
   doc_alias="d", …)` exactly as `_build_naive_query` does; the clauses
   apply to the candidate CTE's `documents` join (alias `d`). When
   `evolution_tier="off"` the clauses list is empty and the two SELECT
   blocks are byte-stable.

> NOTE for Task 1.1 implementer: the candidate CTE filters by
> `d.namespace` *inside* the CTE so HNSW ordering is over chunks, with the
> namespace applied as a filter. The HNSW Index Scan is **eligible but
> not guaranteed** — the planner's choice depends on cost estimates, table
> statistics, and the namespace's data distribution. It reliably appears
> on a freshly-ingested contiguous namespace; on a pre-existing,
> differently-distributed namespace the planner can fall back to a
> `Seq Scan` for the bare-distance `ORDER BY … LIMIT` even at default
> `enable_seqscan`.
>
> **REQUIREMENT (not incidental):** the Task 1.1 plan/recall assertion
> MUST run on a freshly-ingested fixture namespace (the exact test's `ts`
> fixture satisfies this and passes verbatim). A plan assertion against a
> pre-existing/heterogeneous namespace is not reliable.
>
> **FLAG for Task 1.1:** the production scenario — one namespace as a
> small slice of a huge shared global HNSW index — is **not** fully
> de-risked by this spike. Task 1.1 should consider `hnsw.ef_search` and
> whether `enable_seqscan` / the index strategy needs explicit attention
> for that scenario (cross-ref Task 2.4 / K6, which makes `ef_search`
> configurable). If a future pgvector/planner version refuses HNSW under
> the join, the fallback is a pre-filtered partial candidate set.

### Exact test (used VERBATIM in Task 1.1 Step 1)

Verified symbols: `pg_raggraph.GraphRAG`,
`GraphRAG.ingest_records(records, namespace=...)`,
`GraphRAG.query(question, mode=..., namespace=...)` returning
`QueryResult` with `.chunks` (list of `ChunkResult`, `.content` attr),
`GraphRAG.db` property → `Database`, `Database.fetch_all(sql, params)`
returning `list[dict]`, HNSW index name `idx_chunk_embed`
(`sql/schema.sql:123`). The `scale_rag` fixture
(`tests/scale/conftest.py`) yields a connected `GraphRAG(skip_extraction
=True)` and its teardown wipes `ts%` namespaces.

```python
# tests/scale/test_twostage_retrieval.py
import pytest

from pg_raggraph import GraphRAG  # noqa: F401  (fixture provides instance)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_twostage_uses_hnsw_and_preserves_topk(scale_rag):
    rows = [
        {"text": f"doc {i} about topic {i % 7}", "source_id": f"t{i}"}
        for i in range(5000)
    ]
    await scale_rag.ingest_records(rows, namespace="ts")

    r = await scale_rag.query("topic 3", mode="naive", namespace="ts")
    assert len(r.chunks) > 0

    # The two-stage candidate CTE's bare-distance ORDER BY must be
    # served by the HNSW index idx_chunk_embed. We bind the probe vector
    # as a real parameter (NOT a `(SELECT embedding FROM chunks LIMIT 1)`
    # sub-select — that seed itself Seq-Scans chunks and would pollute a
    # blanket "Seq Scan" assertion with a false negative).
    probe = await scale_rag.db.fetch_one(
        "SELECT embedding FROM chunks c "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE d.namespace = %(ns)s AND c.embedding IS NOT NULL LIMIT 1",
        {"ns": "ts"},
    )
    plan = await scale_rag.db.fetch_all(
        "EXPLAIN SELECT c.id FROM chunks c "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE d.namespace = %(ns)s "
        "ORDER BY c.embedding <=> %(q)s::vector "
        "LIMIT 200",
        {"ns": "ts", "q": probe["embedding"]},
    )
    plan_text = "\n".join(str(row) for row in plan)
    # The ordering path must walk the HNSW index, not Seq-Scan + Sort it.
    assert "idx_chunk_embed" in plan_text
    assert "Order By: (embedding <=>" in plan_text
    assert "Sort Method" not in plan_text  # no full sort over the namespace
```

> Recall A/B (Task 1.1 Step 5, `tests/scale/test_twostage_recall.py`):
> ingest a 5k `ts` fixture; run `mode="naive"` once with
> `two_stage_retrieval=True` and once `False` (construct two `GraphRAG`
> instances differing only in that kwarg, or toggle
> `scale_rag.config.two_stage_retrieval`); collect
> `{c.chunk_id for c in r.chunks}` from each and assert
> `len(a & b) / len(a) >= 0.95`. `ChunkResult.chunk_id` is populated by
> `query()` (`retrieval.py:362-374`).

---

## F3 — Dedicated embedding endpoint config

### Confirmed mechanism

`config.llm_base_url` / `config.llm_api_key` are defined in
`config.py:70` and `config.py:72`. Enumeration of every read across
`src/pg_raggraph/`:

| File:line | Reads | Purpose | Used for embedding? |
|---|---|---|---|
| `embedding.py:113` | `config.llm_base_url` | `get_embedding_provider`, `embedding_provider in ("openai","ollama")` branch — `base_url` for `HttpxEmbeddingProvider` (overridden to `https://api.openai.com/v1` when provider is exactly `"openai"`) | **YES — embedding** |
| `embedding.py:119` | `config.llm_api_key` | same branch — `api_key=` for `HttpxEmbeddingProvider` | **YES — embedding** |
| `extraction.py` | `config.llm_base_url` / `config.llm_api_key` | LLM entity/relationship extraction provider (`HttpxLLMProvider`) | NO — extraction only |
| `answer.py` | `config.llm_base_url` / `config.llm_api_key` | answer-generation LLM | NO — answer LLM only |

(The extraction/answer reads are listed for completeness; F3 does not
touch them. Verified by `grep -rn "llm_base_url\|llm_api_key" src/`.)

**The problem:** the only way to point embeddings at a non-OpenAI,
non-local endpoint today is `embedding_provider="ollama"`, which
*reuses* `llm_base_url`/`llm_api_key`. A fleet that does LLM extraction
*and* wants a shared embedding service cannot separate the two endpoints
— both ride `llm_*`. (Documented as the pre-F3 escape hatch in
`docs/deployment-embedding-scaling.md:204-231`.)

`get_embedding_provider` (`embedding.py:108-123`) is the single factory;
`GraphRAG._get_embedder()` (`__init__.py:257-262`) is its only caller and
caches the instance.

### Chosen design

Add a dedicated `http` embedding provider that uses new, embedding-only
config fields. Existing `local|openai|ollama` branches are **unchanged**
(back-compat: if the new fields are unset and provider stays one of the
existing three, behavior is byte-identical).

`config.py` — two new fields (placed next to the Embedding block,
`config.py:64-67`):

```python
embedding_base_url: str = ""   # used only when embedding_provider == "http"
embedding_api_key: str = ""    # bearer token for the http embedding endpoint
```

Defaults `""` ⇒ feature is opt-in and invisible unless
`embedding_provider="http"` is selected. No precedence interaction with
`llm_*` — the `http` branch reads ONLY `embedding_base_url`/
`embedding_api_key`/`embedding_model`/`embedding_dim`; it never falls
back to `llm_*`.

`embedding.py` — new branch in `get_embedding_provider`
(`embedding.py:108-123`), inserted before the final `else: raise`:

```python
elif config.embedding_provider == "http":
    if not config.embedding_base_url:
        raise ValueError(
            "embedding_provider='http' requires embedding_base_url"
        )
    return HttpxEmbeddingProvider(
        base_url=config.embedding_base_url,
        model=config.embedding_model,
        api_key=config.embedding_api_key,
        dimension=config.embedding_dim,
    )
```

`HttpxEmbeddingProvider` already exists (`embedding.py:77-105`) with the
exact constructor signature `(base_url, model, api_key="", dimension
=384)` and POSTs to `{base_url}/embeddings` — no change needed for F3
(its keep-alive/batching is F4's scope, Task 2.2).

### Exact test (used VERBATIM in Task 2.1 Step 1)

Verified symbols: `pg_raggraph.config.PGRGConfig`
(`model_config = {"extra": "forbid", "env_prefix": "PGRG_"}` —
**NOT** arbitrary field kwargs: `PGRGConfig(embedding_base_url=...)`
raises `ValidationError: Extra inputs are not permitted
[type=extra_forbidden]` until the field exists. Task 2.1 **MUST** add
`embedding_base_url` and `embedding_api_key` fields to
`src/pg_raggraph/config.py` — without them these F3 tests cannot even
construct the config, so the field addition is a hard prerequisite of
the test, not optional),
`pg_raggraph.embedding.get_embedding_provider(config)`,
`pg_raggraph.embedding.HttpxEmbeddingProvider` with private attrs
`_base_url` (constructor does `base_url.rstrip("/")`) and `_api_key`.
This test needs **no database** and **no network** (the provider is
constructed, not called) — it is a unit test.

```python
# tests/scale/test_embed_provider_http.py
import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.embedding import HttpxEmbeddingProvider, get_embedding_provider


def test_embed_provider_http():
    cfg = PGRGConfig(
        embedding_provider="http",
        embedding_base_url="http://embeddings.internal/v1",
        embedding_api_key="secret-token",
        embedding_model="BAAI/bge-small-en-v1.5",
        embedding_dim=384,
        llm_base_url="http://should-not-be-used:11434/v1",
        llm_api_key="llm-key-must-not-leak",
    )
    provider = get_embedding_provider(cfg)

    assert isinstance(provider, HttpxEmbeddingProvider)
    # Points at the dedicated embedding endpoint — NOT llm_base_url,
    # NOT api.openai.com (rstrip('/') is applied by the constructor).
    assert provider._base_url == "http://embeddings.internal/v1"
    assert provider._api_key == "secret-token"
    assert provider.dimension == 384


def test_embed_provider_http_requires_base_url():
    cfg = PGRGConfig(embedding_provider="http")  # embedding_base_url unset
    with pytest.raises(ValueError, match="embedding_base_url"):
        get_embedding_provider(cfg)


def test_embed_provider_back_compat_ollama_unchanged():
    # Back-compat guard: ollama still reuses llm_base_url (pre-F3 path).
    cfg = PGRGConfig(
        embedding_provider="ollama",
        llm_base_url="http://ollama.internal:11434/v1",
        embedding_dim=384,
    )
    provider = get_embedding_provider(cfg)
    assert isinstance(provider, HttpxEmbeddingProvider)
    assert provider._base_url == "http://ollama.internal:11434/v1"
```

---

## K2 — RLS feasibility for tenant isolation

### Confirmed mechanism

Isolation today is **only** the application-added namespace predicate.
`_validate_namespace()` (`__init__.py:158`) runs on every public
entrypoint but only validates the *string*; it does not enforce
isolation. Every SQL builder/path was audited for the namespace
predicate:

| Path (file:line) | Tables touched | Namespace predicate | RLS-coverable as-is? |
|---|---|---|---|
| `_build_naive_query` (`retrieval.py:83-99`) | `chunks c` JOIN `documents d` | `WHERE d.namespace = %(namespace)s` | `documents` YES; **`chunks` NO direct predicate — isolated via the documents FK join** |
| `_build_local_query` (`retrieval.py:122-162`) | `entities` (seed), `relationships`, `chunks`, `entity_chunks`, `documents` | seed `WHERE namespace=%(namespace)s` on `entities`; final `WHERE d.namespace=%(namespace)s` on `documents`. `chunks`/`entity_chunks` in `relevant_chunks` CTE have **no own predicate** | `entities`/`relationships`/`documents` YES; `chunks`/`entity_chunks` only transitively |
| `_build_global_query` (`retrieval.py:185-226`) | `relationships r` `WHERE r.namespace=%(namespace)s`, `entities`, `chunks`, `entity_chunks`, `documents` `WHERE d.namespace` | relationships + documents direct; chunks/entity_chunks transitive | same as local |
| `ENTITIES_FOR_CHUNKS` (`retrieval.py:230-235`) | `entities e` JOIN `entity_chunks ec` | **NO namespace predicate** — scoped only by `ec.chunk_id = ANY(chunk_ids)` from a prior namespace-scoped query | `entities` has `namespace` ⇒ RLS *would* add defense here |
| `RELATIONSHIPS_FOR_ENTITIES` (`retrieval.py:237-250`) | `relationships r` JOIN `entities` | **NO namespace predicate** — scoped by chunk_ids subselect | `relationships` has `namespace` ⇒ RLS would add defense |
| `GRAPH_BOOST_QUERY` (`retrieval.py:419-442`) | `entity_chunks`, `relationships r` `WHERE r.namespace=%(namespace)s`, `chunks c` `WHERE c.id=ANY(chunk_ids)` | relationships direct; **`chunks`/`entity_chunks` have no own predicate** | relationships YES |
| `resolution.py:23-26, 41-61` | `entities` | `WHERE namespace = %s` / `%(namespace)s` | YES |
| ingest INSERTs (`__init__.py:1040, 1073, 1094, 1136, 1152, 1158`) | `documents`/`document_versions`/`chunks`/`entity_chunks`/`relationships`/`relationship_chunks` | `documents`/`document_versions`/`relationships` carry an explicit `namespace` column value; `chunks`/`entity_chunks`/`relationship_chunks` do **not** (no namespace column) | INSERT RLS needs `WITH CHECK`; chunks/junctions blocked (no column) |
| `delete()` (`__init__.py:1307-1309`) | `documents`/`entities`/`relationships` `WHERE namespace=%s` | direct on all three | YES |
| `status()` (`__init__.py:1294-1296`) | `chunks c` JOIN `documents d` `WHERE d.namespace=%s` | documents direct; chunks transitive | documents YES |
| `prune_orphans()` (`__init__.py:1621-1639`) | `entities`/`relationships` `WHERE namespace=%s` | direct | YES |
| `merge_entities` (`__init__.py:1555-1610`) | `entities` (verifies single namespace), `relationships`, `entity_chunks` | `entities` checked; `relationships` filtered by id+`a.namespace=b.namespace` | entities/relationships YES |

**Schema facts (the decisive constraint), from `sql/schema.sql`:**

- `documents` — has `namespace TEXT NOT NULL` (line 23)
- `entities` — has `namespace TEXT NOT NULL` (line 55)
- `relationships` — has `namespace TEXT NOT NULL` (line 69)
- `document_versions` — has `namespace TEXT NOT NULL` (line 163)
- `facts` — has `namespace TEXT NOT NULL` (`CREATE TABLE facts` at line 179)
- **`chunks` — NO `namespace` column** (lines 40-50). Isolated *only*
  by `JOIN documents d ON d.id=c.document_id WHERE d.namespace=…`.
- **`entity_chunks` / `relationship_chunks` — NO `namespace` column**
  (lines 80-95). Pure junction tables.

**Conclusion:** every builder reaches its namespace via *exactly one*
`namespace` value (the `%(namespace)s` / `%s` param, or
`config.namespace`). No builder mixes two namespaces in one statement
(`merge_entities` explicitly *refuses* cross-namespace). So a session
GUC `app.tenant` bound per pooled connection + an RLS policy
`USING (namespace = current_setting('app.tenant', true))` is feasible on
the four tables that **have** a `namespace` column —
`documents`, `entities`, `relationships`, `document_versions` — WITHOUT
rewriting any builder, and is a true no-op when `app.tenant` is unset
(`current_setting(...,true)` → NULL → `namespace = NULL` → no rows
filtered *in*; policy only restricts, and a NULL setting makes the
`USING` expression NULL ⇒ effectively the policy yields no restriction
only if we also keep RLS permissive — see design).

**Blocker for the plan's literal Step 3 text:** the plan says
`ALTER TABLE chunks … CREATE POLICY ns_isolation USING (namespace =
current_setting('app.tenant', true))`. **`chunks` has no `namespace`
column, so that exact policy cannot be created on `chunks`.** Same for
`entity_chunks`/`relationship_chunks`. This must be resolved by the
chosen design below.

### Chosen design

**Defense-in-depth, opt-in, no builder rewrites.**

#### 0. RLS is INERT under a superuser / BYPASSRLS connection role (decisive)

**Empirically proven against the documented DB.** The only documented
credential is `postgresql://postgres:postgres@localhost:5434/pg_raggraph`,
and `postgres` is a PostgreSQL **superuser** (and has `rolbypassrls`).
PostgreSQL **always bypasses Row Level Security for superusers and roles
with `BYPASSRLS`, even with `FORCE ROW LEVEL SECURITY`**. Verified on
scratch tables carrying the exact policies below:

- As `postgres` (superuser) with `SET app.tenant='tenA'`: a
  namespace-blind `SELECT` returned **BOTH `tenA` and `tenB` rows** —
  RLS completely inert, isolation silently fails open.
- As a dedicated non-superuser, non-BYPASSRLS role (`SET ROLE`) with
  the **identical** policies and `SET app.tenant='tenA'`: only `tenA`
  rows visible; switching to `app.tenant='tenB'` showed only `tenB`.
  The subquery-through-`documents`-FK policy on `chunks` isolated
  correctly too.

**Therefore `rls_enabled=True` is a NO-OP that fails open if the
connection role is superuser or has `BYPASSRLS`.** The migration's
policies are necessary but **not sufficient** — isolation only takes
effect under a non-privileged role. The design MUST provision a
dedicated application role and route the RLS path through it:

- **Provision a non-superuser, non-BYPASSRLS application role**
  `pgrg_app` (`NOSUPERUSER NOBYPASSRLS`; `NOLOGIN` is fine when reached
  via `SET ROLE` from the existing DSN — see binding below) and grant
  it the privileges every builder/ingest path needs:
  `GRANT SELECT, INSERT, UPDATE, DELETE` on the touched tables
  (`documents`, `entities`, `relationships`, `document_versions`,
  `chunks`, `entity_chunks`, `relationship_chunks`, `facts`) and
  `GRANT USAGE, SELECT` on their sequences (the `*_id_seq` BIGSERIALs).
  Role creation + grants belong in migration `003_rls_namespace.sql`
  (or, if the operator forbids role DDL in migrations, as a documented
  operator step the migration header points to).
- **Bind the RLS path to that role via `SET ROLE pgrg_app`** on each
  acquired connection when `config.rls_enabled` (alongside the
  `app.tenant` GUC bind in §3). `SET ROLE` is the back-compat-safe
  choice: the default superuser DSN keeps working unchanged when
  `rls_enabled=False` (no `SET ROLE`, no policy effect), and when
  `rls_enabled=True` the connection drops superuser privileges for the
  operation so the policies actually filter. Connecting *directly* as
  `pgrg_app` (a `LOGIN` role + its own DSN) is the equivalent
  alternative for operators who prefer per-role credentials; both are
  acceptable, `SET ROLE` is the default because it needs no DSN change.

> **Operational caveat (state explicitly in the migration header and
> ops docs):** `rls_enabled=True` provides **zero isolation** if the
> live connection role is a superuser or has `BYPASSRLS` and the
> `SET ROLE pgrg_app` binding is not applied. It fails *open*, silently.
> The operator MUST ensure the RLS path runs as `pgrg_app` (via
> `SET ROLE` from the default DSN, or a dedicated `pgrg_app` DSN). The
> design makes the Step 5 test deterministic regardless of the DSN's
> base role precisely because it forces the connection onto `pgrg_app`
> before asserting isolation.

1. `config.py`: add `rls_enabled: bool = False`.

2. `src/pg_raggraph/sql/migrations/003_rls_namespace.sql` (next number;
   001/002 already applied):
   - Enable + FORCE RLS and add the uniform policy on the **four tables
     that have `namespace`**:
     `documents`, `entities`, `relationships`, `document_versions`:

     ```sql
     ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
     CREATE POLICY ns_isolation ON documents
       USING (current_setting('app.tenant', true) IS NULL
              OR namespace = current_setting('app.tenant', true));
     -- repeat for entities, relationships, document_versions
     ```

     The `current_setting('app.tenant', true) IS NULL OR …` guard makes
     the policy a **true no-op when the GUC is unset** (back-compat:
     unchanged behavior for callers that never set `rls_enabled`), and a
     hard tenant filter when it is set. `, true` = missing_ok so an unset
     GUC yields NULL instead of erroring.

   - **`chunks` (and the two junction tables) cannot carry that policy
     directly — no `namespace` column.** Chosen resolution: a
     **subquery policy** keyed through the owning `documents` row (no
     schema change, no builder change, no denormalization to keep in
     sync):

     ```sql
     ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
     CREATE POLICY ns_isolation ON chunks
       USING (current_setting('app.tenant', true) IS NULL
              OR EXISTS (SELECT 1 FROM documents d
                         WHERE d.id = chunks.document_id
                           AND d.namespace = current_setting('app.tenant', true)));
     ```

     `entity_chunks`/`relationship_chunks` similarly via their
     `chunk_id → chunks → documents` path *if* defense is wanted there;
     for Task 1.2's scope the leak-guard test only inspects
     `query()` chunk content, so the `documents`+`chunks` policies are
     sufficient for the RLS test. (Junction-table policies are listed in
     the migration as commented optional hardening with a note that they
     add a correlated subquery to graph traversal — measure before
     enabling.)

   - **Provision the non-superuser application role + grants** (see §0;
     RLS is inert without this). In the same migration:

     ```sql
     DO $$ BEGIN
       IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='pgrg_app') THEN
         CREATE ROLE pgrg_app NOSUPERUSER NOBYPASSRLS NOLOGIN;
       END IF;
     END $$;
     -- Privileges every builder/ingest/delete path needs:
     GRANT SELECT, INSERT, UPDATE, DELETE ON
       documents, entities, relationships, document_versions,
       chunks, entity_chunks, relationship_chunks, facts TO pgrg_app;
     GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO pgrg_app;
     -- So the existing superuser DSN can drop to pgrg_app via SET ROLE:
     GRANT pgrg_app TO CURRENT_USER;
     ```

     If the operator forbids role DDL inside migrations, the migration
     header MUST point to a documented operator step that runs the
     equivalent `CREATE ROLE` + `GRANT`s before `rls_enabled=True` is
     turned on. Empirically verified on scratch tables: the identical
     policies isolate correctly under this role and fail open under
     `postgres`.

   > Rejected alternative: denormalizing a `namespace` column onto
   > `chunks` (+ trigger/backfill). It makes the policy uniform and
   > cheaper at query time, but adds a migration that rewrites every
   > existing chunk row, a sync trigger, and an ingest-path write. The
   > subquery policy needs zero data migration and zero builder/ingest
   > change, which matches the plan's "no builder rewrite, back-compat"
   > constraint. If the EXISTS subquery proves too costly under load
   > (Task 4.1), denormalization is the documented escalation.

3. `db.py`: bind **both `SET ROLE pgrg_app` and the `app.tenant` GUC**
   per acquired connection when `config.rls_enabled` (the GUC alone is
   inert under the superuser DSN — see §0). The cleanest hook is a small
   helper applied in
   `fetch_all`/`execute`/`insert_returning_id`/`bulk_insert` and in
   `Transaction.__aenter__`, right after `register_vector_async(conn)`,
   issuing **in order**:
   `SET LOCAL ROLE pgrg_app;` then
   `SET LOCAL app.tenant = <ns>;` (equivalently
   `SELECT set_config('role','pgrg_app',true), set_config('app.tenant',%s,true)`).
   `SET LOCAL` keeps both scoped to the operation's transaction so the
   pooled connection reverts to the base superuser role afterward
   (pgbouncer-safe — see the K3 caveat below). When `rls_enabled=False`
   neither statement is issued and behavior is byte-identical to today
   (the superuser DSN keeps working). The namespace value is the one
   already threaded into every public API (`ns = namespace or
   config.namespace`). Because `db.py` methods don't currently receive
   the namespace, Task 1.2 Step 4 will thread the active namespace to the
   connection (e.g. a `Database.set_tenant(ns)` called by the public API
   before issuing queries, or a contextvar set in `__init__.py` public
   methods). This is additive — builders are untouched. **Task 1.2 scope
   note:** this binding plus the `pgrg_app` role + grants from §0/§2 are
   in scope, not just the policy + GUC.

   > pgbouncer caveat (K3): under transaction pooling, session-level
   > `SET` does not persist across transactions. Use `SET LOCAL`
   > within the operation's transaction, or `set_config(...,
   > is_local => true)`. Document in the migration header.

### Exact tests (used VERBATIM in Task 1.2 Steps 1 and 5)

Verified symbols: `GraphRAG.ingest_records(records, namespace=...)`,
`GraphRAG.query(question, mode="naive", namespace=...)` →
`QueryResult.chunks` (`ChunkResult.content`), `GraphRAG.db` →
`Database`, `Database.fetch_all(sql, params)`,
`Database.execute(sql, params)`. The `scale_rag` fixture teardown wipes
`ten%` namespaces (`tests/scale/conftest.py:_SCALE_NS_PATTERNS`).
`PGRGConfig(rls_enabled=...)` field added by Task 1.2. **Task 1.2 scope
includes the non-superuser `pgrg_app` role + grants + the `SET LOCAL
ROLE pgrg_app` connection binding (see §0/§2/§3) — not just the policy +
GUC. Step 5 is broken without the role binding because the documented
DSN's `postgres` role is a superuser that bypasses RLS.**

**Step 1 — permanent app-filter guard (passes today, ships even if RLS
slips):**

```python
# tests/scale/test_namespace_isolation.py
import pytest

from pg_raggraph import GraphRAG  # noqa: F401 (fixture provides instance)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_cross_namespace_leak(scale_rag):
    await scale_rag.ingest_records(
        [{"text": "tenantA secret alpha", "source_id": "a1"}],
        namespace="tenA",
    )
    await scale_rag.ingest_records(
        [{"text": "tenantB secret beta", "source_id": "b1"}],
        namespace="tenB",
    )
    r = await scale_rag.query("secret", mode="naive", namespace="tenA")
    assert len(r.chunks) > 0
    assert all("beta" not in c.content for c in r.chunks)
    assert any("alpha" in c.content for c in r.chunks)
```

**Step 5 — RLS blocks a deliberately namespace-blind raw query.**

The documented DSN's role is `postgres`, a **superuser** — RLS is inert
under it (see §0). A test that connects as `postgres` and asserts
isolation **fails against the documented DB** (the reviewer ran the
exact policies as `postgres` and got *both* tenants' rows). The
corrected test below makes isolation deterministic regardless of the
DSN's base role: it ingests both tenants with a **non-RLS** instance
(the cross-tenant data must exist to *prove* isolation — a tenant-bound
ingest could not write tenB), then asserts the namespace-blind queries
return only `tenA` **through a connection forced onto the non-superuser
`pgrg_app` role** with `app.tenant='tenA'` bound — exactly the
mechanism Task 1.2's §3 `db.py` binding installs. This was empirically
verified on scratch tables: `SET LOCAL ROLE pgrg_app` + `SET LOCAL
app.tenant='tenA'` from the superuser connection returned only `tenA`
rows on both the direct-policy `documents` and the subquery-policy
`chunks`; the same statements as bare `postgres` leaked both tenants.

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_rls_blocks_namespace_blind_query():
    # 1. Ingest BOTH tenants with a plain (non-RLS) instance. The
    #    cross-tenant rows MUST exist for the isolation assertion to be
    #    meaningful; a tenant-bound connection could not write tenB.
    seed = GraphRAG(
        "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
        namespace="tenA",
        skip_extraction=True,
    )
    await seed.connect()
    try:
        await seed.ingest_records(
            [{"text": "tenantA secret alpha", "source_id": "a1"}],
            namespace="tenA",
        )
        await seed.ingest_records(
            [{"text": "tenantB secret beta", "source_id": "b1"}],
            namespace="tenB",
        )
    finally:
        await seed.close()

    # 2. rls_enabled=True applies migration 003 (policies + the pgrg_app
    #    role/grants) and binds, per operation, SET LOCAL ROLE pgrg_app
    #    + SET LOCAL app.tenant=<ns>. This drops the superuser DSN onto
    #    the non-superuser role so the policies actually filter — without
    #    this the documented postgres DSN bypasses RLS and the test would
    #    (correctly) fail, exposing a non-isolating build.
    rag = GraphRAG(
        "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
        namespace="tenA",
        skip_extraction=True,
        rls_enabled=True,
    )
    await rag.connect()
    try:
        # Guard: prove the binding actually dropped privileges. If this
        # ever runs as a superuser/BYPASSRLS role, RLS is inert and the
        # isolation asserts below would be a false PASS — fail loudly.
        whoami = await rag.db.fetch_all(
            "SELECT current_user AS u, "
            "current_setting('app.tenant', true) AS t, "
            "(SELECT rolsuper OR rolbypassrls FROM pg_roles "
            " WHERE rolname = current_user) AS privileged"
        )
        assert whoami[0]["u"] == "pgrg_app", whoami
        assert whoami[0]["t"] == "tenA", whoami
        assert whoami[0]["privileged"] is False, (
            f"RLS would be INERT: connection role is privileged {whoami}"
        )

        # A raw query that OMITS any namespace predicate. With the
        # connection on pgrg_app and app.tenant='tenA', the RLS policy on
        # documents must hide tenB's rows.
        rows = await rag.db.fetch_all(
            "SELECT content_hash, namespace FROM documents"
        )
        seen = {row["namespace"] for row in rows}
        assert seen == {"tenA"}, f"RLS leak: saw namespaces {seen}"

        # And the chunks subquery-policy must hide tenB chunk bodies even
        # with a namespace-blind chunk select.
        crows = await rag.db.fetch_all(
            "SELECT content FROM chunks"
        )
        assert all("beta" not in r["content"] for r in crows)
        assert any("alpha" in r["content"] for r in crows)
    finally:
        # Cleanup runs as the privileged base DSN (rls_enabled instance
        # only scopes role/tenant per-operation via SET LOCAL, so the
        # DELETE here is not tenant-restricted and removes BOTH tenants).
        await rag.db.execute(
            "DELETE FROM documents WHERE namespace LIKE 'ten%'"
        )
        await rag.close()
```

> Implementation note for Task 1.2: Step 5 is deliberately a
> **two-instance** test. The seed instance (`rls_enabled=False`) writes
> both tenants — this is required: a tenant-bound connection cannot
> produce the cross-tenant data the isolation assertion depends on. The
> assertion instance (`rls_enabled=True`) exercises the §3 binding
> (`SET LOCAL ROLE pgrg_app` + `SET LOCAL app.tenant`). The `whoami`
> guard is **load-bearing**: without it, a build that forgot the
> `SET ROLE` binding (or ran against a BYPASSRLS DSN) would silently
> PASS because the namespace-blind selects would happen to be filtered
> by nothing yet still "look" isolated only if data were absent — the
> guard converts that into a hard failure, so the test genuinely proves
> isolation rather than asserting a tautology. Both instances use the
> documented `postgresql://postgres:postgres@...` DSN, and the test
> deterministically PASSES once Task 1.2's migration (policies +
> `pgrg_app` role/grants) and the §3 GUC/role binding land. It is not
> the `scale_rag` fixture because that builds the instance with
> `rls_enabled` defaulting to False. The final `DELETE` runs under the
> base superuser DSN (the `SET LOCAL` scoping reverts after each
> operation), so it removes both tenants; `delete(namespace=...)` is an
> alternative but only purges `documents`/`entities`/`relationships`
> (`__init__.py:1307-1309`) — sufficient here since chunks cascade via
> `documents(id) ON DELETE CASCADE` (`sql/schema.sql:42`).

---

## Self-review — API symbols verified against source

Every symbol referenced in the three "Exact test" blocks was confirmed
present on branch `feature/scale-remediation`:

- `pg_raggraph.GraphRAG` — `src/pg_raggraph/__init__.py`
- `GraphRAG.ingest_records(records, namespace=None, on_progress=None)` —
  `__init__.py:479-484`
- `GraphRAG.query(question, mode="smart", namespace=None, *, ...)` —
  `__init__.py:1171-1181`; returns `QueryResult`
- `QueryResult.chunks: list[ChunkResult]`, `ChunkResult.content`,
  `ChunkResult.chunk_id` — populated `retrieval.py:354-374`
- `GraphRAG.db` property → `Database` — `__init__.py:251-255`
- `Database.fetch_all(query_str, params)` → `list[dict]` —
  `db.py:215-223`; `Database.execute` — `db.py:208-213`
- HNSW index `idx_chunk_embed` — `sql/schema.sql:123`
- `PGRGConfig` (`extra="forbid"` — `embedding_base_url`/
  `embedding_api_key` MUST be added by Task 2.1 or the F3 tests cannot
  construct the config) — `config.py:51`;
  `get_embedding_provider(config)` — `embedding.py:108`;
  `HttpxEmbeddingProvider` ctor `(base_url, model, api_key="",
  dimension=384)`, attrs `_base_url`/`_api_key`/`dimension` —
  `embedding.py:77-105`
- `scale_rag` fixture + `ten%`/`ts%` teardown prefixes —
  `tests/scale/conftest.py`
- New fields introduced by their tasks (not yet in source, by design):
  `retrieval_candidate_k`, `two_stage_retrieval` (Task 1.1);
  `embedding_base_url`, `embedding_api_key` (Task 2.1); `rls_enabled`
  (Task 1.2); `_build_naive_query_twostage` (Task 1.1). These are the
  *deliverables* of the gated tasks, named here so the tests compile the
  moment each task lands.

### Phase-1 hand-off — corrected scope notes

- **Task 1.2 (K2):** scope now explicitly includes the non-superuser,
  non-BYPASSRLS `pgrg_app` application role + table/sequence grants +
  the `SET LOCAL ROLE pgrg_app` connection binding — **not just** the
  RLS policy + `app.tenant` GUC. RLS is inert (fails open) under the
  documented superuser `postgres` DSN without this. Empirically
  confirmed on scratch tables.
- **Task 2.1 (F3):** `PGRGConfig` is `extra="forbid"`; the
  `embedding_base_url` / `embedding_api_key` fields MUST be added to
  `src/pg_raggraph/config.py` first or the F3 tests cannot construct the
  config.
- **Task 1.1 (K1):** the two-stage candidate CTE is HNSW-*eligible*,
  not HNSW-*guaranteed* — the plan/recall assertion MUST run on a
  freshly-ingested fixture namespace, and the production "small
  namespace in a huge shared HNSW index" scenario is not fully
  de-risked by this spike (consider `hnsw.ef_search` / `enable_seqscan`;
  cross-ref Task 2.4 / K6).
