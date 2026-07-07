# pg-raggraph: No-BS Project Assessment

*Written at the end of a day of building, benchmarking, and breaking things. Dated honestly.*

**Last verified against: v0.5.0a19, commit `e7a5320`, 2026-07-07** (see the 2026-07 update below; sections beneath it grade the v0.3.0-era codebase and are kept as history).

## TL;DR

pg-raggraph is **a working, PostgreSQL-native GraphRAG library**. On a real 486-doc developer codebase, its 1-hop graph boost improved the top retrieved chunk's score by **+19.3%** over plain vector+BM25 at the same latency — a retrieval-quality proxy, not graded answer accuracy ([`benchmarks/pg-agents-results.md`](benchmarks/pg-agents-results.md)). On gold-labeled multi-hop QA (MuSiQue, dual LLM judges), recursive graph traversal beats pure vector by **+4–5pp** end-to-end ([`benchmarks/ab-gate/RESULTS.md`](benchmarks/ab-gate/RESULTS.md)). The architecture is sound and the tests pass.

Below is the honest teardown.

## 2026-07-07 Update — Claims Audit and Current State

An adversarial audit of this project's public claims (AAT, 2026-07) forced corrections. Recording them here, because this file is the document the README points due-diligence readers at:

- **Benchmark captions corrected.** Earlier revisions of this file and the README captioned the pg-agents top-score lift as an "accuracy" improvement. It is not: the metric is average score of the best retrieved chunk — a retrieval-confidence proxy; no answers were generated or graded in that run. Canonical numbers live in [`benchmarks/pg-agents-results.md`](benchmarks/pg-agents-results.md) (+19.3% top score, 486 docs). The lift did **not** transfer to gold-labeled QA: best +3.3pp on judged SCOTUS questions, within the noise floor ([`benchmarks/age-bakeoff/SESSION-HANDOFF.md`](benchmarks/age-bakeoff/SESSION-HANDOFF.md)). The end-to-end case for graph now rests on the MuSiQue result: `local` traversal beats `naive` by +4–5pp across two judges and two runs, with flat retrieval recall ([`benchmarks/ab-gate/RESULTS.md`](benchmarks/ab-gate/RESULTS.md)).
- **AGE claim corrected.** "AGE Cypher and pgvector cannot combine in a single query" was wrong. Microsoft's [HorizonDB GraphRAG doc](https://learn.microsoft.com/en-us/azure/horizondb/ai/graph-rag) shows `ag_catalog.cypher()` CTEs composed with pgvector in one SQL statement, and the pattern runs on stock AGE 1.5.0. What survives — and is still dispositive — is the `shared_preload_libraries` cloud lockout (Azure-only among major managed providers), the openCypher subset (no `MERGE ... ON CREATE SET`, `EXISTS`, `datetime()`), manual graph maintenance with no CDC, and documented exponential path expansion beyond 3–4 hops (all per Microsoft's same doc).
- **Scale since v0.3.0:** 887 tests (523 unit + 364 integration) at 0.5.0a19, fourteen releases on. Features graded "missing" below now exist: cross-encoder reranking (`src/pg_raggraph/reranker.py`), opt-in row-level security (`sql/migrations/003_rls_namespace.sql`), structured logging (`PGRG_LOG_FORMAT=json`), MCP server, background extraction, online embedding migration. Rate limiting remains delegated to a reverse proxy by design.
- **Known open problems, unchanged:** SEC 10-Q gold QnA sits at ~47% in every mode (table chunking, not retrieval); retrieval coverage — not ranking — is the accuracy ceiling on gold-labeled corpora (~44% of required gold facts never reach top-10 on SCOTUS).
- **In progress:** a reproducible head-to-head against Microsoft's HorizonDB GraphRAG accelerator on Microsoft's own corpus, and a factorial chunking × embedding experiment attacking the coverage ceiling.

External code-quality audits of the current codebase came back solid; the corrections above are about claims, not code.

---

## 2026-04 Update — What Got Fixed

The gaps flagged below in "What's Rough / Bad" were addressed in a cleanup sprint:

- ✅ **Answer generation** — `rag.ask()` and `pgrg ask` ship a grounded answer built from the retrieved chunks. Falls back to a top-chunk summary if no LLM is configured, so the library is usable as pure vector RAG without ever calling an LLM.
- ✅ **LLM-optional ingestion** — `PGRG_SKIP_EXTRACTION=true` (or simply not setting `PGRG_LLM_BASE_URL`) runs ingestion as chunks + embeddings only. Works end-to-end without any LLM.
- ✅ **Entity/document CRUD** — `delete_document`, `delete_entity`, `merge_entities`, `prune_orphans`.
- ✅ **Incremental updates** — changed files are detected by (namespace, source_path, different content_hash) and the stale document is deleted (cascading chunks + provenance) before re-ingest.
- ✅ **Schema migration framework** — `sql/migrations/NNN_*.sql` files are applied in numeric order on connect, tracked via `pgrg_meta.schema_version`.
- ✅ **Deadlock retry** — per-document ingestion retries up to 3× with exponential backoff on SQLSTATE 40P01 / 40001.
- ✅ **MCP server** — `pgrg mcp-serve` runs a stdio MCP server with `pgrg_query`, `pgrg_ask`, `pgrg_ingest`, `pgrg_status`, `pgrg_delete_document` tools. Install with `pip install pg-raggraph[mcp]`.
- ✅ **CI/CD** — `.github/workflows/test.yml` runs ruff + unit + integration against a pgvector service container.
- ✅ **Deploy story** — `docker-compose.prod.yml` + `DEPLOY.md` cover single-node Docker, managed Postgres, and embedded use.
- ✅ **Too many modes** — CLI help now points users at `smart` as the default and flags other modes as power-user overrides. The modes themselves remain available for people who want them.

The gap analysis in "What's Rough / Bad" below is kept as historical context.

### Post-sprint AAT audit — 7 regressions caught and fixed

An `aat internal` pass on the cleanup-sprint code caught 2 FATAL + 5 SERIOUS bugs I'd introduced. All fixed in the same session:

- **Migrations never ran after initial install** (FATAL). `_ensure_schema` returned early when `schema_version >= SCHEMA_VERSION`, before calling `_apply_migrations`. The whole migration framework was dead code on existing installs. Fixed: migration apply now runs unconditionally after the bootstrap check, guarded by a `pg_advisory_lock(0x70677267)` so concurrent workers can't race on the same migration.
- **MCP `pgrg_ingest` had no path sandbox** (FATAL). Client paths were forwarded straight to `rag.ingest` — an untrusted LLM agent could ingest `/etc`, `~/.ssh`, and query them back. Fixed: MCP ingest is refused unless `PGRG_MCP_INGEST_ROOTS` (colon-separated) is set, and every incoming path is symlink-resolved and checked against the allowlist with proper path-component matching (no `/tmp/kb2` vs `/tmp/kb` prefix confusion).
- **`merge_entities` had four correctness bugs** (SERIOUS). Fixed: refuses `keep_id ∈ merge_ids`, empty lists, missing entities, and cross-namespace merges; drops self-loops created by the merge; collapses duplicate edges post-merge via `DELETE a USING b WHERE a.id > b.id`; returns a single consistent `{kept, merged_count}` shape.
- **Stale-doc delete ran outside the per-file transaction** (SERIOUS). An extraction failure between the delete and the new insert would lose data. Fixed: the stale `DELETE FROM documents` now lives inside the same `db.transaction()` as the fresh insert.
- **`docker-compose.prod.yml` would crashloop** (SERIOUS). It called `pip install pg-raggraph[server]` — the package isn't on PyPI yet. Fixed: added a real `Dockerfile` that builds from local source, compose now builds it via `build:` instead of pulling from PyPI.
- **`DEPLOY.md` contained `sk-REPLACE_ME`** (SERIOUS). Exactly the pattern secret scanners flag. Fixed: replaced with `YOUR_API_KEY_HERE`.

Verified after each fix: `pytest` full suite (68/68), a dedicated regression script covering each bug path (8/8), and an MCP sandbox test (5/5). `ruff check` clean.

---

## What Actually Works (and is good)

### 1. The core graph-boost approach is genuinely novel and effective ✅
We built a 1-hop graph re-ranker that runs in a single SQL query alongside pgvector, and on a real dev-codebase corpus it improves top retrieved-chunk scores by **+19.3%** over naive vector+BM25 (retrieval-quality proxy — see the 2026-07 update above; canonical numbers in `benchmarks/pg-agents-results.md`). I've never seen this specific approach published, and on that corpus it beats the full-graph-traversal modes on top score while being 3-4x faster.

### 2. The architecture is actually PostgreSQL-native ✅
- No Apache AGE (works on every managed PG provider: RDS, Supabase, Neon, Cloud SQL)
- Adjacency tables + recursive CTEs + pgvector + BM25 in a single SQL query for hybrid retrieval
- Everything auto-migrates on first connect
- ~1,500 LOC core library

### 3. The ingestion pipeline is fast ✅
- Parallel LLM extraction (asyncio + semaphore)
- Batched entity embeddings (one call for N entities)
- Per-document transactions (atomic, no race conditions)
- Content hash dedup (re-ingestion is free)
- Throttle profiles (conservative/balanced/aggressive/max) so it doesn't kill your server
- With OpenAI gpt-4o-mini and `aggressive` profile: **~5s per document** for real engineering docs

### 4. The test suite is real ✅
- **115 passing tests** at v0.3.0 (887 as of 0.5.0a19) — unit + integration + E2E + server + cleanup-sprint regression tests
- Unit tests for chunking, config, models, embedding protocols, extraction prompts
- Integration tests hitting real PostgreSQL with real schema
- E2E tests covering the full ingest → query flow
- Regression tests for every AAT finding: merge_entities, migration runner, MCP sandbox, stale-doc replace, prune_orphans, ask() fallback
- Conftest doesn't wipe benchmark data (learned the hard way)

### 5. Documentation is dense and honest ✅
- User guide with all 6 query modes
- Devmem guide for the dev KB use case
- Research docs comparing us to LightRAG, postgres-graph-rag, graphrag-psql, Apache AGE
- Benchmark results (including the ones where we lose)
- Blog post for the narrative

### 6. Supply-chain conscious ✅
We dodged the litellm supply-chain attack (March 2026, versions 1.82.7-1.82.8) by using httpx directly against OpenAI-compatible APIs. Zero LLM-framework dependency.

### 7. Smart mode routing actually works ✅
Confidence-triggered routing (high → naive fast path, medium → graph boost, low → local expansion) delivers boost-level top scores with latency close to naive. On the pg-agents corpus: **+19.3% top score at 91 ms vs naive's 85 ms** (retrieval proxy; `benchmarks/pg-agents-results.md`). The fast path stays fast.

---

## What's Mediocre

### 1. The 5 retrieval modes are overwhelming ⚠️
We have `naive`, `naive_boost`, `smart`, `local`, `global`, `hybrid`. That's too many. A new user has no idea what to pick. The defaults are right (`smart`), but the mode explosion is going to cause confusion. I'd cut `global` and `hybrid` from the public API and keep them as internal helpers.

### 2. LLM-dependent tests still excluded from default CI ⚠️
The core suite (115 tests at v0.3.0; 887 at 0.5.0a19) runs without a live LLM. But `test_real_llm.py`, `test_user_journey.py`, `test_retrieval_comparison.py`, `test_graph_wins.py` need a live LLM and are excluded from `pytest` default. CI only runs the LLM-less suite. The LLM tests run manually.

### 3. The SEC 10-Q gold-QnA results are bad and we never fixed it ⚠️
47% accuracy on 195 gold-standard SEC multi-doc questions. All modes score roughly the same. We never dug into why — it's almost certainly a chunking issue with financial tables (dollar amounts get split across chunks). We wrote it off as "chunking limitation, not retrieval issue" but never fixed the underlying problem.

### 4. The README example showed a non-existent feature — fixed ✅
Original README had `print(result.answer)` but `result.answer` was always empty. Fixed: `rag.ask()` now generates grounded answers via the configured LLM (or falls back to top-chunk summary). `pgrg ask` CLI and `/ask` HTTP endpoint both work.

### 5. Small corpus benchmarks misled us for a while ⚠️
We ran hours of benchmarks on NTSB (20 docs), SCOTUS (390 docs), SEC (20 docs), PostgreSQL docs (31 docs) and concluded graph RAG's advantage was "narrow." Then we tested on pg-agents (a few hundred interconnected docs) and got a +19.3% top-score lift (retrieval proxy). **The previous results weren't wrong, they just didn't stress the graph.** Small corpora make vector search look better because top_k=10 already returns most relevant chunks. We should have tested at scale first.

### 6. Our entity extraction has false positives ⚠️
Example: `goodman` was extracted as a `person` entity from a BERT vocab file. The LLM sees any capitalized word in a list of words and thinks it's a name. No filter against this. A query about "goodman" returns vocab.txt as the top result. Real people's names in the corpus get conflated with vocabulary tokens.

---

## What's Rough / Bad

*(Items marked ✅ have been addressed in v0.3.0. Historical context kept for honesty.)*

### 1. Ingestion fails on edge cases in production — mostly fixed ✅
During the 909-doc pg_agents ingest we saw deadlocks and Pydantic validation errors (~5% of docs lost). Fixed in v0.3.0:
- **Deadlock retry** — 3× exponential backoff on SQLSTATE 40P01/40001, using `e.sqlstate` (not locale-sensitive string matching)
- **Failed/degraded counters** — ingest now surfaces `failed` (gave up after 3 retries) and `degraded` (extraction failed, stored as pure vector) in stats and per-file CLI output

### 2. No incremental update story ✅
Fixed: changed files are atomically replaced — stale doc DELETE and new doc INSERT happen in the same transaction. Content hash dedup still skips unchanged files. `prune_orphans()` cleans up unreferenced entities.

### 3. No entity update/deletion API ✅
Fixed: `delete_document(source_path)`, `delete_entity(id)`, `merge_entities(keep_id, merge_ids)`, `prune_orphans()` are all live and tested. `merge_entities` repoints relationships, drops self-loops, deduplicates edges, and atomically removes merged entities.

### 4. Graph visualization only exists in the demo UI ❌
The `/graph` endpoint returns nodes/edges for vis-network. No CLI export or SDK method for DOT/GraphML/JSON. Still open.

### 5. "Smart mode" is a misleading name ❌
It's threshold-based routing, not AI. Better names: `auto`, `routed`, `tiered`. Too late to rename without breaking callers — but the CLI help now makes it clear this is routing logic, not magic.

### 6. Dev KB extraction prompt is only half-tuned ❌
The `dev` prompt works, but on pg_agents we still get too many `concept` entities. Needs few-shot examples with specific entity types. Still open.

### 7. No answer generation ✅
Fixed: `rag.ask()` calls the LLM with retrieved chunks and returns a grounded answer with source citations. Falls back to a top-chunk summary when no LLM is configured. `pgrg ask` CLI and `/ask` HTTP endpoint both work.

### 8. MCP server advertised but not built ✅
Fixed: `pgrg mcp-serve` runs a stdio MCP server with path sandbox, per-tool error boundaries, and `confirm=True` guard on destructive operations.

### 9. No LangChain / LlamaIndex adapters ❌
Still not built. Would be 30-50 lines each. Open.

### 10. No real CI/CD ✅
Fixed: `.github/workflows/test.yml` runs ruff + unit + integration against a pgvector service container on every push.

### 11. The Docker setup is dev-only ✅
Fixed: `Dockerfile` builds from local source, `docker-compose.prod.yml` uses it, `DEPLOY.md` covers single-node Docker, managed Postgres, embedded use, sizing, backups, upgrades, and LLM-less mode.

### 12. Schema migration is CREATE IF NOT EXISTS only ✅
Fixed: `sql/migrations/NNN_*.sql` files are applied in numeric order on every connect, tracked by filename in `pgrg_applied_migrations` (not just a single version int). Advisory lock prevents concurrent apply races.

---

## What's Missing Entirely

Things we didn't even attempt:

1. **Community detection / topic clusters** — no Leiden algorithm, no global summaries
2. **Hierarchical retrieval** — flat entity graph only
3. **Cross-encoder reranking** — would likely add another +5-10% accuracy
4. **Query rewriting** — single-shot queries only
5. **Conversational memory** — no chat context across queries
6. **RBAC / row-level security** — anyone with DB access sees all namespaces
7. **Audit logging** — no record of who queried what
8. **Rate limiting** — server endpoint has no throttling
9. **Streaming responses** — query returns all chunks at once
10. **Observability** — no metrics, no tracing, no structured logging
11. **Backup / export** — standard PG backups work, but no app-level export
12. **Semantic chunking** — chunker is heading-aware and code-aware but doesn't use embeddings for semantic boundaries

---

## What We Got Genuinely Right

Despite the list of gaps above, there are real wins worth documenting:

### Design decisions that survived contact with reality:

**Rejecting Apache AGE.** Was tempting, would have been wrong. AGE doesn't work on most managed PG providers (`shared_preload_libraries`, Azure-only), and while its `cypher()` calls can be composed with pgvector in one SQL statement (see the 2026-07 update), the composition is awkward, agtype-cast-heavy, and undocumented outside Azure's fork. Our recursive CTE approach is plain SQL and portable.

**Dropping litellm.** Saved us from the March 2026 supply-chain attack. Our httpx-based LLM client is 50 lines and works with any OpenAI-compatible API.

**Local embeddings by default.** fastembed is 65MB and works out of the box. No API key needed to `pip install` and try the tool.

**Per-document transactions.** Fixed the race condition bug we hit with parallel ingestion. Every doc is atomic.

**Namespace isolation.** Trivial to separate different projects/repos without spinning up new databases.

**Profile-based throttling.** `conservative`/`balanced`/`aggressive`/`max` lets users pick their CPU budget explicitly. We validated that `aggressive` uses ~8 cores and doesn't kill the host.

### What we learned that changed our design:

- **Graph boost beats graph traversal on top-K re-ranking.** This was a surprise. We built `local` mode first, then `naive_boost`, and naive_boost ended up being the better strategy.

- **Small corpora hide graph RAG's value.** If we'd only tested on NTSB/SEC/SCOTUS/PG docs, we'd have shipped a library with no measurable retrieval improvement. pg_agents (a few hundred interconnected docs) revealed the retrieval-quality win.

- **SEC filings need structured extraction.** Financial tables don't chunk well as text. A future version needs table-aware extraction for 10-Q/10-K docs.

- **Real LLMs expose real bugs.** Our early tests with a fake LLM URL hid the silent cache poisoning bug, the extraction failure cascading, and the deadlock issues. Real LLMs surface real problems.

---

## Should You Use This?

### Yes, if:
- You're already on PostgreSQL and want graph-enhanced RAG
- You have 100+ interconnected documents (codebase, wiki, incident reports, specs)
- You're OK writing your own answer generation layer
- You can tolerate a few percent of docs failing during ingestion
- You're willing to re-ingest your corpus when things change
- You want to own your data (not a SaaS)

### No, if:
- You need <10 LOC integration (there's no drop-in RAG replacement here)
- You need answer generation out of the box
- You need schema migrations or deployment tooling
- You're on a small corpus (<100 docs) — just use pgvector directly
- You need row-level security or audit logging
- You need MCP/LangChain/LlamaIndex adapters today

---

## Realistic Next Steps (ordered by impact)

*(Items 1-6 are done as of v0.3.0. Remaining gaps in order of impact:)*

1. **Fix the SEC 47% ceiling** — investigate the chunking issue, add table-aware extraction, see if we can hit 70%+ on gold-standard multi-doc financial questions.

2. **Dev KB extraction prompt few-shot tuning** — reduce the `concept` entity fallback rate. Add 3-5 per-type examples to the `dev` prompt.

3. **LangChain / LlamaIndex adapters** — `PGRagGraphRetriever(BaseRetriever)` is ~30 lines. Unlocks the existing ecosystem.

4. **Entity dedup sweep** — after ingestion, optionally run a merge pass for entities like `OpenAI` / `Open AI` that slipped past resolution at ingest time.

5. **Cross-encoder reranking** — would likely add further lift on top of the graph boost. *(Shipped since: `src/pg_raggraph/reranker.py`.)*

---

## Final Grade (v0.3.0)

- **Architecture:** A- (sound, portable, novel graph-boost approach)
- **Implementation:** B+ (115 tests at the time, all AAT findings fixed, shared client pool, proper migration tracking)
- **Documentation:** A- (honest benchmarks, complete API docs, accurate feature list)
- **Production readiness:** B (deploy story exists, CI runs, retry + migration + MCP all work; still missing LangChain adapters and cross-encoder reranking)
- **Innovation:** A (the graph-boost + smart routing approach is a real contribution)
- **Honesty:** A+ (we've benchmarked where we fail and documented it)

**Overall: B+.** The core engine is genuinely production-capable. Answer generation, MCP server, CI, CRUD API, migration framework, and deploy story are all shipped. What remains is accuracy ceiling work (SEC benchmark), ecosystem adapters (LangChain/LlamaIndex), and prompt tuning for the dev KB.

---

## Changelog

- **2026-07-07** — Claims audit update: re-captioned the pg-agents lift as a retrieval-quality proxy (canonical source `benchmarks/pg-agents-results.md`), corrected the AGE/pgvector composability claim per Microsoft's HorizonDB doc, recorded current test count/version, and marked v0.3.0-era sections as historical. Triggered by the AAT external audit (`skill-output/aat/AAT-Teardown.md`, findings F-1..F-8).
- **2026-04** — Cleanup-sprint update (see "2026-04 Update" section).
- **Original** — Written against v0.3.0.
