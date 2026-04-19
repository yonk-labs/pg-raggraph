# Return to the Bake-off — Session Handoff (2026-04-19)

**Purpose:** everything a fresh Claude Code session needs to pick up the pg-raggraph vs Apache AGE bake-off where we left it. The factorial chunking/embedding detour is done; results below inform the next round of tests.

---

## 30-second context

- **Main mission:** head-to-head pg-raggraph vs Apache AGE on the scotus corpus (30 gold-labeled legal QA questions, LLM-judged `fully_correct / partially_correct / wrong / hallucinated`).
- **DC-003 ship threshold:** scotus/pgrg `fully_correct` must lift by **≥ +3 questions (+10 pp)** over the hybrid baseline (10/30).
- **What we just proved (factorial detour):** swapping the chunker to hierarchy-aware + the embedder to nomic lifts *pure pgvector* retrieval to **18/30** — +8 questions over baseline, DC-003 cleared by 2.5×. But the factorial **bypassed pg-raggraph's retrieval pipeline** and **never touched AGE**. The real bake-off under the new chunker hasn't been run yet.
- **What's next (tasks 21-24):** port the hierarchy chunker into the bake-off's ingest path, re-run the full 30-Q bake-off on *both engines* across all retrieval modes, analyze whether graph augmentation still adds signal, and write the final pg-raggraph vs AGE verdict.
- **Budget:** ~$49 of $50 remaining. All four remaining tasks combined should spend ~$4.

---

## What happened in the last two sessions (factorial detour)

Full story lives in two places (both committed):

- `benchmarks/age-bakeoff/results/diagnostics/factorial-accuracy-fp32-REPORT.md` — headline 12-cell × 30 Q results
- `benchmarks/age-bakeoff/results/diagnostics/factorial-probe-COMPARE.md` — fp32 vs int8 comparison

**Top-line factorial findings (already committed, referenced by tasks 21-24):**

1. **Hierarchy chunker dominates every embedder column.** C/bge-small (15/30) > A/nomic (11/30). The chunker matters more than the embedder.
2. **C/nomic fp32 = C/bge-small int8 = 18/30 fully_correct.** +8 over the 10/30 baseline.
3. **Int8 is strictly ≥ fp32 in aggregate** (160 vs 152 across 12 cells). 2.3× faster ingest, same or better accuracy. No reason to ship fp32.
4. **Retrieval rank is a lying metric.** The cheap probe declared B/bge-base the winner; end-to-end LLM accuracy said C/nomic. Don't trust top-K-contains-gold-chunk proxies.
5. **Chunks bigger than the embedder's `max_seq_length` get truncated silently.** BGE caps at 512 tokens; the D (neighbor-expand) chunker produces ~2250-token chunks → BGE embedded the first 512 of each, hence D's dead-last finish.
6. **Zero hallucinations** across 720 answers (360 fp32 + 360 int8). Prompt discipline (`"answer only from provided context"`) works.

**What came out of the detour as infrastructure:**

- **`chunkshop`** — standalone monorepo at `/home/yonk/yonk-tools/chunkshop/` + `github.com/yonk-labs/chunkshop` (MIT, v0.2.0). Config-driven ingest tool (source → chunker → embedder → extractor → pgvector sink). Python reference implementation works; Rust + Go ports planned. Hierarchy chunker is here and battle-tested — **we need to port it into pg-raggraph's own code path to make the bake-off fair**.
- **`benchmarks/age-bakeoff/scripts/factorial-accuracy-runner.py`** and **`factorial-probe-query.py`** — both now accept `--precision fp32|int8`. Runs on `factorial.*` schema (fp32) or `factorial_int8.*` schema (int8). Reusable harness if we want to extend.
- **12 populated `factorial.*` tables + 12 `factorial_int8.*` tables** in the pgrg DB — leave them alone unless you need the space back; they're useful for regression checks.

---

## The four tasks ahead

### Task 21 — Port the hierarchy chunker into `age_bakeoff.chunker`

**Goal:** both `PgrgEngine` and `AgeEngine` ingest via the same chunker, selectable between `sentence_aware` (current default — preserves prior baselines) and `hierarchy` (the factorial winner).

**Why this matters:** The bake-off's `extraction/loaders.py:38` calls `chunk_text(text=doc["content"], document_id=doc["id"])`. Both engines consume the output. So whatever chunker we wire up lands on *both* sides of the comparison — fair fight.

**Files to touch:**

- `benchmarks/age-bakeoff/src/age_bakeoff/chunker.py` — add `_split_hierarchy(text)` (port from `chunkshop/python/src/chunkshop/chunkers/hierarchy.py`); add a `strategy: Literal["sentence_aware", "hierarchy"]` kwarg to `chunk_text()` with default `"sentence_aware"`.
- `benchmarks/age-bakeoff/src/age_bakeoff/extraction/loaders.py` — accept an optional `chunker_strategy` arg (or read from env `BAKEOFF_CHUNKER`), pass through to `chunk_text()`.
- `benchmarks/age-bakeoff/src/age_bakeoff/runner.py` (or wherever the extraction loader is invoked from the CLI) — surface `--chunker hierarchy|sentence_aware` CLI flag.
- Tests: `benchmarks/age-bakeoff/tests/test_chunker.py` — add a `test_hierarchy_prefixes_heading` case. Keep all existing sentence-aware tests passing.

**Ported implementation reference:** `chunkshop/python/src/chunkshop/chunkers/hierarchy.py` — copy the logic, not the chunkshop types. The bake-off has its own `Chunk` model. Key behaviors to preserve:
- Splits on markdown headings (`^#{1,6}\s+.+$`)
- Prepends the heading text to each section's embedded content: `f"{heading}\n\n{body}"`
- `min_section_chars=100` default (drops short sections)
- Falls back to plain split if no headings

**Success criteria:**
- `uv run pytest tests/test_chunker.py` passes
- `BAKEOFF_CHUNKER=hierarchy age-bakeoff ingest --engine pgrg --corpus scotus` produces chunks whose `embedded_content` begins with the section heading
- `BAKEOFF_CHUNKER=sentence_aware ...` reproduces the prior baseline chunks byte-identically (so the old `scotus.json` raw is reproducible from the same seed)

**Don't:** break the `sentence_aware` default. All prior results (`results/raw/scotus__*.json`) must stay reproducible.

### Task 22 — Full bake-off re-run with hierarchy chunking

**Goal:** produce the `results/raw/scotus__hier_*.json` files and the judged `results/judge/scotus__hier_*.json` files for both engines across all retrieval modes.

**Run plan (order of operations):**

```bash
# From benchmarks/age-bakeoff/
export AGE_BAKEOFF_PGRG_DSN="postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg"
export AGE_BAKEOFF_AGE_DSN="postgresql://postgres:postgres@localhost:5435/age_bakeoff_age"
export BAKEOFF_CHUNKER=hierarchy

# pgrg × 6 modes × 30 Qs = 180 Q-runs
for mode in hybrid smart local global naive naive_boost; do
  ./scripts/run-mode-sweep.sh pgrg scotus "$mode" "__hier_$mode"
done

# AGE × 3 modes × 30 Qs = 90 Q-runs (AGE has fewer modes; check src/age_bakeoff/engines/age.py)
for mode in hybrid smart local; do
  ./scripts/run-mode-sweep.sh age scotus "$mode" "__hier_$mode"
done

# Judge everything (~$3-4 gpt-4.1-mini)
age-bakeoff judge --corpus scotus
age-bakeoff report
```

**Expected wall time:** ~30-60 min (AGE is 100× slower per query; see original SESSION-HANDOFF for per-run timings).

**Expected cost:** ~$3-4 (270 answer calls + 270 judge calls at gpt-4.1-mini rates).

**Checkpoint recovery:** `scripts/run-mode-sweep.sh` already has instrumented timeout / diagnostic dump — reuse it. If a cell stalls, logs go to `/tmp/bakeoff-stall-*`.

**Compare to for baselines:**
- `results/judge/scotus.json` — pgrg/hybrid/sentence-aware = 10/30 (original baseline)
- `results/judge/scotus__global.json`, `scotus__local.json`, etc. — previous mode sweep results
- `results/diagnostics/factorial-accuracy-fp32.json` variants A/* cells (same sentence-aware chunker, pure-vector) — a retrieval-only comparison
- `results/diagnostics/factorial-accuracy-fp32.json` variant C/nomic = 18/30 — the pure-vector hierarchy target

### Task 23 — Analyze: does pg-raggraph's graph augmentation add signal on top of hierarchy chunks?

**Goal:** answer *the* thesis question of this bake-off. Either:
- **Graph adds signal:** pgrg/hybrid/hierarchy > 18/30 → pg-raggraph's graph layer is worth shipping as a feature, not just a nice-to-have
- **Graph is noise when chunks are good:** pgrg/hybrid/hierarchy ≈ 18/30 (or less) → pure vector search with hierarchy chunking is all you need; graph augmentation can be demoted to an advanced option

**Comparisons to make (all on scotus, same 30 Qs, same judge):**

| row | engine | chunker | retrieval | expected vs 18/30 |
|---|---|---|---|---|
| 1 | pgrg | sentence-aware | hybrid (baseline) | 10/30 (known) |
| 2 | pgrg | sentence-aware | pure vector (factorial A) | ~12/30 (known) |
| 3 | pgrg | hierarchy | pure vector (factorial C) | **18/30 (known)** |
| 4 | pgrg | hierarchy | hybrid | **this run** |
| 5 | pgrg | hierarchy | smart | **this run** |
| 6 | pgrg | hierarchy | local | **this run** |
| 7 | pgrg | hierarchy | global | **this run** |
| 8 | pgrg | hierarchy | naive_boost | **this run** |

Write up in `benchmarks/age-bakeoff/results/GRAPH-AUGMENTATION-VERDICT.md`: 2-3 page analysis + decision line.

### Task 24 — Head-to-head verdict: pg-raggraph vs Apache AGE

**Goal:** ship the deliverable the whole bake-off exists to produce.

**Output:** `benchmarks/age-bakeoff/results/REPORT-VERDICT.md`. Sections:

1. **Fairness** — both engines under hierarchy chunking + best mode each
2. **Accuracy** — fully_correct/30 per engine × mode
3. **Latency** — p50/p95 per engine (AGE is already known to be ~100× slower on scotus: 2,175-2,599 ms vs pgrg's 22-70 ms)
4. **Operational** — AGE cloud compatibility (only Azure supports `shared_preload_libraries`; no AWS RDS / GCP Cloud SQL / Supabase / Neon) — contrast with pgrg running on stock managed Postgres
5. **Graph quality** — are the entities + relationships AGE extracts comparable to pgrg's?
6. **Recommendation** + caveats

This is the document that closes the mission brief.

---

## Environment & paths

```
Repo root:              /home/yonk/yonk-tools/pg-raggraph
Bake-off:               /home/yonk/yonk-tools/pg-raggraph/benchmarks/age-bakeoff
Chunkshop (sibling):    /home/yonk/yonk-tools/chunkshop  (github.com/yonk-labs/chunkshop)

PG pgrg engine:         localhost:5434  db=age_bakeoff_pgrg  user/pass=postgres/postgres
PG AGE engine:          localhost:5435  db=age_bakeoff_age   user/pass=postgres/postgres
Both containers:        docker ps | grep age-bakeoff  (up 4+ days, healthy)

OPENAI_API_KEY:         loaded from benchmarks/age-bakeoff/.env (via load_dotenv())

Bake-off uv env:        cd benchmarks/age-bakeoff && uv sync --extra dev
                        chunkshop is a path dependency (../../../chunkshop/python, editable)
                        pg-raggraph is a path dependency (../.., editable)
```

## Useful one-liners

```bash
# See which tables the factorial runs populated (fp32 + int8)
psql "$AGE_BAKEOFF_PGRG_DSN" -c "
  SELECT schema_name FROM information_schema.schemata
  WHERE schema_name LIKE 'factorial%'"

# Current commit / branch state
git -C /home/yonk/yonk-tools/pg-raggraph log --oneline -10
git -C /home/yonk/yonk-tools/chunkshop log --oneline -10

# Smoke-run the age_bakeoff runner on a single question after Task 21 changes
cd benchmarks/age-bakeoff && \
  BAKEOFF_CHUNKER=hierarchy age-bakeoff ingest --engine pgrg --corpus scotus --doc-limit 3
```

## Budget accounting

| Spend source | amount |
|---|---|
| Phase 2 mode sweep (prior sessions) | $0.94 |
| Factorial fp32 accuracy run | $0.58 |
| Factorial int8 accuracy run | $0.58 |
| **Total so far** | **~$2.10** |
| **Remaining of $50** | **~$47.90** |
| Estimated task 22 spend | ~$3-4 |

## Commits landed since the last handoff

In `pg-raggraph/`:
- `154e23e` chore(bakeoff): extract chunkshop to standalone repo
- `c5abeba` factorial probe fp32 retrieval results (12 cells)
- `9dccdba` factorial end-to-end accuracy (fp32, 12 cells × 30 Q)
- `182b280` factorial scripts accept --precision fp32|int8
- `b3c1dd5` fp32-vs-int8 comparison report generator
- `6979820` int8 factorial results + fp32-vs-int8 comparison

In `chunkshop/` (github.com/yonk-labs/chunkshop):
- `ab683ae` flip chunkshop default to hierarchy+int8 (v0.2.0)
- `5af76d5` untrack ONNX quantize scratch artifacts

Blog output (one-off deliverable, not part of main project):
- File: `~/blog/blog-factorial-chunking-embedding.md` (2593 words, applied 5 reviewer rewrites).

## Known outstanding concerns

- **Chunkshop repo has a 63 MB `.data` file in commit `212127c`'s history** (not in HEAD). Clone size is inflated. Easy fix if asked: `git filter-repo --invert-paths --path python/3030539e-...data` + force-push; nobody has cloned yet. Deferred pending user call.
- **AGE DB (5435) doesn't snapshot state between runs** — the bake-off re-ingests before every `run` command, so task 22 will need to account for that time. Task #10 from an earlier handoff (PG template-database snapshot+restore) would help but is still pending.

---

## One-line next-session prompt

```
Resume pg-raggraph vs AGE bake-off. Read benchmarks/age-bakeoff/RETURN-TO-BAKEOFF.md, then execute Task 21 (port hierarchy chunker), 22 (full bake-off re-run), 23 (graph-augmentation verdict), 24 (pg-raggraph vs AGE verdict). Budget ~$48 remaining. Start with Task 21.
```
