# pg-raggraph — TODO

Active worklist. Older snapshots live in `docs/archive/TODO.md`.

---

## P0 — Ingest performance audit before public release (2026-04-29)

**Why this exists.** SCOTUS bake-off shows pgrg storage step (post-extraction) takes ~14 min on 772 docs / 416 entities / 4,397 relationships. Apache AGE storage takes ~50 sec on the same input. That's a **17× gap on the storage-only path** (ingest, not LLM extraction). It is paying for real capabilities AGE doesn't have:

- Entity resolution (pg_trgm fuzzy + vector cosine dedup)
- Entity-level embeddings (enables global mode)
- Community detection + summaries
- Embedded-content rewrites for hybrid retrieval

…but **17× is too much** for the work being done. AGE proves the storage floor is much lower.

We will not flip the repo public until pgrg's storage step is within **3×** of AGE on the same SCOTUS input. Stretch target: within 1.5×.

This is not "AGE is the safer bet" — retrieval is the dominant production cost (pgrg is 42-111× faster there) and AGE has architectural blockers (no managed-Postgres support, no pgvector + Cypher composition). But ingest matters too, and our absolute number isn't optimized.

### Workstream

- [ ] **Profile ingest end-to-end on the SCOTUS extraction cache.** Add timing instrumentation around: entity-resolution loop (pg_trgm + vector similarity per-entity), entity embedding batch, community detection, per-document COMMIT cadence, embedded-content rewrites. Same input AGE consumed (`benchmarks/age-bakeoff/src/age_bakeoff/extraction/data/scotus.json`).
- [ ] **Subagent recommendation pass** — collect specific fixes with file:line evidence and expected impact, ranked. (Dispatched 2026-04-29; output landing in `skill-output/perf-audit/`.)
- [ ] **Top likely fixes (validate before implementing):**
  - Batch entity resolution: build a single similarity SQL pass over the whole batch instead of per-entity scans
  - Verify fastembed batching is actually happening (passing list to embed() vs per-string)
  - Make community detection async / post-ingest / threshold-gated
  - Coalesce per-doc transactions into a single transaction per ingest() call, with savepoints for failure isolation
  - Confirm the right pg_trgm GiST/GIN index is in place on `entities.name` and that the planner uses it
  - Ensure pgvector HNSW indexes exist on entity embeddings for the dedup pass
- [ ] **Re-run SCOTUS bake-off ingest after fixes.** Target: ≤3 min storage step (5× win). Stretch: <90s.
- [ ] **Re-run MuSiQue ingest** with optimizations to validate the fix scales.
- [ ] **Document in README/user-guide:** "Ingest cost: ~X sec/doc storage on bge-small-en-v1.5, plus LLM extraction time per provider." Users can plan capacity.
- [ ] **Add an ingest-perf regression test** so we don't silently regress this once it's fixed.

### Definition of done

1. SCOTUS bake-off storage step ≤ 3× AGE on identical input (i.e., ≤2.5 min).
2. README has a real "ingest performance" section with measured numbers.
3. CI guards against regression (smoke test on a small fixed corpus, fails if storage exceeds budget).
4. MuSiQue ingest re-run lands within budget (target: ≤30 min for 1,700 paragraphs end-to-end).

---

## P1 — MuSiQue benchmark (in flight)

Mission: prove (or disprove) that pgrg's graph modes beat naive vector retrieval on a multi-hop corpus. See `benchmarks/musique/README.md`. Currently ingesting (1700 paragraph docs, ~110 min ETA). Eval + writeup to follow.

---

## Closed in recent sessions

See `docs/archive/TODO.md` for the 2026-04-20 snapshot covering T-01..T-08 and the AGE bake-off followups.
