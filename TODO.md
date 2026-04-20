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

_All three items shipped in `edb6cc3` (2026-04-20). Replication table complete; docs + integration tests landed._

| id | item | status | notes |
|---|---|---|---|
| T-01 | Re-judge `acme__hier_smart.json` | ✅ done | pgrg 4/30 (−2 vs sa 6/30), age 4/30. Consistent regression pattern. Cost $0.026. |
| T-02 | Document `chunk_strategy="hierarchy"` in README + user-guide | ✅ done | Config table + chunking section updated; both link ACME-HIER-REPLICATION.md. |
| T-03 | Integration test: ingest with `chunk_strategy="hierarchy"` | ✅ done | Two tests in `tests/integration/test_ingestion.py`: heading-prefixed + title-prefix fallback. 100 tests pass. |

## P1 — strategic questions that gate everything downstream

These three are decision/research items, not pure implementation. Resolve them first because they shape the order of the P2 work.

| id | item | effort | notes |
|---|---|---|---|
| **T-G1** | **Graph-approach review** | ✅ done | `docs/graph-direction-decision.md`. Recommendation: **keep graph tables, supplement retrieval with LightRAG dual-level, demote graph retrieval modes in positioning.** Per-class bakeoff analysis shows graph modes don't beat naive on any class including multi-hop bridging (2/6 across all modes). Three follow-ups spawned: T-G2 (dual-level retrieval experiment), T-G3 (positioning rewrite), T-G4 (by-class bakeoff reporting). |
| T-07 | **Chunkshop direction.** Chunkshop is a bake-off path dep today. Is it (a) meant to become a pg-raggraph runtime dep, (b) staying bake-off-only, or (c) the standalone home for future chunkers? | discussion, not effort | Blocks T-08, T-20, T-21. User's stated preference: **integrate chunkshop first, then do pg-src + MS GraphRAG on top of it.** That implies (a) or (c) — confirm before scheduling T-08. |
| T-08 | **Chunkshop integration** (if T-07 = a or c). | 4-6 hours | Depending on (a) vs (c): either port the chunkshop package into pg-raggraph as a runtime dep with a clean wrapper, or write `docs/chunkshop-integration.md` showing how to run chunkshop → pgvector → `GraphRAG.connect(skip_ingest=True)`. Replicate the factorial-embedding story. |

## P1 — productionize for public GitHub repo

Repo is publishable but not polished. Current state: LICENSE (MIT) ✓, CI lint job ✓. Missing: the standard community-facing scaffolding, a security posture, and a verified reproducibility story.

| id | item | effort | notes |
|---|---|---|---|
| T-P1 | Run `/secret-scan` before any public push | ✅ done | Clean. Report at `skill-output/secret-scan/secret-scan-report.md` (local-only). Zero real keys in tree or history. Both `.env` files gitignored. |
| T-P2 | Add `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` | ✅ done | All three shipped in `5091f34`. CoC adopts Contributor Covenant v2.1 by reference. SECURITY points to `matt@theyonk.com` + GitHub private advisories. |
| T-P3 | GitHub issue + PR templates under `.github/` | ✅ done | Bug / feature / question issue templates + PR template with test plan + benchmark-impact checklist. Blank issues disabled; security reports routed to private advisories. |
| T-P4 | CI — run real tests, not just lint | ✅ already done | Existing `test.yml` runs unit + integration + E2E against a pgvector service container. TODO had overstated the gap. |
| T-P5 | Re-run `/prod-ready` against current `main` + act on the real gaps | **next up, running now** | Existing audit is 8 days pre-bakeoff. Fresh run will write to `skill-output/prod-ready/`. Fixes still need per-item approval before shipping. |
| T-P6 | Re-run `/aat` external lens + act on open P0/P1 items | 1-2 days | Sequencing: run this after T-P5 so the reports can reference each other. |
| T-P7 | PyPI publish workflow | 2-3 hours, **needs user input** | Blocks on: (a) confirmed package name on PyPI (`pg-raggraph` vs `pg_raggraph`), (b) TestPyPI + PyPI tokens as GH secrets, (c) semver policy call. |
| T-P8 | `uv sync --frozen` in CI | ✅ done | `uv.lock` was already tracked; CI now runs `uv sync --all-extras --frozen` so lockfile drift fails the build. |
| T-P9 | README tightening for first impression | 2 hours, **needs user input** | Current headline quotes dev-KB numbers (`+18.9%`). Since the bake-off shipped, headline should either stay dev-KB-focused (with a SCOTUS link) or switch to SCOTUS numbers (with a corpus-shape footnote). Judgment call on which story to lead with. |
| T-P10 | First-run demo that actually works | 2-4 hours incl. recording | `pgrg demo` + a quickstart GIF/video. `/user-test` skill would stress-test the first-run experience. Manual video work toward the end. |

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
| **T-G2** | **LightRAG dual-level retrieval experiment** (from T-G1 decision). Port the query-time low/high keyword extraction + dual entity/relationship vector matching. Ship as `mode="dual_level"` opt-in. | ~1 week + ~$10 bakeoff cost | The one graph-adjacent idea we haven't benchmarked. Promote to default if it beats naive by ≥3 questions on SCOTUS AND holds up on acme. Otherwise, keep as opt-in and lean further into "graph is for explainability, not retrieval." |
| **T-G3** | **Positioning rewrite** — README headline + `docs/modes.md` opening + pg-raggraph-vs-AGE doc per T-G1's "pivot (positioning)" section. | 4-6 hours | Coordinates with T-P9 (README benchmark reconciliation). Should land together; T-P9 alone is a half-solution if the narrative is still "graph-augmented retrieval." Ship before or shortly after the public-repo push. |
| T-20 | **Finish pg code ingestion benchmark.** Started in the `2026-04-17` CHANGELOG entry ("pg-src questions written, extraction pipeline ready, run deferred"). | 4-6 hours + ~$3 | Uses Postgres REL_16_5 executor/planner code (116 .c files) — tests code-corpus chunking + C-language entity extraction. Run via chunkshop once T-08 lands so we're not re-forking chunker logic. |
| T-21 | **MS GraphRAG parity / benchmark / integration.** | scope-dependent, half-day to week | Three sub-options; pick one: (a) **benchmark** — add MS GraphRAG as a third engine in the bake-off alongside pgrg and AGE, measure accuracy + latency on SCOTUS + acme. (b) **parity** — implement community detection (Leiden on the pgrg graph) and hierarchical summaries; measure if they lift global-mode accuracy. (c) **integration** — let users run MS GraphRAG's indexing pipeline and store the output in pgrg's schema. Recommend (a) before (b) or (c). Note: T-G1 decision suggests (b) is unlikely to pay off given the evidence against graph retrieval; prefer (a) as a benchmark-only comparison. |

## P3 — deferred bake-off side work

## P3 — deferred bake-off side work

| id | item | effort | notes |
|---|---|---|---|
| **T-G4** | **By-class bakeoff reporting** — `age-bakeoff report --by-class` flag that breaks accuracy down per question class (semantic / factual / single_hop / multi_hop_bridging). | 1-2 hours | Would have caught the "graph doesn't help bridging" finding in T-G1 automatically instead of needing a one-off python script. Small quality-of-life fix for future sweeps. |
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
