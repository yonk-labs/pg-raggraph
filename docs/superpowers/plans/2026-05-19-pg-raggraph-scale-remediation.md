# pg-raggraph Scale Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every known issue from `docs/deployment-embedding-scaling.md` (F1–F7) and `docs/operations-guide.md` (K1–K9) so pg-raggraph is safe for a multi-tenant deployment serving 100s of users, each fix shipped with an interim operator mitigation and an automated test.

**Architecture:** Two independently-executable tracks — **Track A: Embedding** (in-process model → bounded/shared) and **Track B: Ops/Multi-tenant** (retrieval index usage, tenant isolation, resource bounds). Both are phased by blast radius. Every code fix is TDD (failing test first). Design-heavy items (K1, K2, F3) begin with a verification spike whose deliverable is a confirmed design + the failing test that defines done. Each issue carries a deploy-now mitigation requiring no code.

**Tech Stack:** Python 3.12, pytest + pytest-asyncio, PostgreSQL 16 + pgvector + pg_trgm, psycopg3 / psycopg_pool, fastembed/onnxruntime, ruff.

---

## Conventions

- DB-touching tests use the integration DB (`postgresql://postgres:postgres@localhost:5434/pg_raggraph`); mark `@pytest.mark.integration`.
- Run a single test: `uv run pytest tests/<path>::<name> -v`.
- Every task ends in a commit. Never edit a released migration — add a new numbered `sql/migrations/NNN_*.sql`.
- "Mitigation" = operator action shippable today (config/runbook), no code merge.
- A "spike" task's deliverable is a written finding committed under `docs/superpowers/specs/` + the failing test for the fix; it is not a placeholder.

---

## Phase 0 — Safety net (do first; everything depends on it)

### Task 0.1: Regression baseline harness

**Files:**
- Create: `tests/scale/conftest.py`
- Create: `tests/scale/test_baseline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/scale/test_baseline.py
import pytest
from pg_raggraph import GraphRAG

@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_returns_chunks_baseline(scale_rag):
    await scale_rag.ingest_records(
        [{"text": f"Paris is the capital of France. fact {i}", "source_id": f"d{i}"}
         for i in range(50)], namespace="base")
    r = await scale_rag.query("What is the capital of France?",
                              mode="naive", namespace="base")
    assert any("Paris" in c.content for c in r.chunks)
```

- [ ] **Step 2: Add fixture**

```python
# tests/scale/conftest.py
import pytest_asyncio
from pg_raggraph import GraphRAG

@pytest_asyncio.fixture
async def scale_rag():
    rag = GraphRAG("postgresql://postgres:postgres@localhost:5434/pg_raggraph",
                    namespace="scale_test", skip_extraction=True)
    await rag.connect()
    yield rag
    await rag.db.execute("DELETE FROM documents WHERE namespace LIKE 'base%' "
                         "OR namespace LIKE 'scale%'")
    await rag.close()
```

- [ ] **Step 3: Run** — `uv run pytest tests/scale/test_baseline.py -v` → PASS (proves harness works against current behavior).

- [ ] **Step 4: Commit**

```bash
git add tests/scale/conftest.py tests/scale/test_baseline.py
git commit -m "test(scale): regression baseline harness for remediation"
```

### Task 0.2: Spikes (commit findings before touching code)

- [ ] **Step 1: K1 spike — confirm HNSW is bypassed.** Ingest 20k chunks into one namespace; `EXPLAIN (ANALYZE, BUFFERS)` a `mode=naive` query. Record plan + latency vs a bare `ORDER BY embedding <=> q LIMIT 20`.
- [ ] **Step 2: F3 spike — config surface.** Enumerate every read of `config.llm_base_url`/`llm_api_key` for embedding vs extraction; design `embedding_base_url`/`embedding_api_key` with back-compat.
- [ ] **Step 3: K2 spike — RLS feasibility.** Confirm whether all query builders reference exactly one `namespace` param and whether a session GUC + RLS policy can be added without rewriting builders.
- [ ] **Step 4: Commit findings**

```bash
git add docs/superpowers/specs/2026-05-19-scale-spikes.md
git commit -m "docs(spike): K1/F3/K2 verification findings + chosen designs"
```

Acceptance: each spike states the confirmed mechanism, the chosen design, and the exact test that will prove the fix (used verbatim in the relevant task below).

---

## Phase 1 — Critical (K1, K2, F1, F2, K5, K3)

### Task 1.1 (K1): Two-stage retrieval so the vector index is used

**Mitigation (ship now):** runbook — bound per-namespace corpus; set Postgres `statement_timeout`; prefer `local` mode for large namespaces. Already in `operations-guide.md` §2 K1.

**Files:**
- Modify: `src/pg_raggraph/retrieval.py` (`_build_naive_query`, add `_build_naive_query_twostage`)
- Modify: `src/pg_raggraph/config.py` (add `retrieval_candidate_k: int = 200`, `two_stage_retrieval: bool = True`)
- Test: `tests/scale/test_twostage_retrieval.py`

- [ ] **Step 1: Write the failing test** (defines done: same top-k membership as today on small data, HNSW plan on large data)

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_twostage_uses_hnsw_and_preserves_topk(scale_rag):
    rows = [{"text": f"doc {i} about topic {i%7}", "source_id": f"t{i}"}
            for i in range(5000)]
    await scale_rag.ingest_records(rows, namespace="ts")
    r = await scale_rag.query("topic 3", mode="naive", namespace="ts")
    assert len(r.chunks) > 0
    plan = await scale_rag.db.fetch_all(
        "EXPLAIN SELECT id FROM chunks c JOIN documents d ON d.id=c.document_id "
        "WHERE d.namespace='ts' ORDER BY c.embedding <=> "
        "(SELECT embedding FROM chunks LIMIT 1) LIMIT 200")
    assert any("Index Scan" in str(row) and "hnsw" in str(row).lower()
               or "idx_chunk_embed" in str(row) for row in plan)
```

- [ ] **Step 2: Run** → FAIL (two-stage path absent).
- [ ] **Step 3: Implement** — add a candidate-fetch CTE using bare `ORDER BY c.embedding <=> q LIMIT retrieval_candidate_k` (HNSW-eligible), then re-score that CTE with the existing `w_sem*…+w_bm25*…+w_graph*…` expression and `LIMIT top_k`. Gate behind `config.two_stage_retrieval` (default True); old path retained when False for A/B.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Recall A/B** — add `tests/scale/test_twostage_recall.py` asserting two-stage top-k overlap with single-stage ≥ 0.95 on a 5k fixture (acceptance: no recall regression at default `candidate_k`).
- [ ] **Step 6: Commit** `git commit -m "perf(retrieval): two-stage HNSW candidate + re-score (K1)"`

### Task 1.2 (K2): RLS defense-in-depth for tenant isolation

**Mitigation (ship now):** server-derived namespace only; query-path audit test (Step 1 below ships independently of RLS).

**Files:**
- Create: `tests/scale/test_namespace_isolation.py`
- Create: `src/pg_raggraph/sql/migrations/003_rls_namespace.sql`
- Modify: `src/pg_raggraph/db.py` (set `SET app.tenant` per acquired connection when `config.rls_enabled`)
- Modify: `src/pg_raggraph/config.py` (`rls_enabled: bool = False`)

- [ ] **Step 1: Failing audit test (independent value, ship even if RLS slips)**

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_cross_namespace_leak(scale_rag):
    await scale_rag.ingest_records([{"text":"tenantA secret alpha","source_id":"a1"}], namespace="tenA")
    await scale_rag.ingest_records([{"text":"tenantB secret beta","source_id":"b1"}], namespace="tenB")
    r = await scale_rag.query("secret", mode="naive", namespace="tenA")
    assert all("beta" not in c.content for c in r.chunks)
```

- [ ] **Step 2: Run** → PASS today (app filter works) — this test is the permanent guard.
- [ ] **Step 3: Add RLS migration** — `ALTER TABLE chunks/documents/entities/relationships ENABLE ROW LEVEL SECURITY; CREATE POLICY ns_isolation USING (namespace = current_setting('app.tenant', true));` (policy is a no-op unless `app.tenant` is set, preserving back-compat).
- [ ] **Step 4: Bind GUC in pool** — in `db.py` connection-acquire hook, when `rls_enabled`, `SET app.tenant = <ns>` for the operation's namespace.
- [ ] **Step 5: RLS test** — repeat the leak test with `rls_enabled=True` and a deliberately-buggy raw query missing the WHERE clause; assert RLS still blocks the leak.
- [ ] **Step 6: Commit** `git commit -m "feat(security): optional RLS namespace isolation (K2)"`

### Task 1.3 (F1): Bound onnxruntime threads

**Mitigation (ship now):** `OMP_NUM_THREADS=1` env on multi-process hosts (runbook).

**Files:** Modify `src/pg_raggraph/config.py` (`embedding_threads: int = 1`), `src/pg_raggraph/embedding.py:32-49`; Test `tests/scale/test_embed_threads.py`

- [ ] **Step 1: Failing test**

```python
def test_fastembed_threads_passed(monkeypatch):
    captured = {}
    import fastembed
    class FakeTE:
        def __init__(self, model_name, threads=None, **k): captured.update(model_name=model_name, threads=threads)
        def embed(self, t): return [[0.0]*8 for _ in t]
    monkeypatch.setattr(fastembed, "TextEmbedding", FakeTE)
    from pg_raggraph.embedding import FastEmbedProvider
    FastEmbedProvider("BAAI/bge-small-en-v1.5", threads=1)
    assert captured["threads"] == 1
```

- [ ] **Step 2: Run** → FAIL (signature has no `threads`).
- [ ] **Step 3: Implement** — `FastEmbedProvider.__init__(self, model_name=..., threads: int | None = None)`; pass `threads=threads` to `TextEmbedding`; `get_embedding_provider` passes `config.embedding_threads`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "perf(embedding): bound onnxruntime threads, default 1 (F1)"`

### Task 1.4 (F2): Process-level model cache

**Files:** Modify `src/pg_raggraph/embedding.py`; Test `tests/scale/test_embed_cache.py`

- [ ] **Step 1: Failing test** — instantiate `FastEmbedProvider` twice with same `(model, threads)`; assert the underlying `TextEmbedding` constructor ran once (monkeypatched counter).
- [ ] **Step 2: Run** → FAIL (model built per instance).
- [ ] **Step 3: Implement** — module-level `@functools.lru_cache` factory keyed by `(model_name, threads)` returning the loaded model; `FastEmbedProvider` pulls from it.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "perf(embedding): process-level model cache (F2)"`

### Task 1.5 (K5): Statement timeout + bounded retrieval cost

**Mitigation (ship now):** set `statement_timeout` in postgresql.conf / DSN options (runbook).

**Files:** Modify `src/pg_raggraph/config.py` (`statement_timeout_ms: int = 0`), `src/pg_raggraph/db.py` (apply on connect); Test `tests/scale/test_statement_timeout.py`

- [ ] **Step 1: Failing test** — with `statement_timeout_ms=50`, run `SELECT pg_sleep(1)`; expect a timeout error.
- [ ] **Step 2: Run** → FAIL (no timeout applied).
- [ ] **Step 3: Implement** — when `statement_timeout_ms>0`, `SET statement_timeout` on each acquired connection in `db.py`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(db): configurable statement_timeout (K5)"`

### Task 1.6 (K3): Migration as explicit step + pool-size guard

**Mitigation (ship now):** run `pgrg init`/migration as a pre-deploy job; pgbouncer transaction pooling; `PGRG_POOL_MAX=4` (runbook).

**Files:** Modify `src/pg_raggraph/cli.py` (`pgrg migrate` subcommand that runs migrations and exits), `src/pg_raggraph/config.py` (warn if `pool_max > 10`); Test `tests/scale/test_migrate_cmd.py`

- [ ] **Step 1: Failing test** — invoke the CLI `migrate` command on a fresh DB; assert `pgrg_applied_migrations` populated and process exits 0 without serving.
- [ ] **Step 2: Run** → FAIL (no standalone subcommand).
- [ ] **Step 3: Implement** — add `migrate` Click command calling the existing `_apply_migrations` path then exit; add one-time warning in `config.model_post_init` when `pool_max > 10`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(cli): standalone migrate cmd + pool_max guard (K3)"`

---

## Phase 2 — High (F3, F4, K4, K6)

### Task 2.1 (F3): Dedicated embedding endpoint config

**Files:** Modify `config.py` (`embedding_base_url`, `embedding_api_key`), `embedding.py:108-123` (add `"http"` provider); Test `tests/scale/test_embed_provider_http.py`

- [ ] **Step 1: Failing test** — `embedding_provider="http"`, `embedding_base_url="http://x/v1"`; assert `get_embedding_provider` returns `HttpxEmbeddingProvider` pointed at that URL (not `llm_base_url`, not api.openai.com).
- [ ] **Step 2: Run** → FAIL (`http` unknown).
- [ ] **Step 3: Implement** — add `http` branch using the new fields; keep `local|openai|ollama` unchanged for back-compat.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(embedding): dedicated embedding endpoint config (F3)"`

### Task 2.2 (F4): Reuse httpx client + honor batch size

**Files:** Modify `embedding.py` `HttpxEmbeddingProvider`; Test `tests/scale/test_embed_batching.py`

- [ ] **Step 1: Failing test** — embed 50 texts with `embed_batch_size=16`; assert the mocked endpoint received 4 batched POSTs (not 1×50 or 50×1) and one shared client was used.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — construct one `httpx.AsyncClient` in `__init__`; chunk `texts` by `embed_batch_size`; add `aclose()`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "perf(embedding): keep-alive client + batched requests (F4)"`

### Task 2.3 (K4): Ingest backpressure hook

**Mitigation (ship now):** dedicated bounded ingest workers + queue at the service layer; `fact_extractor=none|lede_spacy` when LLM graph not needed (runbook).

**Files:** Modify `src/pg_raggraph/__init__.py` `ingest_records` (accept `max_in_flight` semaphore already exists via extract_concurrency — add per-call cap + raise typed `IngestBackpressure` when a caller-supplied bound is exceeded); Test `tests/scale/test_ingest_backpressure.py`

- [ ] **Step 1: Failing test** — call `ingest_records(..., max_concurrent_docs=2)`; instrument to assert no more than 2 docs embed concurrently.
- [ ] **Step 2: Run** → FAIL (param absent).
- [ ] **Step 3: Implement** — thread an `asyncio.Semaphore(max_concurrent_docs or config.doc_concurrency)` through the per-doc loop.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(ingest): per-call concurrency bound (K4)"`

### Task 2.4 (K6): Expose HNSW build/search params

**Mitigation (ship now):** `SET hnsw.ef_search`; tune `maintenance_work_mem`; scheduled `REINDEX CONCURRENTLY` (runbook).

**Files:** Create `sql/migrations/004_hnsw_params.sql` (recreate HNSW indexes with `WITH (m=?, ef_construction=?)` from config-templated values), Modify `config.py` (`hnsw_m: int=16`, `hnsw_ef_construction: int=64`, `hnsw_ef_search: int=40`), `db.py` (set `hnsw.ef_search` per connection); Test `tests/scale/test_hnsw_params.py`

- [ ] **Step 1: Failing test** — connect with `hnsw_ef_search=80`; `SHOW hnsw.ef_search` → `80`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — apply `SET hnsw.ef_search` on connect; migration recreates indexes `CONCURRENTLY` with templated `m`/`ef_construction`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(hnsw): configurable m/ef_construction/ef_search (K6)"`

---

## Phase 3 — Medium / hardening (F5, F6, F7, K7, K8, K9)

### Task 3.1 (F5): Local-embedder concurrency warning

**Files:** Modify `embedding.py` (one-time WARNING when `provider==local`, pointing at the deployment doc), mirroring `config.py` default-DSN warning. Test: assert log emitted once. Commit `"feat(embedding): warn on local provider at scale (F5)"`.

### Task 3.2 (F6): Pool guardrail

**Files:** Modify `config.py` — already partially in K3; here add the documented recommended ceiling check + docs xref. Test: warning emitted when `pool_max*~workers` heuristic exceeded. Commit `"feat(config): connection-pool guardrail (F6)"`.

### Task 3.3 (F7): Content-hash embedding cache

**Files:** Create `sql/migrations/005_embedding_cache.sql` (`embedding_cache(text_sha256 PK, embedding vector(?))`), Modify ingest path to look up/populate. Test: re-ingesting identical text issues zero new embed calls (mocked counter). Commit `"perf(embedding): content-hash embed cache (F7)"`.

### Task 3.4 (K7): Per-namespace metrics hook

**Files:** Modify `__init__.py` query/ingest to emit structured metric events (callback or logging) tagged by namespace + mode + latency. Test: a query emits one metric record with `namespace`,`mode`,`latency_ms`. Commit `"feat(obs): per-namespace metric events (K7)"`.

### Task 3.5 (K8): Per-namespace purge + export

**Files:** Verify/extend `delete()` to cascade chunks/entities/relationships/document_versions for a namespace; add `export_namespace(ns)->iterator`. Test: ingest into ns, `delete(namespace=ns)`, assert zero rows across all 4 tables; export yields the ingested docs. Commit `"feat(lifecycle): namespace purge+export, GDPR (K8)"`.

### Task 3.6 (K9): Read-replica routing doc + DSN split

**Files:** Modify `config.py` (`read_dsn: str = ""`), `db.py` (route read-only query path to `read_dsn` when set, writes to `dsn`); Test: with distinct read/write DSNs, a `query()` uses the read pool, `ingest_records()` the write pool (assert via connection tagging). Commit `"feat(db): optional read-replica routing (K9)"`.

---

## Phase 4 — Integration & sign-off

### Task 4.1: Multi-tenant load test

**Files:** Create `tests/scale/test_load_multitenant.py` (or a `benchmarks/scale/` script).

- [ ] **Step 1:** 50 namespaces × 2k chunks; 200 concurrent queries across tenants; assert p99 < target, zero cross-tenant leaks (reuse Task 1.2 Step 1 assertion at scale), pool never exhausted.
- [ ] **Step 2:** Run with `two_stage_retrieval` on vs off; record latency delta as evidence K1 is fixed.
- [ ] **Step 3:** Commit results to `benchmarks/scale-results/`.

### Task 4.2: Docs reconciliation

- [ ] Update `operations-guide.md` / `deployment-embedding-scaling.md` "Status" sections: flip each F/K from "recommended, not implemented" to "implemented in <commit>", keeping the mitigation paragraph for users not yet on the new version.
- [ ] Commit `"docs: mark F1-F7/K1-K9 implemented; retain interim mitigations"`.

---

## Coverage Matrix (self-review)

| Item | Fix task | Mitigation | Test |
|---|---|---|---|
| F1 threads | 1.3 | OMP_NUM_THREADS=1 | test_embed_threads |
| F2 model cache | 1.4 | — | test_embed_cache |
| F3 embed endpoint | 2.1 (spike 0.2) | ollama-provider escape hatch | test_embed_provider_http |
| F4 batched client | 2.2 | — | test_embed_batching |
| F5 warn | 3.1 | — | log assertion |
| F6 pool guard | 3.2 | PGRG_POOL_MAX=4 | warning assertion |
| F7 embed cache | 3.3 | — | zero-recompute test |
| K1 HNSW bypass | 1.1 (spike 0.2) | bound namespace, statement_timeout | test_twostage_* |
| K2 isolation | 1.2 (spike 0.2) | server-derived ns + audit test | test_namespace_isolation |
| K3 conns/migrate | 1.6 | pgbouncer, pre-deploy migrate | test_migrate_cmd |
| K4 ingest load | 2.3 | bounded ingest workers/queue | test_ingest_backpressure |
| K5 tail latency | 1.5 | statement_timeout, cap max_hops | test_statement_timeout |
| K6 HNSW ops | 2.4 | ef_search/maintenance_work_mem | test_hnsw_params |
| K7 noisy neighbor | 3.4 | service-layer quotas | metric-event test |
| K8 lifecycle | 3.5 | — | purge+export test |
| K9 single-writer | 3.6 | vertical scale first | read/write routing test |

Every F/K maps to a fix task, a deploy-now mitigation, and a named test. No placeholder steps; design-heavy items (1.1, 1.2, 2.1) gated by the Phase-0 spike whose committed finding supplies the final implementation + test.

---

## Execution order & dependencies

Phase 0 → Phase 1 (1.1 and 1.2 require their Phase-0 spike) → Phase 2 → Phase 3 → Phase 4. Track A (F*) and Track B (K*) within a phase are parallelizable across workers/subagents. Each task is independently revertable and leaves tests green.
