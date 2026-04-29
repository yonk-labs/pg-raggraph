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
