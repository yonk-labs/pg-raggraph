# pg-raggraph — TODO / handoff (2026-04-20)

> Snapshot of pending work after the AGE bake-off dominated several sessions. Hand this to the next session as the "where are we" doc.

## State at handoff

**Last commits on `main`:**
- `bb4dc23` — shipped `chunk_strategy="hierarchy"` as opt-in; softened verdict docs
- `cdab3f9` — acme replication killed the "hierarchy as default" recommendation
- `92ae493` — pg-raggraph vs Apache AGE comparison doc
- `0cc6017`, `9c7b6da` — bake-off hierarchy sweep + verdicts

**Clean tree.** 39 unit tests passing. Lint/format clean. Budget ~$47 of $50.

**What shipped recently:** hierarchy chunker as `config.chunk_strategy="hierarchy"` (opt-in, default stays `auto`). Full rationale in `.autonomy/summaries/post-bakeoff-summary.md` and `benchmarks/age-bakeoff/RETURN-TO-BAKEOFF-2.md`.

---

## P0 — loose ends from the session that just ended

| id | item | effort | notes |
|---|---|---|---|
| T-01 | Re-judge `acme__hier_smart.json` — judge wrapper timed out; file is the only one missing from the 6-mode replication table | 10 min + ~$0.20 | `uv run age-bakeoff judge --corpus acme` with `SKIP_INGEST=1`. ±1 question; does not move the replication story, but closes the data cleanly. |
| T-02 | Document `chunk_strategy="hierarchy"` in `README.md` + `docs/user-guide.md` | 30 min | Neither mentions the new opt-in. Add a "Chunking strategies" subsection referencing `ACME-HIER-REPLICATION.md` for the when-to-use / when-not-to-use call. |
| T-03 | Integration test: ingest a fixture with `chunk_strategy="hierarchy"` end-to-end | ~1 hour | Unit tests cover `_split_hierarchy` in isolation. Need at least one `tests/integration/test_ingestion.py` case that flips the strategy via config and asserts chunk count + first-chunk prefix. |

## P1 — strategic questions that gate everything downstream

These three are decision/research items, not pure implementation. Resolve them first because they shape the order of the P2 work.

| id | item | effort | notes |
|---|---|---|---|
| **T-G1** | **Graph-approach review.** Time-boxed research pass: is the way pg-raggraph does "graph" (adjacency tables + entity extraction + recursive CTE traversal) actually the right primitive, or is it what's capping our accuracy? | **1-2 days, research-heavy** | Evidence we already have: SCOTUS bakeoff showed graph modes tied or underperformed naive once chunking was good (`GRAPH-AUGMENTATION-VERDICT.md`). The +8 lift came from chunking, not graph. Questions to answer: (a) is entity-extraction-from-LLM the wrong primitive? HippoRAG uses entity embeddings instead. (b) Are adjacency-table relationships noise for most queries? (c) Should community detection (MS GraphRAG's Leiden) replace or augment traversal? (d) Is "graph" mostly ceremony on top of what's really vector+BM25+rank — and are we paying latency/complexity for theater? Output: a `docs/graph-direction-decision.md` with keep / pivot / supplement call and an evidence trail. |
| T-07 | **Chunkshop direction.** Chunkshop is a bake-off path dep today. Is it (a) meant to become a pg-raggraph runtime dep, (b) staying bake-off-only, or (c) the standalone home for future chunkers? | discussion, not effort | Blocks T-08, T-20, T-21. User's stated preference: **integrate chunkshop first, then do pg-src + MS GraphRAG on top of it.** That implies (a) or (c) — confirm before scheduling T-08. |
| T-08 | **Chunkshop integration** (if T-07 = a or c). | 4-6 hours | Depending on (a) vs (c): either port the chunkshop package into pg-raggraph as a runtime dep with a clean wrapper, or write `docs/chunkshop-integration.md` showing how to run chunkshop → pgvector → `GraphRAG.connect(skip_ingest=True)`. Replicate the factorial-embedding story. |

## P1 — productionize for public GitHub repo

Repo is publishable but not polished. Current state: LICENSE (MIT) ✓, CI lint job ✓. Missing: the standard community-facing scaffolding, a security posture, and a verified reproducibility story.

| id | item | effort | notes |
|---|---|---|---|
| T-P1 | Run `/secret-scan` before any public push | 15 min | Non-negotiable per `secret-awareness.md` rule. |
| T-P2 | Add `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` | 1-2 hours | None exist. CONTRIBUTING should include: local dev setup, test matrix, PR expectations. SECURITY should name the reporting channel. |
| T-P3 | GitHub issue + PR templates under `.github/` | 30 min | Bug report, feature request, question templates. PR template with test-plan checklist. |
| T-P4 | CI — expand beyond lint: unit tests, integration tests (with service container for PG), coverage threshold | 2-3 hours | Current `test.yml` only runs lint + format. No actual test execution in CI. This is the biggest hole. |
| T-P5 | Re-run `/prod-ready` against current `main` + act on the real gaps | 1-2 days incl. fixes | Existing `ProdReady-FixPlan.md` is 8 days pre-bakeoff (2026-04-12). Fresh audit captures drift. Supersedes / confirms T-14 + T-15 below. |
| T-P6 | Re-run `/aat` external lens + act on P0/P1 items that haven't been addressed | 1-2 days | `AAT-BattlePlan.md` calls out: README honesty gap, LLM setup docs, positioning, demo-that-actually-runs. Check which are done, act on the rest. |
| T-P7 | PyPI publish workflow | 2-3 hours | Tag-triggered GH Action that builds + publishes. Test on TestPyPI first. Documented version policy (semver). |
| T-P8 | Reproducible install story — commit `uv.lock` and wire `uv sync --frozen` into CI | 30 min | Lockfile exists but not verified as CI-enforced. |
| T-P9 | README tightening for first impression | 2 hours | Current headline table shows dev-KB numbers (`+18.9%`). Since the bake-off shipped, the headline should either stay dev-KB-focused with a link to SCOTUS, or switch to SCOTUS with a footnote about corpus-shape sensitivity. Coordinate with T-18. |
| T-P10 | Demo that actually works from scratch | 2-4 hours incl. recording | `pgrg demo` + a quickstart GIF/video. `/user-test` skill could stress-test the first-run experience. |

## P2 — test + doc debt exposed this session

| id | item | effort | notes |
|---|---|---|---|
| T-04 | Re-run `benchmarks/age-bakeoff/tests/` after the chunker port | 15 min | `cd benchmarks/age-bakeoff && uv run pytest` — port was byte-for-byte but verify. |
| T-05 | Add a regression test for the hierarchy title-prefix fallback integrated with the ingest pipeline | ~1 hour | Same as T-03 but specifically covers the fallback path (no headings, title derived from filename). |
| T-06 | Benchmark-result regression guard | 2-3 hours | `benchmarks/` currently produces reports but has no pytest guardrail that catches accuracy drift between commits. Land a smoke test that runs a tiny corpus and asserts ≥ baseline accuracy. |
| T-09 | Decide whether hierarchy's char-based path stays divergent from the token-based default | 1 hour thinking + PR | Hierarchy skips `chunk_max_tokens` by design (mirrors benchmarked behavior). If we keep it, document loudly. If we unify (run token-budget after hierarchy splits), re-run SCOTUS to re-validate the +8 reproduces. |

## P2 — new corpora + parity work (gated on T-07/T-08)

Per user direction: **integrate chunkshop first** (T-07, T-08), then attack these. Running them on today's in-library chunker would fork the chunking story.

| id | item | effort | notes |
|---|---|---|---|
| T-20 | **Finish pg code ingestion benchmark.** Started in the `2026-04-17` CHANGELOG entry ("pg-src questions written, extraction pipeline ready, run deferred"). | 4-6 hours + ~$3 | Uses Postgres REL_16_5 executor/planner code (116 .c files) — tests code-corpus chunking + C-language entity extraction. Run via chunkshop once T-08 lands so we're not re-forking chunker logic. |
| T-21 | **MS GraphRAG parity / benchmark / integration.** | scope-dependent, half-day to week | Three sub-options; pick one: (a) **benchmark** — add MS GraphRAG as a third engine in the bake-off alongside pgrg and AGE, measure accuracy + latency on SCOTUS + acme. (b) **parity** — implement community detection (Leiden on the pgrg graph) and hierarchical summaries; measure if they lift global-mode accuracy. (c) **integration** — let users run MS GraphRAG's indexing pipeline and store the output in pgrg's schema. Recommend (a) before (b) or (c). |

## P3 — deferred bake-off side work

## P3 — deferred bake-off side work

| id | item | effort | notes |
|---|---|---|---|
| T-10 | `/whats-next` run for the project — step 4 of the post-bakeoff autonomy contract, never executed | 30 min | Skill-driven. Will surface items that aren't captured here. Complement to this TODO. |
| T-11 | Third-corpus replication (Wikipedia-shaped titles) | 3-5 hours + ~$2 | Fork B from `RETURN-TO-BAKEOFF-2.md`. Find the boundary between SCOTUS-win and acme-draw. Only worth it if `chunk_strategy="hierarchy"` gets real adoption. |
| T-12 | Smart-mode confidence recalibration | 2-3 hours + ~$3 | The 17-vs-18 SCOTUS gap is within ±1Q noise, per `GRAPH-AUGMENTATION-VERDICT.md` Implications #3. Confirming or moving the boost/expand thresholds requires a bigger question set. |
| T-13 | AGE Cypher-vs-pgrg entity extraction quality comparison | half-day | Original Task 24 scope. Both engines preserve 100% of extractions today — question is whether qualitatively different extraction paths (Cypher node props vs pgrg JSONB) handle ambiguous entity names / cross-doc co-reference differently on an adversarial corpus. |

## P3 — prod-ready carryover from v0.1.0 audit (may be subsumed by T-P5)

`skill-output/prod-ready/ProdReady-FixPlan.md` is from v0.1.0. Spot-check says PR-001 (SQL safety via `psycopg.sql.Identifier`) and PR-003 (logging) already shipped. Remaining items need verification before acting.

| id | item | effort | source |
|---|---|---|---|
| T-14 | Audit ProdReady-FixPlan: mark each of the 16 items done/open against current tree | 1 hour | `ProdReady-FixPlan.md` + grep each acceptance criterion in the repo. |
| T-15 | Re-run `/prod-ready` fresh against current `main` | 1-2 hours | The audit is 8 days pre-bakeoff (2026-04-12). A fresh pass captures drift from the bake-off work. |

## P4 — documentation sprawl check

| id | item | effort | notes |
|---|---|---|---|
| T-16 | Reconcile `docs/FINDINGS.md` with current state | 1 hour | Claims naive "80% on PostgreSQL docs" but that was a pre-bakeoff benchmark. Either update with bakeoff numbers or clearly label as historical. |
| T-17 | `docs/smart-mode-plan.md` — is this still the plan, or outdated by the bakeoff smart-mode finding? | 30 min | Review + either delete or mark as shipped. |
| T-18 | `README.md` benchmark table — currently quotes pre-bakeoff 909-doc dev-KB numbers | 30 min | Decide whether the README headline stays "naive_boost +18.9%" or gets reshaped around the SCOTUS +8 hierarchy result. These measure different things (retrieval quality proxy vs end-to-end accuracy). |

---

## Not doing (explicitly)

- **Heuristic title-quality detection at ingest** — option C from the bake-off fork. Days of work, brittle. Skip unless a concrete use case appears.
- **Making hierarchy the default** — ruled out by acme replication. See `ACME-HIER-REPLICATION.md`.

## Re-classified (was "not doing", now scheduled)

- **pg code ingestion** — deferred from the 2026-04-17 bakeoff work; now scheduled as T-20, gated on chunkshop integration (T-08).

## For the next session — recommended sequence

Per user direction (2026-04-20), the order is:

1. **Clean up the just-shipped hierarchy feature** — T-01, T-02, T-03 as one ~2-hour pass.
2. **T-G1 — graph-approach review.** This is the strategic question that gates everything. If the way pg-raggraph does "graph" is fundamentally limiting, the right move isn't more chunkers or more corpora, it's a pivot. Time-box at 1-2 days of research + a decision doc.
3. **T-07 — chunkshop direction call.** User's preference: integrate chunkshop before pg-src and MS GraphRAG. Confirm (a) vs (c), then schedule T-08.
4. **T-08 — chunkshop integration** per the direction from T-07.
5. **Public-GitHub readiness** — T-P1 through T-P10. Can run in parallel with the chunkshop work since the two don't overlap in files. T-P4 (CI runs actual tests) and T-P5 (fresh prod-ready) are the highest-leverage items in this bucket.
6. **T-20 pg code ingestion + T-21 MS GraphRAG work** — only after T-08 lands, so both consume chunkshop rather than forking chunker logic.
7. Residual: T-10 (`/whats-next`) for cross-check; P2/P3 deferred work as schedule allows.

**Budget-impact items** (flag before starting):
- T-G1 research: $0-5 if we stay in code/docs, more if we run comparison benchmarks.
- T-11 third-corpus replication: ~$2.
- T-12 smart-mode recalibration: ~$3.
- T-20 pg-src bench: ~$3.
- T-21 MS GraphRAG (option a, benchmark): ~$5-10 depending on corpus size and LLM calls.

---

## Pointers

- Full bakeoff session handoff: `benchmarks/age-bakeoff/RETURN-TO-BAKEOFF-2.md`
- Why hierarchy is opt-in: `benchmarks/age-bakeoff/results/ACME-HIER-REPLICATION.md`
- What shipped 2026-04-20: `.autonomy/summaries/post-bakeoff-summary.md` (local-only; `.autonomy/` gitignored)
- Prior prod-ready audit: `skill-output/prod-ready/ProdReady-{GapAnalysis,FixPlan}.md`
- AAT audit: `skill-output/aat/AAT-*.md`
- Research base: `skill-output/research-base/`
