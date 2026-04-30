# pg-raggraph — TODO

Active worklist. Older snapshots live in `docs/archive/TODO.md`.

---

## P0 — Ingest performance gate ✅ closed 2026-04-29

**Original concern.** SCOTUS bake-off log timestamps showed pgrg's storage step (post-LLM-extraction) at ~14 min vs Apache AGE's ~50 sec on identical input — a 17× gap that we agreed must be explained or fixed before public release.

**Diagnosis.** A subagent perf audit (`skill-output/perf-audit/Ingest-Perf-Recommendations.md`) traced the 14-min figure to the **bake-off adapter**, not pg-raggraph's library code. The adapter at `benchmarks/age-bakeoff/src/age_bakeoff/engines/pgrg.py` issued one transactional round-trip per row — ~10K-50K total `db.execute`/`db.fetch_one` calls. Each one acquired a fresh pool connection, ran `register_vector_async` (which itself fires a SELECT against `pg_type`), executed the statement, committed, and released. That accounted for almost all of the 14 minutes. The library's own ingest path (`src/pg_raggraph/__init__.py:540-699`) already wraps writes in a single `db.transaction()` per document — it never had this bug.

**Fix shipped (commit `22dd18e`):**
- **F1** — Wrap the bake-off adapter's `ingest()` in a single `db.transaction()`. One connection across every INSERT, one COMMIT at `__aexit__`. ~5 lines of structural change.
- **F2** — Pre-build `entity_chunks` and `relationship_chunks` rows in Python via an inverted index, then one `tx.executemany()` per link table.
- **Library helper** — Added `Transaction.executemany()` to `pg_raggraph/db.py` so batched inserts work inside an active transaction (the existing `Database.bulk_insert` opens its own connection and commits).

**Measurement (`benchmarks/age-bakeoff/scripts/time_scotus_ingest.py`, SCOTUS extraction cache):**

| state | wall time | vs AGE (50s) |
|---|---|---|
| Pre-F1 baseline | ~840s (14 min) | 17× |
| Post-F1 | 119s | 2.4× |
| Post-F1 + F2 | 107s | 2.1× |

**Definition of done (target ≤ 3× AGE):** **met.** The remaining 2.1× is real and explainable — pgrg's library does work AGE skips (entity embeddings + HNSW maintenance during insert, `tsvector` search_vector trigger on every chunk, embedded-content rewrites for hybrid retrieval). That's about 70 extra seconds on 416 entities + 816 chunks for capabilities AGE doesn't have.

**Public-release checklist (still open):**

- [ ] Update `research/apache-age-evaluation.md` methodology disclosure with the corrected ingest numbers (current doc never published the bad number, but should explicitly document the bake-off adapter pre/post timings for transparency).
- [ ] Add an ingest-perf smoke test to CI that fails if SCOTUS storage step exceeds a budget (e.g., 3 min on the test box).
- [ ] Add a short "ingest cost" note to README/user-guide so users can plan capacity.

---

## P1 — MuSiQue benchmark (in flight)

Mission: prove (or disprove) that pgrg's graph modes beat naive vector retrieval on a multi-hop corpus. See `benchmarks/musique/README.md`. Currently ingesting (1700 paragraph docs, near completion). Eval + writeup to follow.

---

## P1 — Accuracy roadmap (consolidated, performance-respecting)

Six-step plan in [`docs/proposals/Accuracy-Improvements-Roadmap.md`](docs/proposals/Accuracy-Improvements-Roadmap.md). Constraint: no substantial sacrifice in latency or per-query cost. Total expected lift ~+10-15 pp on MuSiQue with ~+100-150 ms p50 latency and zero added per-query LLM cost.

### Status

- ✅ **Step 1 — `short_answer` mode (commit `fd842d5`).** Validated 2026-04-29. EM 0% → 27%, F1 4.4% → 33% on hybrid. Latency dropped 7.6× on `smart`. DoD met.
- ✅ **Step 2 — cross-encoder reranker (commit `2709f43`).** Validated 2026-04-29. Lifts `naive`/`naive_boost` by +5-7 F1 and +8 pp support recall but regresses `hybrid` slightly (-3.3 F1). **Latency DoD missed** (+1.4 to +3.4 s vs +80 ms target on this CPU box). Default stays `rerank=False` — opt-in only. Follow-up below.
- ✅ **Step 2b — reranker model swap (commits `6cf114a`, validation `9a6c287` and follow-ups).** MiniLM-L-6 + factor=2 shipped as default. 2.4-3.9× faster than bge-reranker-base across modes. Latency DoD met on 2 of 4 modes (naive, hybrid). Accuracy lift is smaller (~31% of bge-reranker's lift on naive) but that's the right tradeoff for a default — power users can still pick `rerank_model="BAAI/bge-reranker-base"` for accuracy-first work. Full numbers in [`benchmarks/musique/results.md`](benchmarks/musique/results.md) v4 section.
- ⬜ Step 3 — PPR over `relationships` (Phase B from PropRAG proposal) — +3-5 pp on multi-hop, +30-50 ms (1 week)
- ⬜ Step 4 — Smart routing tunes — encode "right amount of graph is a little" finding (2-3 days)
- ⬜ Step 5 — Propositions (Phase A from PropRAG proposal) — +3-5 pp standalone (1 week)
- ⬜ Step 6 — PPR over proposition cliques (Phase C) — +5-10 pp combined (1 week)

> **MuSiQue tuning parking-lot:** comprehensive list of unexplored ideas (chunkshop strategies, MiniLM-L-12, per-mode rerank flag, embedder swap variants, HyDE, multi-query) lives in [`benchmarks/musique/tuning-ideas.md`](benchmarks/musique/tuning-ideas.md). Pickup priority captured there. **Not pulling on these now — more relevant work is in the CRM/dev-rel direction.**

---

## P2 — DB-native pg-raggraph (forward proposal, pgrg-native only)

User question: *"is there a way to do these as database functions/primitives? maybe a longer term ask."* Sketched in [`docs/proposals/DB-Native-Ingest.md`](docs/proposals/DB-Native-Ingest.md).

**Hard constraint:** **no pgai integration.** pg-raggraph stands alone, same independence stance as our Apache AGE position. No mandatory new extensions beyond pgvector + pg_trgm.

Three paths sketched:
- **Path A (recommended near-term, if demand):** pgrg-native sidecar HTTP service for embed + extract; SQL functions call it via `pg_net`. The sidecar IS our existing Python code, just bound to a port. ~70% of the value is already pure SQL today (chunking, resolution, graph storage, traversal).
- Path B (long-term aspiration): native pgrx extension. Cloud-extension availability blocks this — same problem that killed AGE for us.
- Path C: PL/Python sidecars-in-process. Strict downgrade vs Path A.

Not committed for execution. Revisit when there's a real user wanting `SELECT pgrg.ingest_record(...)` from a trigger. The in-memory `rag.ingest_records()` API (committed in this session) is the right Python-side answer for now.

Decision branches captured in the roadmap; Tier 3 ideas (HyDE, multi-query) explicitly deferred as `smart`-mode escalations only.

Sub-proposal: [`docs/proposals/PropRAG-on-Postgres.md`](docs/proposals/PropRAG-on-Postgres.md) covers Steps 3, 5, 6 in depth.

---

## P2 — library ingest improvements (non-blocking, from perf audit F3-F6)

Real but smaller wins on the library's own ingest path. None affect the bake-off comparison; these help the production ingest path users will actually run.

- **F3 — `resolution.py` round-trip reduction.** Combine the exact-match SELECT and fuzzy SELECT into one CTE (saves one round-trip per entity). Verify the `gin_trgm_ops` index actually serves `similarity(name, X) > threshold` with `EXPLAIN ANALYZE` — if `Seq Scan`, switch to `name %% %s` plus `set_limit()`. Estimated 2-3× on per-document resolution cost.
- **F4 — `register_vector_async` once per connection, not per checkout.** Move codec registration to the `AsyncConnectionPool` `configure` callback in `db.py`. Drop the per-call invocations from `execute`/`fetch_all`/`insert_returning_id`/`bulk_insert`/`Transaction.__aenter__`. Pure win, no behavior change. Estimated 1.5-2× on every short-query path. ~10 LOC + helper.
- **F5 — opt-in `bulk_load=true` flag** that drops/rebuilds HNSW + trgm indexes around large initial loads. Only useful for >100K-chunk corpora. Default off; document the read-during-load tradeoff.
- **F6 — opt-in `PGRG_INGEST_FAST=1` env var** to set `synchronous_commit=off` per session. Document the crash-window tradeoff. Marginal but free, only after F1+F2-class fixes.

Recommended order: F4 first (one-line correctness improvement that compounds with everything), F3 next (real cleanup of the resolution path), F5/F6 as power-user knobs.

Full detail in `skill-output/perf-audit/Ingest-Perf-Recommendations.md`.

---

## Closed in recent sessions

See `docs/archive/TODO.md` for the 2026-04-20 snapshot covering T-01..T-08 and the AGE bake-off followups.
