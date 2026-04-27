# Phase 1 Regression — `feature/evolution-tier1` sanity check

**Date:** 2026-04-27
**Branch:** `feature/evolution-tier1` @ `9256a26`
**Approach (amended):** unit + integration test suite. **Not** the SCOTUS+acme accuracy subset originally specified — see *Mid-execution pivot* below.
**Hard cap:** 60 min wall (SC-001) — actual: **3 min 4 s**.

## Mid-execution pivot

Plan Tasks 1.1–1.6 originally specified a 20-Q SCOTUS + 10-Q acme accuracy regression via a custom harness. During execution we found:

- The Postgres DBs assumed by the plan no longer hold the prior 772-doc SCOTUS / 160-doc acme corpora used to produce the 18/30 reference baseline (`benchmarks/age-bakeoff/results/REPORT-VERDICT.md`). The bake-off `age_bakeoff_pgrg` DB has only 22 docs in `bakeoff` namespace; the standard `pg_raggraph` DB has `bench_scotus` (391 docs, different corpus shape) and no acme.
- Reproducing the prior baseline corpus would require a 45–60 min re-ingest — blowing the SC-001 1-hour hard cap.

User picked **Option 3** from the four escalation options: pivot Phase 1 to the unit + integration test pass count as the regression signal. Captures whether the Tier 1 retrieval/scoring code regressed at the contract level. The accuracy verification of Task 5's `0.7/0.3 → 0.50/0.20/0.20` weight change is **deferred to Phases 2/3**, where Path A (versioned Python docs) and Path B (medical HRT) run on never-measured-before real corpora — the *real* signal lives there.

## SC-001 (amended) — pass thresholds

| Threshold | Result | Pass? |
|---|---|---|
| All `tests/unit/` + `tests/integration/` pass | **175 passed, 1 xfailed** | YES |
| Wall time ≤ 60 min | **3 min 4 s** | YES |

The 1 xfailed test is the LLM-dependent flake documented in the project memory; xfail expected, not a regression.

## Verdict

**PASS** → proceed to Task 1.7 (merge `feature/evolution-tier1` → `main`).

## Raw output

```
175 passed, 1 xfailed in 183.61s (0:03:03)
```

Run command: `uv run pytest tests/unit/ tests/integration/ --tb=short -q` from `.worktrees/evolution-tier1`.

## What this evidence does and does not cover

**Does cover:**
- All Tier 1 evolution behaviors with explicit unit + integration coverage (retraction filter, `as_of`, `version_filter`, supersession, scoring weights smoke, fixture-corpus pipelines).
- The `tests/fixtures/evolving/{medical_retraction,software_versioning,policy_effective_dates}/` synthetic-fixture flows.
- Migration runner, schema bootstrap, ingest API contract.

**Does NOT cover:**
- Real-corpus accuracy under Task 5's new base weights (`0.50/0.20/0.20`). That's the explicit job of Phases 2 + 3.
- vs-AGE latency / accuracy (the bake-off REPORT-VERDICT remains the prior measurement; not re-validated here).

If a real-corpus accuracy regression slips past Phase 1's pytest gate, Phase 2/3 will catch it: Path A SC-004 demands `≥80% version_filter purity` and Path B SC-006 demands retraction filtering with zero retracted docs in top-5. Both are sensitive to retrieval/scoring drift.
