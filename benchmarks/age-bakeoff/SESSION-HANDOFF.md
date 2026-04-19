# Bake-off Follow-up — Session Handoff (2026-04-19 23:30 EDT)

Previous handoff at end of 2026-04-18 session (commit `4762028`). Git tip is still `4762028`; this session has NOT committed. 15 modified files + 5 new files are uncommitted.

## TL;DR in plain English

Last session ran `naive` and `naive_boost` modes — the two modes we'd missed in Phase 2 — hypothesizing they'd clear DC-003's +10 pp fix-threshold. **Neither did** (best lift +3.3 pp = +1 question on scotus/pgrg). The blog's +18.9% naive_boost win turns out to have been on a **different corpus** (pg_agents, a 909-doc codebase) with a **different metric** (avg top_score + high-confidence count, not LLM-judged fully_correct). It didn't transfer to gold-labeled legal QA.

The user's reaction was decisive: **30% accuracy is production-unacceptable. A +10 pp lift at 30% is noise in a broken system.** We pivoted off mode-shopping and onto a **pipeline-root-cause investigation** — the real question is why ~44% of required gold facts never reach the top-K retrieved chunks. If the gold-fact-bearing chunk isn't in the context, no mode / ranking tweak can recover it.

We designed a **factorial chunking × embedding experiment** to isolate which upstream knob actually moves retrieval coverage. Plan is written at `docs/superpowers/plans/2026-04-19-factorial-chunking-embedding.md`. $0 spend, ~45-60 min local, 48 observations.

## What this session produced

### Code changes (uncommitted)
- **`benchmarks/age-bakeoff/src/age_bakeoff/cli.py`**
  - Added `naive_boost` to the `--mode` help text (line ~221)
  - **Bug fix** (2 sites, lines ~345 and ~778): `judge` and `diagnose context-relevance` were skipping labelled raw JSONs (`acme__naive.json` etc.) when invoked with `--corpus acme --corpus scotus`, because the filter checked the raw filename stem rather than the base corpus. Fixed to filter via `_corpus_and_label_from_stem(name)`. Phase 2 results weren't affected because those runs used bare `judge` (no `--corpus` arg); this only bit us when the new harness passed `--corpus` explicitly.
- **`benchmarks/age-bakeoff/src/age_bakeoff/config.py`** — comment listing valid modes updated to include `naive_boost`.
- **`benchmarks/age-bakeoff/tests/test_config.py`** — `+23` lines, 2 new tests: `test_naive_boost_is_accepted_mode` and `test_all_pgrg_modes_accepted`. Test count 97 → 99.
- **NEW `benchmarks/age-bakeoff/scripts/run-mode-sweep.sh`** — instrumented harness. Per-step `timeout 45m`, record-count verification on `results/raw/{corpus}__{label}.json`, diagnostic dump to `/tmp/bakeoff-stall-<ts>-<tag>/` on failure (log tail, `ps`, `docker stats`, both DBs' `pg_stat_activity` + blocked locks, disk free). **Reusable for Task 2.4, MSR, pg-src.** Why it exists: the first 2 subagent attempts at `run --mode naive --corpus scotus` both stalled silently around scotus AGE ingest. Root cause: the subagents combined `ScheduleWakeup` with a foreground Bash — suspending the agent killed its child process. Fix: always `run_in_background: true` for long Bash calls, and never combine them with ScheduleWakeup.

### Data produced (uncommitted)
- **`results/raw/acme__naive.json`, `acme__naive-boost.json`, `scotus__naive.json`, `scotus__naive-boost.json`** — 4 new labelled raw runs. Note: these are gitignored (via `benchmarks/age-bakeoff/.gitignore:5`) — only judge outputs get committed.
- **`results/judge/acme__naive.json`, `acme__naive-boost.json`, `scotus__naive.json`, `scotus__naive-boost.json`** — new.
- **`results/judge/{acme,acme__global,acme__local,acme__smart,scotus,scotus__global,scotus__local,scotus__smart}.json`** — re-judged (majority-vote is stochastic; verdicts shifted by 0-2 questions on each).
- **`results/REPORT.md`** — regenerated, now covers all 12 corpus variants (`+222` lines vs prior).
- **`results/cost-run.json` / `cost-judge.json`** — updated.
- **NEW `results/diagnostics/FINDINGS.md`** — contains the pre-existing diagnostic analysis AND a new addendum documenting the naive_boost sweep, DC-003 verdict, and the two CLI bugs we fixed.

## Headline numbers

`fully_correct` out of 30, per mode per (corpus, engine). Δ is percentage-points vs `hybrid` baseline (the plain `acme.json` / `scotus.json` unlabelled files).

| Mode | acme/age | acme/pgrg | scotus/age | scotus/pgrg | Best Δ |
|---|---|---|---|---|---|
| hybrid (baseline) | 5 | 5 | 11 | 10 | — |
| smart | 4 (−3.3) | 6 (+3.3) | **12 (+3.3)** | 11 (+3.3) | +3.3 pp |
| local | 4 (−3.3) | 6 (+3.3) | 11 (0) | 10 (0) | +3.3 pp |
| global | **6 (+3.3)** | **7 (+6.7)** | 11 (0) | 10 (0) | **+6.7 pp** (acme/pgrg) |
| **naive** | 4 (−3.3) | 4 (−3.3) | 11 (0) | 11 (+3.3) | +3.3 pp |
| **naive_boost** | 4 (−3.3) | 4 (−3.3) | 11 (0) | 11 (+3.3) | +3.3 pp |

**DC-003 threshold is +3 questions (+10 pp). No mode clears it on any cell.**

Retrieval latency p50: pgrg scotus naive/naive_boost = **22-24 ms** (3× faster than smart at 36 ms, 3× faster than hybrid at 70 ms, **~100× faster than AGE at 2,175-2,599 ms**).

## What's known about the ceiling (cite when planning fixes)

1. **Judge is fine.** `gold_strictness.json`: 0/30 paraphrased gold answers judged wrong or hallucinated.
2. **Retrieval coverage is the ceiling.** `context_relevance.json`: ~44% of required gold facts never appear in any retrieved chunk at k=10 on scotus (17/38 pgrg, 16/38 age).
3. **Ranking is not the fix.** `top_k_sweep.json`: k=10 → k=50 lifts scotus/age +5.83 pp, pgrg +0.00 pp. Under threshold.
4. **Mode switches are not the fix.** Table above.
5. **The blog's +18.9% is irrelevant to this benchmark.** `docs/modes.md:340` — measured on `pg_agents` codebase, 20 open-ended dev questions, metric was `avg top_score` + `high-confidence count` (router-routing signal, not answer correctness). Do not cite on scotus.
6. **Retrieval gets ~55-60% of required facts at best** — that's the wall the mode sweep is hitting. Fixing ranking is deck-chair work at this level.

## The factorial experiment (next major work)

**Plan:** `docs/superpowers/plans/2026-04-19-factorial-chunking-embedding.md`

**Design (4 × 3 = 12 cells × 4 probes = 48 observations):**

Chunking variants:
- A: Current (sentence-aware, auto-detect)
- B: Fixed-size + 50% overlap
- C: Hierarchy-aware (section → paragraph, parent header attached)
- D: Current + retrieval-time ±1 neighbor expansion (reuses A's index)

Embedding variants:
- E1: `BAAI/bge-small-en-v1.5` (384-dim, current default)
- E2: `BAAI/bge-base-en-v1.5` (768-dim)
- E3: `nomic-ai/nomic-embed-text-v1.5` (768-dim, different family)

Probes:
- `scotus-q-018` (semantic, fully_correct both engines — **control**)
- `scotus-q-004` (factual, partially_correct — "legal issues in Bostock v. Clayton County")
- `scotus-q-008` (single_hop, partially_correct — "justices who dissented in Apple v. Pepper")
- `scotus-q-025` (multi_hop_bridging, wrong both — "justices who voted majority in Bostock AND dissented in Espinoza" — **thesis case**)

**Measured per cell:** rank of first gold-containing chunk, top-10 hit, top-50 hit, per-fact recall @10. All pure-vector probes, $0 spend, ~45-60 min local.

**Output:** `results/diagnostics/factorial-probe.json` + `results/diagnostics/factorial-probe-REPORT.md`.

**Decision rule:** If any cell lifts `required_facts_matched` on the 3 failing probes by ≥30%, adopt that config and rerun the full bake-off. If no cell moves meaningfully, the ceiling is entity-extraction coverage or gold-fact mismatch, and we move to a second forensic drill.

## Task list on entry

Run `TaskList` to see current state. Snapshot of what was active at handoff:

| # | Status | Task |
|---|---|---|
| 1 | ✅ done | Analyze diagnostic JSONs (FINDINGS.md) |
| 9 | ✅ done | Task 2.3b — naive + naive_boost modes (DC-003 not cleared; documented) |
| **11** | **pending** | **Commit pending bake-off work (naive_boost sweep + harness + CLI fix) — 2 commits** |
| **12** | **pending** | **Factorial chunking × embedding experiment** — blocks everything below until results inform next step |
| 2 | pending (blocked by 12) | Task 2.4 — BM25 isolation via --signals knob |
| 10 | pending (blocked by 12) | Harness: snapshot+restore via PG template databases |
| 3, 4, 5, 6 | pending (blocked by 12) | Phase 2.6 MSR datasets (HotPotQA + Podcasts) |
| 7 | pending (blocked by 12) | pg-src extraction + bake-off run |
| 8 | pending (blocked by 12) | DC-003 fix-threshold gate |

**Task #12 is the gate.** Don't burn MSR / pg-src / BM25 spend on a broken pipeline.

## How to restart cold

1. Read this file.
2. Read `results/diagnostics/FINDINGS.md` for the full ceiling diagnosis.
3. Read `docs/superpowers/plans/2026-04-19-factorial-chunking-embedding.md` for the next experiment.
4. Run `TaskList` — task **#11 comes first** (commit), then **#12** (factorial).
5. Re-dispatch via `superpowers:subagent-driven-development` — same pattern: implementer → spec reviewer → code quality reviewer. **Critical rule learned this session:** subagents that run long Bash commands must use `run_in_background: true`, **never** `ScheduleWakeup`. ScheduleWakeup suspends the agent and kills child subprocesses silently — this caused two stall-then-abandon cycles.

## Environment state at handoff

- Docker: `age-bakeoff-pgrg` (5434) and `age-bakeoff-age` (5435) both up healthy, 3+ days uptime.
- PG data state: pgrg has scotus fully ingested (774 docs, 823 chunks, 420 entities, 4401 relationships); AGE has scotus graph but some ingest churn from the naive_boost runs. Safe to reuse. AGE DB does **not** snapshot state across runs — the bake-off runner re-ingests before every `run`. (Task #10 would fix this.)
- `.env` with OPENAI_API_KEY wired via `load_dotenv()` at CLI entry.
- Tests: 99 passing (97 + 2 new naive_boost tests).
- Git: `main` at `4762028` (unchanged this session), 15 modified + 5 new files, nothing staged.

## Budget

| File | Total |
|---|---|
| `cost-run.json` | $0.2561 |
| `cost-judge.json` | $0.0546 |
| `cost-diagnose.json` | $0.0341 |
| **Session total** | **$0.3448** |
| **Phase total** | **~$0.94** (pre-session tally $0.59 + this session $0.34) |
| **Budget remaining** | **$49.06 of $50** |

## One-line next-session prompt

```
Resume pg-raggraph bake-off follow-up. Read benchmarks/age-bakeoff/SESSION-HANDOFF.md first, then docs/superpowers/plans/2026-04-19-factorial-chunking-embedding.md. Run TaskList. Priority: Task #11 (commit uncommitted work, 2 commits) then Task #12 (factorial chunking×embedding experiment, $0 spend). Budget $49/50 remaining.
```
