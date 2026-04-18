# Bake-off Follow-up — Session Handoff

Last session ended: 2026-04-18 after Phase 2 benchmark sweep on acme + scotus. Git is clean; all work is committed. Latest commit: `300f8e5`.

## TL;DR in plain English

We ran a **head-to-head benchmark** comparing two ways to do GraphRAG (pg-raggraph vs Apache AGE). The original bake-off proved pg-raggraph is **47× faster on SCOTUS**, but *both* engines had low answer quality (17-37% "fully correct"). This follow-up phase was supposed to figure out why the quality is low and find a fix.

**What we just did:**
1. Built 3 diagnostic CLIs that inspect the retrieval pipeline without running benchmarks (gold-strictness, context-relevance, top-k-sweep). These are data-collection tools, not fixes.
2. Added `--mode` and `--label` knobs so we can run the bench with pg-raggraph's different retrieval modes (`hybrid`, `smart`, `local`, `global`) without clobbering prior results.
3. Ran the full bench on acme + scotus with all 4 modes × 2 engines (8 variants, 180 records each). Also ran all 3 diagnostics.
4. Fixed 3 real bugs along the way:
   - `CostTracker` wasn't wired up (SC-015 budget cap was advisory)
   - `PgrgEngine._top_k` was only post-slicing, not driving retrieval (degenerate data above k=10)
   - `.env` file wasn't being loaded into `os.environ` (caused a 16-min run of all-error records)

**The headline:** Speed advantage holds (pg-raggraph 36ms vs AGE 2,389ms on scotus smart mode = **66× faster**). But the quality ceiling is real: **no mode switch moved "fully correct" by more than +2 questions** (out of 30) on any corpus. Best single improvement: pgrg `global` mode on acme (+2 absolute, +7 percentage points). Our bar to declare a fix was **+3 questions (+10 pp)**, so none qualify.

**Total OpenAI spend: $0.59 / $50** — basically nothing.

## What "pp" means

"**pp**" = **percentage points**. It's the DIFFERENCE between two percentages:
- "Raising from 17% to 27% is **+10 pp**" (10 percentage points added)
- "Raising from 17% to 27% is **+59%**" (a 59% relative increase)

We use pp because talking about the "absolute gap" between two accuracy numbers is less confusing than "was 17%, now 27% = 59% improvement."

## Your hypothesis (worth testing)

> "We had issues with getting acme and scotus results getting better with just age, when we looked at source code with more docs it switched heavily as we just did not have enough data points until then. Hoping that pg_source or the Microsoft benchmark will have an impact."

That's a real possibility. Acme is a tiny fixture corpus (6 docs), SCOTUS is ~50 cases. Neither is big enough to stress multi-hop reasoning. Two bigger/harder corpora are still pending:

1. **pg-src** (PostgreSQL executor + optimizer + full SGML docs, ~5-8K chunks). 30 questions already written. Extraction cache not yet run (~$1-2). Would be the "code corpus" showcase.
2. **Microsoft GraphRAG benchmark datasets** (you added this mid-session):
   - **HotPotQA Filtered** — industry-standard multi-hop QA benchmark (Yang et al. 2018). 12MB of text, thousands of gold-labeled questions. Sample ~60.
   - **Kevin Scott Podcasts** — 125 thematic questions (Edge et al. 2024 — the GraphRAG paper). Tests the `global` mode specifically.

Both are pending (Tasks 2.6.1 through 2.6.5). If pg-raggraph beats AGE on HotPotQA's multi-hop questions, that's the strongest possible validation of the bridging thesis.

## Where things stand

### Completed (9 commits this session)
- ✅ Task 0.1: CostTracker wired into runner + judge + CLI (`84bc2d0`, `da4b21b`)
- ✅ Task 0.2: Fact recall + per-class wired into REPORT.md (`c5b7e1e`, `b835796`)
- ✅ Task 1.1: `diagnose gold-strictness` CLI (`1f085e2`, `6ec9d32`)
- ✅ Task 1.2: `diagnose context-relevance` CLI (`76d8ce2`, `3c51d63`)
- ✅ Task 1.3: `diagnose top-k-sweep` CLI + PgrgEngine `_top_k` bug fix (`02fbeff`, `cb4c2d5`)
- ✅ DC-001: drift check passed
- ✅ Task 2.1: `--mode`/`--label` CLI knobs + downstream `__label` handling (`c2b3046`, `27ad78b`)
- ✅ `load_dotenv()` fix in CLI (`10a30ef`)
- ✅ Per-query timeout in runner (`f3e0b3c`)
- ✅ Tasks 2.2 + 2.3: Smart/local/global modes run on acme + scotus + all 3 diagnostics (`300f8e5`)

**Tests: 97 passing**. Budget used: $0.59 of $50.

### Pending tasks (priority order)

**Before DC-003 gate:**
1. **Analyze top_k_sweep + context_relevance data** (NO spend) — the diagnostic JSONs exist at `results/diagnostics/`. If k=50 recovers 10%+ more required facts than k=10 misses, that's a candidate fix with no code change.
2. **Task 2.4** — BM25 isolation via `--signals` knob (needs adding). ~$2. Tests which retrieval signal (vector / BM25 / graph) carries the most weight.
3. **Phase 2.6** — MSR corpora (HotPotQA + Podcasts). ~$5-10. This is your hypothesis test.
    - 2.6.1: fetch datasets
    - 2.6.2: build loaders + convert CSV questions to YAML
    - 2.6.3: LLM extraction (~$3-5)
    - 2.6.4: run bake-off (all modes)
    - 2.6.5: attribution blocks in REPORT/ARCHITECTURE/README
4. **pg-src extraction + run** (Task 5.1, 5.2). ~$1-2 extraction + $2-3 bench. Same test as MSR — does a bigger/harder corpus change the picture?
5. **Task 2.5** — Cross-encoder re-ranking (conditional). Only if 2.4 + MSR both flatline.
6. **DC-003 gate** — did ANY experiment hit +10 pp? If yes: lock via regression test, proceed to Phase 3 writeup. If no: ship the research doc documenting why the ceiling is real.

**After DC-003:**
7. **Phase 3**: Write `QUALITY-ANALYSIS.md` citing all the diagnostic JSONs
8. **Phase 4**: Feature coverage tasks (SC-006 entity resolution, SC-007 incremental ingest, SC-008 concurrent queries, SC-009 AGE tuned indexes)
9. **Phase 5**: pg-src corpus run if not done earlier
10. **Phase 6**: Docs closeout (README, ARCHITECTURE, DC-FINAL)

### Known issues to resolve later
- **Task #26**: Smart-mode hang on SCOTUS was worked around with a 120s per-query timeout — the real hang may still exist in `pg_raggraph/retrieval.py::_smart_query` or `_graph_boost` on large graphs. Didn't recur on the second run — timeout may have been a red herring.
- **Task #25**: Upstream pg-raggraph design flaw — `GraphRAG.query()` should accept `top_k` as a kwarg instead of forcing callers to mutate `config.top_k`.
- **Task #19**: Follow-up refactor — tracker prop-drill (7 files) → `contextvars.ContextVar`. Non-urgent.

## Key numbers from Phase 2 runs (from REPORT.md)

### Fully correct (out of 30 per variant per engine)

| Corpus | Mode | pgrg | age |
|---|---|---|---|
| acme | baseline | 5 | 5 |
| acme | global | **7** | 6 |
| acme | local | 6 | 4 |
| acme | smart | 6 | 4 |
| scotus | baseline | 10 | 11 |
| scotus | global | 10 | **12** |
| scotus | local | 10 | 11 |
| scotus | smart | **11** | 12 |

### Retrieval latency p50

| Corpus | Mode | pgrg (ms) | age (ms) | ratio |
|---|---|---|---|---|
| acme | smart | 23 | 45 | 2× |
| acme | local | 31 | 45 | 1.5× |
| scotus | baseline | 60 | 2,863 | 47× |
| **scotus** | **smart** | **36** | **2,389** | **66×** |

pg-raggraph is getting FASTER under smart mode on SCOTUS (60→36ms). That's a retrieval-infrastructure win independent of answer quality.

## How to restart in a new session

Copy-paste this prompt to resume:

```
Continue the pg-raggraph bake-off follow-up work.

Context:
- Mission brief: skill-output/mission-brief/Mission-Brief-bakeoff-followup.md
- Original brief: skill-output/mission-brief/Mission-Brief-age-bakeoff.md
- Plan: docs/superpowers/plans/2026-04-17-bakeoff-followup.md
- Handoff doc: benchmarks/age-bakeoff/SESSION-HANDOFF.md (READ THIS FIRST)

Git state: main at commit 300f8e5, clean. Tests 97 passing. Budget used $0.59/$50.

Next priorities (in order):
1. Analyze existing diagnostic data at results/diagnostics/{gold_strictness,context_relevance,top_k_sweep}.json — NO spend, just data mining.
2. Task 2.4: BM25 isolation via --signals knob
3. Phase 2.6: Microsoft GraphRAG benchmark (HotPotQA + Podcasts) — this is the big open test
4. pg-src corpus run
5. DC-003 fix-threshold gate

User hypothesis to test: Acme + SCOTUS may be too small to differentiate engines. pg-src
(bigger code corpus) and MSR benchmarks (real multi-hop questions) should reveal actual
differences.

Resume subagent-driven-development skill. Same pattern: implementer + spec reviewer + code quality reviewer per task. Docker containers still up (age-bakeoff-pgrg:5434, age-bakeoff-age:5435). .env has OPENAI_API_KEY. load_dotenv() already wired into cli.py.
```

## Key files to re-read on resume

- `benchmarks/age-bakeoff/results/REPORT.md` — current numbers (8 corpus variants)
- `benchmarks/age-bakeoff/results/diagnostics/*.json` — diagnostic data not yet analyzed
- `benchmarks/age-bakeoff/TODO.md` — original TODO list (some items still live)
- `docs/superpowers/plans/2026-04-17-bakeoff-followup.md` — full execution plan with DC gates
- `skill-output/mission-brief/Mission-Brief-bakeoff-followup.md` — Success Criteria SC-001 through SC-016

## Cost tracking

```
results/cost-run.json       $0.3359  (360 benchmark-run calls)
results/cost-judge.json     $0.2177  (1440 judge calls, majority-vote)
results/cost-diagnose.json  $0.0341  (80 diagnostic calls)
--------------------------------------------------------
Total                       $0.5877  of $50 budget ($49.41 remaining)
```
