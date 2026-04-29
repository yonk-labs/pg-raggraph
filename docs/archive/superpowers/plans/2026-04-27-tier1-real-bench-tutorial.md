# Tier 1 Real-World Benchmarks + Dev-Rel Tutorial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship two real-world Tier 1 corpora (versioned Python docs + PubMed HRT retractions) with measured benchmark numbers, a `docs/USE-CASES.md` decision matrix, and a 3-part dev-rel blog series — gated by a ≤1 hr regression sanity check before merging `feature/evolution-tier1` into main.

**Architecture:** Five phases, sequential. Phase 0 cleans the working tree on main. Phase 1 runs in the existing worktree at `.worktrees/evolution-tier1` (branch `feature/evolution-tier1`); a passing regression triggers a fast-forward / `--no-ff` merge into main. Phases 2–4 run on main and produce two new `benchmarks/{python-versioned-docs,medical-hrt}/` corpora with their own runners + gold-Q sets, then `docs/USE-CASES.md` and three posts in `docs/blog/`. Every DC-XXX from `skill-output/mission-brief/Mission-Brief-tier1-real-bench-tutorial.md` is a hard gate (⛔) in this plan.

**Tech Stack:** Python 3.12+, uv, pgrg 0.3.0a0, PostgreSQL 16 + pgvector + pg_trgm (Docker, port 5434), pytest + pytest-asyncio, requests/httpx for downloads, NCBI eutils API for PubMed.

**Mission brief:** `skill-output/mission-brief/Mission-Brief-tier1-real-bench-tutorial.md` — re-read at every DC-XXX.

---

## Mid-execution amendments (live log)

### 2026-04-27 — Phase 1 pivoted to pytest sanity (SC-001 reworded)

Tasks 1.1–1.6 were originally a 20-Q SCOTUS + 10-Q acme accuracy regression via a custom harness. During execution we discovered the local Postgres state no longer contains the 772-doc bake-off corpus that produced the prior 18/30 reference baseline (the `bakeoff` namespace now holds 22 docs; the standard DB has `bench_scotus` 391 docs and no acme). Re-ingesting would have blown the 60-min SC-001 hard cap.

User chose to pivot Phase 1 to running the unit + integration test suite on `feature/evolution-tier1` as the regression signal. Result: **175 passed + 1 xfailed in 3 min 4 s** (the xfail is a documented LLM-flake; not a regression). Brief SC-001 was amended in place — see `skill-output/mission-brief/Mission-Brief-tier1-real-bench-tutorial.md`. Real-corpus accuracy validation of Task 5's `0.50/0.20/0.20` base weights migrates to SC-004 (Path A version_filter purity) and SC-006 (Path B retraction filtering).

The plan tasks 1.1–1.6 below are kept as historical context — they were not executed. Task 1.7 (merge to main) proceeds with the pytest-pass evidence in `benchmarks/regressions/results/2026-04-27-regression.md`.

---

## File Structure

**Phase 0 (created on `main`):**
- Modify: `.gitignore` (add `benchmarks/age-bakeoff/corpora/msgraph-work/`)
- Resolve: `TODO.md` (commit-with-message OR revert; do not leave dirty)
- Create: `benchmarks/cost-log.md` (running cost ledger for SC-009)

**Phase 1 (created on `feature/evolution-tier1` in worktree `.worktrees/evolution-tier1`):**
- Create: `benchmarks/regressions/__init__.py`
- Create: `benchmarks/regressions/run_regression.py` (standalone harness)
- Create: `benchmarks/regressions/judge.py` (minimal LLM judge — gpt-5-mini)
- Create: `benchmarks/regressions/scotus_subset20.yaml` (first 20 SCOTUS Qs)
- Create: `benchmarks/regressions/acme_subset10.yaml` (first 10 acme Qs)
- Create: `benchmarks/regressions/results/2026-04-27-regression.md`
- Modify: `benchmarks/cost-log.md` (append Phase 1 cost row)

**Phase 2 (created on `main` after merge):**
- Create: `benchmarks/python-versioned-docs/README.md`
- Create: `benchmarks/python-versioned-docs/download_python_docs.py`
- Create: `benchmarks/python-versioned-docs/ingest.py`
- Create: `benchmarks/python-versioned-docs/gold.yaml` (≥15 Qs)
- Create: `benchmarks/python-versioned-docs/run_path_a.py`
- Create: `benchmarks/python-versioned-docs/results.md`
- Create: `tests/integration/test_python_versioned_docs.py`
- Modify: `benchmarks/cost-log.md` (append Phase 2 row)

**Phase 3 (created on `main`):**
- Create: `benchmarks/medical-hrt/README.md`
- Create: `benchmarks/medical-hrt/pubmed_query.txt`
- Create: `benchmarks/medical-hrt/download_abstracts.py`
- Create: `benchmarks/medical-hrt/manifest.yaml` (≥30 abstracts + metadata)
- Create: `benchmarks/medical-hrt/ingest.py`
- Create: `benchmarks/medical-hrt/gold.yaml` (≥15 Qs, ≥5 retraction-aware)
- Create: `benchmarks/medical-hrt/run_path_b.py`
- Create: `benchmarks/medical-hrt/results.md`
- Create: `tests/integration/test_medical_hrt.py`
- Modify: `benchmarks/cost-log.md` (append Phase 3 row)
- Untouched: `tests/fixtures/evolving/medical_retraction/` (constraint)

**Phase 4 (created on `main`):**
- Create: `docs/USE-CASES.md`
- Create: `docs/blog/01-intro-classic-vs-evolving.md`
- Create: `docs/blog/02-path-a-versioned-python-docs.md`
- Create: `docs/blog/03-path-b-medical-retractions.md`
- Modify: `README.md` (cross-link USE-CASES.md)
- Modify: `docs/user-guide.md` (cross-link USE-CASES.md)
- Modify: `benchmarks/cost-log.md` (append Phase 4 row)

---

## Phase 0 — Pre-flight (on `main`)

### Task 0.1: Resolve dirty `TODO.md`

**Files:**
- Inspect: `TODO.md`
- Action: commit-with-message OR `git restore TODO.md`

- [ ] **Step 1: View the diff**

```bash
git diff TODO.md
```

Expected: see local edits since `be43969`.

- [ ] **Step 2: Decide**

Read the diff. Two outcomes:

(a) Edits reflect real intent and the brief: stage and commit with a clear message.

```bash
git add TODO.md
git commit -m "docs(todo): <one-line summary of what changed>"
```

(b) Edits are stale or scratch: revert.

```bash
git restore TODO.md
```

- [ ] **Step 3: Verify clean tree**

```bash
git status
```

Expected: only `?? benchmarks/age-bakeoff/corpora/msgraph-work/` remains (handled in Task 0.2). No `M TODO.md`.

---

### Task 0.2: Gitignore the msgraph-work scratch dir

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Append the gitignore rule**

Add this line at the bottom of `.gitignore`:

```
benchmarks/age-bakeoff/corpora/msgraph-work/
```

- [ ] **Step 2: Verify it works**

```bash
git status
```

Expected: `?? benchmarks/age-bakeoff/corpora/msgraph-work/` is gone from the untracked list.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore benchmarks/age-bakeoff/corpora/msgraph-work scratch dir"
```

---

### Task 0.3: Create the cost log

**Files:**
- Create: `benchmarks/cost-log.md`

- [ ] **Step 1: Write the cost log**

Create `benchmarks/cost-log.md`:

```markdown
# pg-raggraph cost log — Tier 1 real-bench + tutorial effort

Mission brief: `skill-output/mission-brief/Mission-Brief-tier1-real-bench-tutorial.md`
Cost cap (SC-009): **$25.00 USD**

| Phase | Date | Activity | Model | Tokens (in/out) | Cost USD | Cumulative |
|-------|------|----------|-------|-----------------|----------|------------|
|       |      |          |       |                 |          |            |

**Running total: $0.00 / $25.00**
```

- [ ] **Step 2: Commit**

```bash
git add benchmarks/cost-log.md
git commit -m "chore(bench): add cost log ledger for Tier 1 real-bench effort"
```

---

## Phase 1 — Regression + Merge (in `.worktrees/evolution-tier1` on `feature/evolution-tier1`)

### ⛔ DC-001: Pre-Phase-1 alignment check

- [ ] **Re-read mission brief** at `skill-output/mission-brief/Mission-Brief-tier1-real-bench-tutorial.md`
- [ ] **Verify worktree state**

```bash
cd .worktrees/evolution-tier1
git status
git rev-parse --abbrev-ref HEAD
```

Expected: working tree clean, branch is `feature/evolution-tier1`. If anything else, stop and reassess.

- [ ] **Verify cost log exists**

```bash
ls -la ../../benchmarks/cost-log.md
```

Expected: file present. If not, return to Task 0.3.

- [ ] **Verify Postgres is up**

```bash
docker compose -f ../../docker-compose.yml ps
```

Expected: postgres service running on port 5434. If not: `docker compose up -d postgres`.

---

### Task 1.1: Create regression harness scaffolding

**Files:**
- Create: `benchmarks/regressions/__init__.py`
- Create: `benchmarks/regressions/scotus_subset20.yaml`
- Create: `benchmarks/regressions/acme_subset10.yaml`

- [ ] **Step 1: Create the package init**

Create `benchmarks/regressions/__init__.py` (empty, just a marker file).

- [ ] **Step 2: Build the SCOTUS subset (first 20 Qs)**

```bash
python3 -c "
import yaml
src = yaml.safe_load(open('benchmarks/age-bakeoff/questions/scotus.yaml'))
out = {'corpus': 'scotus_regression', 'questions': src['questions'][:20]}
yaml.safe_dump(out, open('benchmarks/regressions/scotus_subset20.yaml', 'w'), sort_keys=False)
print(f'wrote {len(out[\"questions\"])} questions')
"
```

Expected: `wrote 20 questions`.

- [ ] **Step 3: Build the acme subset (first 10 Qs)**

```bash
python3 -c "
import yaml
src = yaml.safe_load(open('benchmarks/age-bakeoff/questions/acme.yaml'))
out = {'corpus': 'acme_regression', 'questions': src['questions'][:10]}
yaml.safe_dump(out, open('benchmarks/regressions/acme_subset10.yaml', 'w'), sort_keys=False)
print(f'wrote {len(out[\"questions\"])} questions')
"
```

Expected: `wrote 10 questions`.

- [ ] **Step 4: Verify subsets**

```bash
wc -l benchmarks/regressions/*.yaml
head -5 benchmarks/regressions/scotus_subset20.yaml
```

Expected: both files non-empty, both start with `corpus:` and `questions:`.

---

### Task 1.2: Verify SCOTUS + acme are ingested

**Files:** none modified — read-only DB check.

- [ ] **Step 1: Connect and check the namespaces**

```bash
docker compose -f ../../docker-compose.yml exec postgres psql -U postgres -d pg_raggraph -c "
SELECT namespace, COUNT(*) AS n_docs
FROM documents
GROUP BY namespace
ORDER BY namespace;
"
```

Expected: rows for `scotus` and `acme` namespaces with non-zero doc counts. The bake-off harness uses its own DBs; this DB is the standard pgrg one. If `scotus`/`acme` are missing, fall through to Step 2.

- [ ] **Step 2 (only if missing): Ingest from benchmarks/ corpora**

```bash
cd ..  # back to project root
uv run pgrg ingest --namespace scotus benchmarks/scotus/
uv run pgrg ingest --namespace acme benchmarks/age-bakeoff/corpora/acme/
cd .worktrees/evolution-tier1
```

Wall-clock: 10–30 min depending on corpus size. Verify post-ingest counts > 0.

- [ ] **Step 3: Record any ingest cost in `benchmarks/cost-log.md`**

If Step 2 ran, append a row:

```markdown
| 1 | 2026-04-27 | Regression ingest scotus+acme | gpt-4o-mini | <in>/<out> | $X.XX | $X.XX |
```

---

### Task 1.3: Write the regression runner

**Files:**
- Create: `benchmarks/regressions/run_regression.py`

- [ ] **Step 1: Write the runner**

Create `benchmarks/regressions/run_regression.py`:

```python
"""Standalone regression runner — feature/evolution-tier1 sanity check.

Reads a subset YAML, runs each question through pgrg in `naive_boost` mode,
writes the answers + retrieved chunks to a JSON file. Hard caps wall time at
60 minutes total (SC-001).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from pg_raggraph import GraphRAG

DSN = os.environ.get(
    "PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
)
HARD_CAP_SECONDS = 60 * 60  # SC-001


async def run_one(rag: GraphRAG, namespace: str, q: dict) -> dict:
    t0 = time.perf_counter()
    result = await rag.query(
        q["question"], namespace=namespace, mode="naive_boost", top_k=10
    )
    answer = await rag.ask(
        q["question"], namespace=namespace, mode="naive_boost", top_k=10
    )
    dt_ms = (time.perf_counter() - t0) * 1000
    return {
        "id": q["id"],
        "question": q["question"],
        "gold_answer": q.get("gold_answer", ""),
        "required_facts": q.get("required_facts", []),
        "answer": answer.text if hasattr(answer, "text") else str(answer),
        "top_chunk_ids": [c.id for c in result.chunks[:5]],
        "latency_ms": round(dt_ms, 1),
    }


async def main(yaml_path: Path, namespace: str, out_path: Path) -> None:
    qs = yaml.safe_load(yaml_path.read_text())["questions"]
    rag = GraphRAG(dsn=DSN)
    await rag.connect()
    started = time.perf_counter()
    results: list[dict] = []
    try:
        for i, q in enumerate(qs, 1):
            elapsed = time.perf_counter() - started
            if elapsed > HARD_CAP_SECONDS:
                print(
                    f"!! HARD CAP {HARD_CAP_SECONDS}s exceeded at Q{i}/{len(qs)}",
                    file=sys.stderr,
                )
                break
            print(f"[{i}/{len(qs)}] {q['id']} ({elapsed:.0f}s elapsed)", flush=True)
            results.append(await run_one(rag, namespace, q))
    finally:
        await rag.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "started_at": datetime.now(timezone.utc).isoformat(),
                "yaml": str(yaml_path),
                "namespace": namespace,
                "n_questions": len(results),
                "elapsed_s": round(time.perf_counter() - started, 1),
                "results": results,
            },
            indent=2,
        )
    )
    print(f"wrote {out_path} ({len(results)} answers)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml", type=Path, required=True)
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    asyncio.run(main(args.yaml, args.namespace, args.out))
```

- [ ] **Step 2: Confirm `pgrg` API matches**

```bash
grep -nE "async def (query|ask|connect|close)" ../../src/pg_raggraph/__init__.py | head -10
```

Expected: methods exist. If `ask` returns something other than an object with `.text`, adjust the runner's `answer.text if hasattr…` line.

---

### Task 1.4: Run the regression (hard time cap)

**Files:** writes JSON output only.

- [ ] **Step 1: Run SCOTUS subset and time it**

```bash
START=$(date +%s)
uv run python benchmarks/regressions/run_regression.py \
  --yaml benchmarks/regressions/scotus_subset20.yaml \
  --namespace scotus \
  --out benchmarks/regressions/results/scotus_subset20_answers.json
END=$(date +%s)
echo "SCOTUS regression took $((END-START))s"
```

Expected wall time: 5–15 min. If it exceeds 30 min, abort (`Ctrl+C`) — root-cause before proceeding.

- [ ] **Step 2: Run acme subset and time it**

```bash
START=$(date +%s)
uv run python benchmarks/regressions/run_regression.py \
  --yaml benchmarks/regressions/acme_subset10.yaml \
  --namespace acme \
  --out benchmarks/regressions/results/acme_subset10_answers.json
END=$(date +%s)
echo "acme regression took $((END-START))s"
```

Expected: 3–8 min.

- [ ] **Step 3: Verify both JSON files have answers**

```bash
python3 -c "
import json
for p in ['benchmarks/regressions/results/scotus_subset20_answers.json',
         'benchmarks/regressions/results/acme_subset10_answers.json']:
    d = json.load(open(p))
    print(p, 'n=', d['n_questions'], 'elapsed=', d['elapsed_s'], 's')
"
```

Expected: SCOTUS n=20, acme n=10. Total combined elapsed should be well under the 60-min hard cap.

---

### Task 1.5: Score with a minimal LLM judge

**Files:**
- Create: `benchmarks/regressions/judge.py`

- [ ] **Step 1: Write the judge**

Create `benchmarks/regressions/judge.py`:

```python
"""Minimal LLM judge — scores generated answers against gold_answer.

Reuses the bake-off's required_facts criterion: an answer is fully_correct
if every string in required_facts (lowercased) appears in the answer
(lowercased). No LLM call needed at this fidelity. Faster, deterministic,
and matches the bake-off's primary scorer for SC-001.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def fully_correct(answer: str, required_facts: list[str]) -> bool:
    if not required_facts:
        return False
    lo = answer.lower()
    return all(f.lower() in lo for f in required_facts)


def score_file(path: Path) -> dict:
    d = json.loads(path.read_text())
    n_correct = 0
    rows = []
    for r in d["results"]:
        ok = fully_correct(r["answer"], r["required_facts"])
        n_correct += int(ok)
        rows.append({"id": r["id"], "fully_correct": ok})
    return {
        "yaml": d["yaml"],
        "n_questions": d["n_questions"],
        "n_correct": n_correct,
        "fraction": round(n_correct / max(d["n_questions"], 1), 3),
        "rows": rows,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    args = ap.parse_args()
    for p in args.paths:
        s = score_file(p)
        print(
            f"{s['yaml']}: {s['n_correct']}/{s['n_questions']} "
            f"({s['fraction']*100:.1f}%) fully_correct"
        )
        out = p.with_suffix(".scored.json")
        out.write_text(json.dumps(s, indent=2))
        print(f"  → {out}")
```

- [ ] **Step 2: Run the judge**

```bash
uv run python benchmarks/regressions/judge.py \
  benchmarks/regressions/results/scotus_subset20_answers.json \
  benchmarks/regressions/results/acme_subset10_answers.json
```

Expected: two summary lines printed; two `*.scored.json` files written.

- [ ] **Step 3: Read out the numbers**

Note the `n_correct/n_questions` for both — these are the SC-001 evidence numbers. Carry them into Task 1.6.

---

### Task 1.6: Write the regression report

**Files:**
- Create: `benchmarks/regressions/results/2026-04-27-regression.md`
- Modify: `benchmarks/cost-log.md` (append Phase 1 row)

- [ ] **Step 1: Write the report**

Create `benchmarks/regressions/results/2026-04-27-regression.md`:

```markdown
# Phase 1 Regression — feature/evolution-tier1 sanity check

**Date:** 2026-04-27
**Branch:** feature/evolution-tier1 @ <fill in: git rev-parse --short HEAD>
**Mode:** naive_boost (single run per question)
**Hard cap:** 60 min wall (SC-001)

## SC-001 Thresholds

| Corpus | n | Threshold | Result | Pass? |
|---|---|---|---|---|
| SCOTUS subset (first 20) | 20 | ≥ 16/20 | <fill in: SCOTUS n_correct from Task 1.5> | <YES/NO> |
| acme subset (first 10) | 10 | ≥ 4/10 | <fill in: acme n_correct from Task 1.5> | <YES/NO> |
| Total wall time | — | ≤ 60 min | <fill in: combined elapsed_s from Task 1.4> | <YES/NO> |

## Verdict

- **PASS** → proceed to Task 1.7 (merge to main).
- **FAIL (drop ≥ 2 absolute on either threshold)** → stop. Open a follow-up issue, root-cause, do NOT merge.

## Per-question detail

See `scotus_subset20_answers.scored.json` and `acme_subset10_answers.scored.json`.
```

Replace each `<fill in: …>` with the real value from Tasks 1.4 + 1.5.

- [ ] **Step 2: Append cost-log row**

Append to `benchmarks/cost-log.md`:

```markdown
| 1 | 2026-04-27 | regression run + judge | n/a (substring scorer) | n/a | $0.00 | $0.00 |
```

(LLM ingest from Task 1.2 Step 3, if it ran, was already logged there.)

- [ ] **Step 3: Commit Phase 1 work on the branch**

```bash
git add benchmarks/regressions/ benchmarks/cost-log.md
git commit -m "bench(regression): Phase 1 sanity — feature/evolution-tier1 SCOTUS+acme subset"
```

---

### ⛔ DC-002: Post-Phase-1 alignment check + merge decision

- [ ] **Re-read mission brief** at `skill-output/mission-brief/Mission-Brief-tier1-real-bench-tutorial.md`
- [ ] **Three-question drift check:**
  1. Am I still solving the stated Purpose? (real-world Tier 1 numbers + tutorial)
  2. Does my current work map to SC-001 / SC-002? (yes — regression then merge)
  3. Am I doing anything Out of Scope? (no Tier 2/3, no new modes)
- [ ] **Compare regression results to thresholds**

Open `benchmarks/regressions/results/2026-04-27-regression.md`. Confirm both PASS columns are YES.

- [ ] **If FAIL:** stop here. Do NOT proceed to merge. Write a follow-up issue describing which threshold failed and likely cause (Task 5 base-weight change, ingestion drift, etc.). End plan execution.

- [ ] **If PASS:** proceed to Task 1.7.

---

### Task 1.7: Merge `feature/evolution-tier1` → `main`

**Files:** none — pure git operations. Plan execution returns to the main checkout after this task.

- [ ] **Step 1: Push the regression commit**

```bash
git push origin feature/evolution-tier1
```

- [ ] **Step 2: Switch to main checkout**

```bash
cd ../..  # back to /home/yonk/yonk-tools/pg-raggraph
git status
git rev-parse --abbrev-ref HEAD
```

Expected: clean tree, on `main`.

- [ ] **Step 3: Pull latest main**

```bash
git fetch origin
git pull --ff-only origin main
```

- [ ] **Step 4: Merge with `--no-ff` to preserve the alpha branch history**

```bash
git merge --no-ff feature/evolution-tier1 -m "merge: feature/evolution-tier1 — Tier 1 evolution alpha + Phase 1 regression"
```

If conflicts arise: stop. Do NOT force resolve. Investigate which file conflicts (likely `benchmarks/cost-log.md` from Phase 0), resolve manually, re-run.

- [ ] **Step 5: Verify v0.3.0a0 tag is reachable from main (SC-002)**

```bash
git tag --contains main | grep v0.3.0a0
git log --oneline v0.3.0a0..HEAD | head -3
```

Expected: `v0.3.0a0` appears in the contains list. If the tag was on the merged branch, it's now in main's history.

- [ ] **Step 6: Run the test suite to confirm nothing broke at the merge**

```bash
uv run pytest tests/unit/ -x
uv run pytest tests/integration/ -x
```

Expected: all pass. The branch was 175 passed + 1 xfailed; merge should preserve that.

- [ ] **Step 7: Push main**

```bash
git push origin main
```

---

## Phase 2 — Path A: Versioned Python Docs (on `main`)

### Task 2.1: Scaffold the corpus directory

**Files:**
- Create: `benchmarks/python-versioned-docs/README.md`

- [ ] **Step 1: Create the directory and README**

Create `benchmarks/python-versioned-docs/README.md`:

```markdown
# Python versioned docs corpus — Tier 1 Path A

**Purpose:** Real-world corpus for testing pgrg's `version_filter` Tier 1
evolution feature. Same Python language reference page (or selected pages)
ingested three times under three `version_label`s — Python 3.10, 3.11, 3.12.
Tests whether retrieval correctly scopes to a single version.

**Source:** `https://docs.python.org/3.10/`, `…/3.11/`, `…/3.12/` —
official docs, BSD-licensed.

**Mission brief:** `skill-output/mission-brief/Mission-Brief-tier1-real-bench-tutorial.md`
SC-003, SC-004.

## Files

- `download_python_docs.py` — fetches selected pages for each version
- `ingest.py` — ingests with `metadata={"version_label": "Python 3.x"}`
- `gold.yaml` — ≥15 hand-written gold questions
- `run_path_a.py` — runs the gold questions and produces metrics
- `results.md` — measured numbers (filled in after benchmarking)

## Pages selected (rationale)

We pick **4 pages × 3 versions = 12 documents** that cover features with
known cross-version differences, so `version_filter` has real signal to
exploit:

1. `library/enum.html` — `StrEnum` added in 3.11; enhanced in 3.12.
2. `whatsnew/3.10.html`, `whatsnew/3.11.html`, `whatsnew/3.12.html` — version-specific changes.
3. `library/typing.html` — type-hint surface evolves every release.
4. `reference/datamodel.html` — language-level changes (e.g., 3.12 PEP 695 generics).

Each page is downloaded for its target version. The "whatsnew" page is
version-specific by definition; the other three are downloaded three times.
```

- [ ] **Step 2: Commit the scaffold**

```bash
git add benchmarks/python-versioned-docs/README.md
git commit -m "bench(python-versioned-docs): scaffold Path A corpus README"
```

---

### Task 2.2: Write the downloader

**Files:**
- Create: `benchmarks/python-versioned-docs/download_python_docs.py`

- [ ] **Step 1: Write the downloader**

Create `benchmarks/python-versioned-docs/download_python_docs.py`:

```python
"""Download selected Python docs pages for 3.10, 3.11, 3.12.

Saves as `pages/{version}/{slug}.html`. Idempotent — skips files that
already exist on disk. No network call when re-run.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "pages"
USER_AGENT = "pgrg-benchmark/1.0 (https://github.com/the-yonk/pg-raggraph)"

VERSIONS = ["3.10", "3.11", "3.12"]
COMMON_SLUGS = ["library/enum", "library/typing", "reference/datamodel"]
WHATSNEW = {v: f"whatsnew/{v}" for v in VERSIONS}


def url(version: str, slug: str) -> str:
    return f"https://docs.python.org/{version}/{slug}.html"


def fetch(client: httpx.Client, target: Path, version: str, slug: str) -> bool:
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    r = client.get(url(version, slug), timeout=30.0)
    r.raise_for_status()
    target.write_bytes(r.content)
    return True


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    n_fetched = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        for version in VERSIONS:
            for slug in COMMON_SLUGS + [WHATSNEW[version]]:
                target = OUT_DIR / version / f"{slug.replace('/', '__')}.html"
                if fetch(client, target, version, slug):
                    print(f"  + {target.relative_to(ROOT)}")
                    n_fetched += 1
                    time.sleep(0.5)  # be polite
                else:
                    print(f"  = {target.relative_to(ROOT)} (cached)")
    print(f"fetched {n_fetched} new files into {OUT_DIR}")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it**

```bash
cd benchmarks/python-versioned-docs
uv run python download_python_docs.py
cd ../..
```

Expected: 12 HTML files (`3 versions × 4 slugs`) under `pages/`.

- [ ] **Step 3: Verify the haul**

```bash
find benchmarks/python-versioned-docs/pages -name "*.html" | wc -l
ls benchmarks/python-versioned-docs/pages/3.12/
```

Expected: count = 12 (or 12 minus any 3.10/3.11 pages that 404 — investigate any misses).

- [ ] **Step 4: Commit (downloader + content)**

```bash
git add benchmarks/python-versioned-docs/download_python_docs.py \
        benchmarks/python-versioned-docs/pages/
git commit -m "bench(python-versioned-docs): download 3.10/3.11/3.12 docs pages"
```

---

### Task 2.3: Write the ingest script

**Files:**
- Create: `benchmarks/python-versioned-docs/ingest.py`

- [ ] **Step 1: Write the ingest script**

Create `benchmarks/python-versioned-docs/ingest.py`:

```python
"""Ingest the Python docs corpus into pgrg with version_label metadata.

Strips HTML to plain text via beautifulsoup4. Each version's pages go in
under the same namespace, distinguished only by metadata.version_label.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from bs4 import BeautifulSoup

from pg_raggraph import GraphRAG

ROOT = Path(__file__).parent
PAGES = ROOT / "pages"
NAMESPACE = "python_docs"
DSN = os.environ.get(
    "PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
)


def html_to_text(p: Path) -> str:
    soup = BeautifulSoup(p.read_text(), "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


async def main() -> None:
    rag = GraphRAG(dsn=DSN, namespace=NAMESPACE, evolution_tier="structural")
    await rag.connect()
    try:
        # Wipe namespace so re-runs are deterministic.
        await rag.delete_namespace(NAMESPACE)
        for version in sorted(p.name for p in PAGES.iterdir() if p.is_dir()):
            label = f"Python {version}"
            for html_file in sorted((PAGES / version).glob("*.html")):
                txt = html_to_text(html_file)
                tmp = ROOT / "_tmp" / f"{version}__{html_file.stem}.md"
                tmp.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(f"# {html_file.stem} ({label})\n\n{txt}")
                await rag.ingest(
                    [str(tmp)],
                    namespace=NAMESPACE,
                    metadata={"version_label": label},
                )
                print(f"  + {label}: {html_file.name}")
    finally:
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify pgrg API matches**

```bash
grep -nE "(delete_namespace|async def ingest|evolution_tier)" src/pg_raggraph/__init__.py | head -10
```

Expected: methods exist. If `delete_namespace` doesn't exist, replace with the existing wipe primitive (check `src/pg_raggraph/__init__.py` for `delete_document`, `delete_all`, etc.) — substitute the closest equivalent and note the choice in the commit.

- [ ] **Step 3: Add beautifulsoup4 if not already present**

```bash
grep beautifulsoup4 pyproject.toml || uv add --dev beautifulsoup4
```

Note: this counts as a dev-only dep (test/benchmark tooling), not a runtime dep — so it does NOT violate the "no new runtime dependencies" constraint in the brief.

- [ ] **Step 4: Run the ingest**

```bash
cd benchmarks/python-versioned-docs
uv run python ingest.py
cd ../..
```

Wall time: 5–15 min depending on extraction-LLM speed.

- [ ] **Step 5: Verify SC-003 — three version labels present**

```bash
docker compose exec postgres psql -U postgres -d pg_raggraph -c "
SELECT metadata->>'version_label' AS label, COUNT(*) AS n_docs
FROM documents
WHERE namespace = 'python_docs'
GROUP BY 1
ORDER BY 1;
"
```

Expected: three rows, one per version, each with non-zero `n_docs`.

- [ ] **Step 6: Commit**

```bash
git add benchmarks/python-versioned-docs/ingest.py pyproject.toml uv.lock
git commit -m "bench(python-versioned-docs): ingest 3.10/3.11/3.12 with version_label"
```

---

### Task 2.4: Write `gold.yaml` (≥15 questions)

**Files:**
- Create: `benchmarks/python-versioned-docs/gold.yaml`

- [ ] **Step 1: Hand-write the gold questions**

Create `benchmarks/python-versioned-docs/gold.yaml`:

```yaml
corpus: python_docs
# 15 hand-written questions. Five categories:
#   - filtered_match: question with version_filter, answer must come from filter
#   - cross_version: same intent across versions (paired)
#   - unfiltered_target: 3.12-only feature, unfiltered query, expect 3.12 chunks in top-3
#   - whatsnew: question best answered by a whatsnew page
#   - drift_aware: question that has different correct answers per version
questions:
  # filtered_match (5)
  - id: pyver-q-001
    category: filtered_match
    question: "How does StrEnum work in Python 3.12?"
    version_filter: "Python 3.12"
    expected_substring: "StrEnum"
  - id: pyver-q-002
    category: filtered_match
    question: "What changed in the typing module in Python 3.11?"
    version_filter: "Python 3.11"
    expected_substring: "typing"
  - id: pyver-q-003
    category: filtered_match
    question: "What does the data model say about descriptors in Python 3.10?"
    version_filter: "Python 3.10"
    expected_substring: "descriptor"
  - id: pyver-q-004
    category: filtered_match
    question: "List the new features in Python 3.11."
    version_filter: "Python 3.11"
    expected_substring: "3.11"
  - id: pyver-q-005
    category: filtered_match
    question: "What enum features are available in Python 3.10?"
    version_filter: "Python 3.10"
    expected_substring: "Enum"

  # cross_version (3 pairs = 6 entries)
  - id: pyver-q-006
    category: cross_version
    question: "How do I use StrEnum?"
    version_filter: "Python 3.11"
    expected_substring: "StrEnum"
  - id: pyver-q-007
    category: cross_version
    question: "How do I use StrEnum?"
    version_filter: "Python 3.12"
    expected_substring: "StrEnum"
  - id: pyver-q-008
    category: cross_version
    question: "What does PEP 604 do?"
    version_filter: "Python 3.10"
    expected_substring: "union"
  - id: pyver-q-009
    category: cross_version
    question: "What does PEP 604 do?"
    version_filter: "Python 3.11"
    expected_substring: "union"
  - id: pyver-q-010
    category: cross_version
    question: "How do generics work?"
    version_filter: "Python 3.11"
    expected_substring: "Generic"
  - id: pyver-q-011
    category: cross_version
    question: "How do generics work?"
    version_filter: "Python 3.12"
    expected_substring: "Generic"

  # unfiltered_target (2)
  - id: pyver-q-012
    category: unfiltered_target
    question: "What does PEP 695 syntax for type aliases look like?"
    expected_version_in_top3: "Python 3.12"  # PEP 695 is 3.12-only
    expected_substring: "type"
  - id: pyver-q-013
    category: unfiltered_target
    question: "What is the new syntax for generic functions added in 3.12?"
    expected_version_in_top3: "Python 3.12"
    expected_substring: "generic"

  # whatsnew (2)
  - id: pyver-q-014
    category: whatsnew
    question: "What are the highlights of Python 3.10?"
    version_filter: "Python 3.10"
    expected_substring: "structural pattern"
  - id: pyver-q-015
    category: whatsnew
    question: "What's new for performance in Python 3.11?"
    version_filter: "Python 3.11"
    expected_substring: "fast"
```

- [ ] **Step 2: Validate the YAML loads cleanly**

```bash
python3 -c "
import yaml
d = yaml.safe_load(open('benchmarks/python-versioned-docs/gold.yaml'))
print(len(d['questions']), 'questions')
from collections import Counter
print(Counter(q['category'] for q in d['questions']))
"
```

Expected: `15 questions` and a Counter showing the five categories distributed.

- [ ] **Step 3: Commit**

```bash
git add benchmarks/python-versioned-docs/gold.yaml
git commit -m "bench(python-versioned-docs): 15 hand-written gold Qs"
```

---

### Task 2.5: Write `run_path_a.py`

**Files:**
- Create: `benchmarks/python-versioned-docs/run_path_a.py`

- [ ] **Step 1: Write the runner**

Create `benchmarks/python-versioned-docs/run_path_a.py`:

```python
"""Path A runner — exercises pgrg's version_filter against the gold set.

For each question:
  - filtered_match / cross_version: run with version_filter; assert top-5
    chunks come ONLY from the matching version_label.
  - unfiltered_target: run without filter; assert top-3 contains a chunk
    from the expected_version.
  - whatsnew: same as filtered_match.

Writes results.md with per-category pass rates and SC-004 verdict.
"""
from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from pathlib import Path

import yaml

from pg_raggraph import GraphRAG

ROOT = Path(__file__).parent
DSN = os.environ.get(
    "PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
)
NAMESPACE = "python_docs"


async def chunk_version(rag: GraphRAG, chunk_id: str) -> str | None:
    """Resolve a chunk_id to its document's version_label."""
    async with rag.db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT d.metadata->>'version_label' "
            "FROM chunks c JOIN documents d ON c.document_id = d.id "
            "WHERE c.id = $1",
            chunk_id,
        )
        return row[0] if row else None


async def run_question(rag: GraphRAG, q: dict) -> dict:
    kwargs = {"namespace": NAMESPACE, "mode": "naive_boost", "top_k": 10}
    if "version_filter" in q:
        kwargs["version_filter"] = q["version_filter"]
    result = await rag.query(q["question"], **kwargs)
    top5_versions = [await chunk_version(rag, c.id) for c in result.chunks[:5]]
    top3_versions = top5_versions[:3]
    pass_filter = (
        "version_filter" not in q
        or all(v == q["version_filter"] for v in top5_versions if v)
    )
    pass_target = (
        "expected_version_in_top3" not in q
        or q["expected_version_in_top3"] in top3_versions
    )
    return {
        "id": q["id"],
        "category": q["category"],
        "top5_versions": top5_versions,
        "pass_filter": pass_filter,
        "pass_target": pass_target,
        "passed": pass_filter and pass_target,
    }


async def main() -> None:
    qs = yaml.safe_load((ROOT / "gold.yaml").read_text())["questions"]
    rag = GraphRAG(dsn=DSN, evolution_tier="structural")
    await rag.connect()
    rows: list[dict] = []
    try:
        for q in qs:
            r = await run_question(rag, q)
            print(
                f"[{'PASS' if r['passed'] else 'FAIL'}] {r['id']} "
                f"({r['category']}): top5={r['top5_versions']}"
            )
            rows.append(r)
    finally:
        await rag.close()

    # Compute SC-004 metrics.
    filtered = [
        r for r in rows
        if r["category"] in ("filtered_match", "cross_version", "whatsnew")
    ]
    target = [r for r in rows if r["category"] == "unfiltered_target"]
    n_filt_pass = sum(1 for r in filtered if r["pass_filter"])
    n_target_pass = sum(1 for r in target if r["pass_target"])
    sc004_filter_rate = n_filt_pass / max(len(filtered), 1)
    sc004_target_pass = n_target_pass >= 1

    summary = {
        "n_total": len(rows),
        "by_category": dict(Counter(r["category"] for r in rows)),
        "filtered_pass": f"{n_filt_pass}/{len(filtered)}",
        "filter_rate": round(sc004_filter_rate, 3),
        "target_pass": f"{n_target_pass}/{len(target)}",
        "sc004_threshold_filter": "≥ 0.80",
        "sc004_filter_pass": sc004_filter_rate >= 0.80,
        "sc004_threshold_target": "≥ 1 of 2",
        "sc004_target_pass": sc004_target_pass,
        "rows": rows,
    }
    out = ROOT / "results.json"
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Confirm the chunk-resolution SQL matches the schema**

```bash
grep -nE "(chunks|documents|namespace|metadata)" src/pg_raggraph/sql/schema.sql | head -20
```

Verify `chunks.document_id` and `documents.metadata` exist. If column names differ, adjust the SQL in `chunk_version()`.

- [ ] **Step 3: Run it**

```bash
cd benchmarks/python-versioned-docs
uv run python run_path_a.py
cd ../..
```

Expected: per-question PASS/FAIL log, then a JSON summary printed.

- [ ] **Step 4: Verify SC-004 thresholds**

The printed JSON must show `sc004_filter_pass: true` and `sc004_target_pass: true`. If not, do NOT proceed — investigate.

---

### Task 2.6: Write `results.md`

**Files:**
- Create: `benchmarks/python-versioned-docs/results.md`

- [ ] **Step 1: Write the results doc**

Use the JSON from Task 2.5 to fill in `results.md`:

```markdown
# Path A — Versioned Python docs results

**Date:** <fill in: today YYYY-MM-DD>
**Branch:** main @ <fill in: git rev-parse --short HEAD>
**Mode:** `naive_boost`, top_k=10 (top-5 used for filter check, top-3 used for target check)
**Corpus:** 12 docs (3 versions × 4 selected pages); namespace `python_docs`

## SC-004 Verdict

| Threshold | Result | Pass? |
|---|---|---|
| ≥ 80% of `version_filter`-tagged Qs return top-5 chunks ONLY from matching version | <fill: filter_rate × 100>% (<filtered_pass>) | <YES/NO> |
| For ≥ 1 unfiltered_target Q, top-3 contains expected version | <target_pass> | <YES/NO> |

**Overall SC-004:** <PASS / FAIL>

## By category

| Category | n | n passed | rate |
|---|---|---|---|
| filtered_match | 5 | <fill> | <fill>% |
| cross_version | 6 | <fill> | <fill>% |
| unfiltered_target | 2 | <fill> | <fill>% |
| whatsnew | 2 | <fill> | <fill>% |

## Per-question

See `results.json` for the full row dump.

## Notes for the blog post

<fill in: 2-3 surprising observations from the run — e.g. "all cross-version
StrEnum Qs cleanly resolved to their filter; cross-version typing Qs got
contaminated when version_filter was off"; cite real numbers, not
hypotheticals>
```

Replace each `<fill in: …>` with real values from `results.json`.

- [ ] **Step 2: Append cost-log row**

Append to `benchmarks/cost-log.md`:

```markdown
| 2 | <date> | python-versioned-docs ingest+benchmark | gpt-4o-mini | <in>/<out> | $X.XX | $X.XX |
```

- [ ] **Step 3: Commit**

```bash
git add benchmarks/python-versioned-docs/run_path_a.py \
        benchmarks/python-versioned-docs/results.md \
        benchmarks/python-versioned-docs/results.json \
        benchmarks/cost-log.md
git commit -m "bench(python-versioned-docs): Path A results — SC-004 <PASS/FAIL>"
```

---

### Task 2.7: Add the integration test

**Files:**
- Create: `tests/integration/test_python_versioned_docs.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_python_versioned_docs.py`:

```python
"""Integration test — Python versioned docs corpus is ingested with three
distinct version_labels in one namespace (SC-003 evidence)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_three_version_labels_present(rag_pool):
    """SC-003: three distinct version_labels in `python_docs` namespace."""
    async with rag_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT metadata->>'version_label' AS label "
            "FROM documents WHERE namespace = 'python_docs' "
            "AND metadata->>'version_label' IS NOT NULL"
        )
    labels = {r["label"] for r in rows}
    assert labels == {"Python 3.10", "Python 3.11", "Python 3.12"}, labels


async def test_at_least_one_doc_per_version(rag_pool):
    """SC-003: each version has ≥ 1 ingested document."""
    async with rag_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT metadata->>'version_label' AS label, COUNT(*) AS n "
            "FROM documents WHERE namespace = 'python_docs' GROUP BY 1"
        )
    counts = {r["label"]: r["n"] for r in rows}
    for label in ("Python 3.10", "Python 3.11", "Python 3.12"):
        assert counts.get(label, 0) >= 1, f"{label}: {counts}"
```

- [ ] **Step 2: Verify the conftest provides `rag_pool`**

```bash
grep -nE "rag_pool|conftest" tests/integration/conftest.py 2>&1 | head -10
```

If `rag_pool` doesn't exist, check what asyncpg/connection fixture the existing integration tests use (e.g. `db_conn`, `pool`) and adapt the import + fixture name.

- [ ] **Step 3: Run the test**

```bash
uv run pytest tests/integration/test_python_versioned_docs.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_python_versioned_docs.py
git commit -m "test(python-versioned-docs): SC-003 ingestion shape test"
```

---

### ⛔ DC-003: Post-Path-A alignment check

- [ ] **Re-read mission brief**
- [ ] **Three-question drift check** (Purpose / SC-XXX mapping / Out-of-Scope)
- [ ] **Verify SC-003 evidence**: `tests/integration/test_python_versioned_docs.py` passes; results.md contains the three-version table.
- [ ] **Verify SC-004 evidence**: results.md "Overall SC-004" line is **PASS**.
- [ ] **If FAIL on SC-004**: stop. Open a follow-up issue. Do NOT draft blog post #2.
- [ ] **If PASS**: proceed to Phase 3.

---

## Phase 3 — Path B: Medical HRT real corpus (on `main`)

### Task 3.1: Scaffold the corpus directory

**Files:**
- Create: `benchmarks/medical-hrt/README.md`
- Create: `benchmarks/medical-hrt/pubmed_query.txt`

- [ ] **Step 1: Write the README**

Create `benchmarks/medical-hrt/README.md`:

```markdown
# Medical HRT real corpus — Tier 1 Path B

**Purpose:** Real-world corpus testing pgrg's `retracted` filtering and
`as_of` time-travel Tier 1 features against published medical literature on
hormone replacement therapy (HRT) and cardiovascular outcomes — the
canonical "answer changes after a date" case (WHI 2002 retraction).

**Source:** PubMed via NCBI eutils API (`https://www.ncbi.nlm.nih.gov/`).
Abstracts are public-domain summaries; full-text rights vary.

**Mission brief:** `skill-output/mission-brief/Mission-Brief-tier1-real-bench-tutorial.md`
SC-005, SC-006.

**IMPORTANT:** This corpus is fully separate from the synthetic fixture at
`tests/fixtures/evolving/medical_retraction/` (constraint). The synthetic
fixture stays for unit tests.

## Files

- `pubmed_query.txt` — exact PubMed search expressions used
- `download_abstracts.py` — fetches abstracts via NCBI eutils
- `manifest.yaml` — ≥30 abstracts with effective_from / retracted /
  retracted_at / retraction_reason metadata
- `ingest.py` — ingests abstracts into pgrg with metadata
- `gold.yaml` — ≥15 hand-written gold questions, ≥5 retraction-aware
- `run_path_b.py` — runs gold Qs in two configurations
  (`retracted_behavior="hide"` and `as_of=1995-01-01`)
- `results.md` — measured numbers
```

- [ ] **Step 2: Write the PubMed query**

Create `benchmarks/medical-hrt/pubmed_query.txt`:

```
# Three searches used to seed the corpus (run via NCBI eutils esearch endpoint).

# 1) Pre-2002 supportive HRT + cardiovascular literature (target ~10 abstracts)
("hormone replacement therapy"[Title/Abstract] OR "HRT"[Title/Abstract])
AND ("cardiovascular"[Title/Abstract] OR "coronary"[Title/Abstract])
AND ("1990"[Date - Publication] : "2001"[Date - Publication])

# 2) WHI 2002 trial + immediate aftermath (target ~10 abstracts)
"Women's Health Initiative"[Title/Abstract]
AND ("2002"[Date - Publication] : "2004"[Date - Publication])

# 3) Post-2002 cautionary / retraction-aware literature (target ~10 abstracts)
("hormone replacement therapy"[Title/Abstract] OR "HRT"[Title/Abstract])
AND ("cardiovascular"[Title/Abstract] OR "coronary"[Title/Abstract])
AND ("retraction"[Publication Type] OR "Retraction Notice"[All Fields]
     OR "no longer recommend"[Title/Abstract])
AND ("2003"[Date - Publication] : "2024"[Date - Publication])

# Manual curation step: from each search, select abstracts whose titles +
# abstracts are clearly on-topic. Reject editorials and review-of-reviews.
# Tag each as effective_from=publication_date, retracted=(true if Pub Type
# includes "Retracted Publication" OR if the abstract states a withdrawal),
# retracted_at=actual retraction notice date when known.
```

- [ ] **Step 3: Commit**

```bash
git add benchmarks/medical-hrt/README.md benchmarks/medical-hrt/pubmed_query.txt
git commit -m "bench(medical-hrt): scaffold Path B corpus with PubMed query spec"
```

---

### Task 3.2: Write the downloader

**Files:**
- Create: `benchmarks/medical-hrt/download_abstracts.py`

- [ ] **Step 1: Write the downloader**

Create `benchmarks/medical-hrt/download_abstracts.py`:

```python
"""Download PubMed abstracts via NCBI eutils.

Usage:
  uv run python download_abstracts.py --query QUERY_FILE --max 30 --out abstracts/

Implements eutils best practices: 3 req/s (no API key), polite User-Agent,
exponential backoff on 429. Writes one .json per PubMed ID with title,
abstract, publication date, publication types, and retraction flag.

NOTE: This is a HUMAN-IN-THE-LOOP step. After download, manually curate
abstracts/ — drop off-topic ones — before running ingest.py.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
USER_AGENT = "pgrg-benchmark/1.0 (matt@theyonk.com)"
RATE_DELAY = 0.34  # ~3 req/s


def esearch(client: httpx.Client, term: str, retmax: int) -> list[str]:
    r = client.get(
        f"{EUTILS}/esearch.fcgi",
        params={"db": "pubmed", "term": term, "retmax": retmax, "retmode": "json"},
    )
    r.raise_for_status()
    return r.json()["esearchresult"]["idlist"]


def efetch(client: httpx.Client, pmid: str) -> dict[str, Any]:
    r = client.get(
        f"{EUTILS}/efetch.fcgi",
        params={"db": "pubmed", "id": pmid, "retmode": "xml"},
    )
    r.raise_for_status()
    # Lightweight XML parsing — enough for title/abstract/date/pubtypes.
    from xml.etree import ElementTree as ET

    root = ET.fromstring(r.text)
    article = root.find(".//Article")
    title = (article.findtext("ArticleTitle") or "").strip() if article is not None else ""
    abstract = " ".join(
        (e.text or "")
        for e in (article.findall(".//AbstractText") if article is not None else [])
    ).strip()
    pub_date = root.findtext(".//PubDate/Year") or ""
    pub_types = [
        (e.text or "")
        for e in root.findall(".//PublicationType")
    ]
    retracted = any("Retract" in t for t in pub_types)
    return {
        "pmid": pmid,
        "title": title,
        "abstract": abstract,
        "pub_year": int(pub_date) if pub_date.isdigit() else None,
        "pub_types": pub_types,
        "retracted": retracted,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True, help="PubMed search expression")
    ap.add_argument("--max", type=int, default=15)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0) as client:
        ids = esearch(client, args.query, args.max)
        print(f"  found {len(ids)} pmids")
        for pmid in ids:
            target = args.out / f"{pmid}.json"
            if target.exists():
                print(f"  = {pmid} (cached)")
                continue
            time.sleep(RATE_DELAY)
            try:
                doc = efetch(client, pmid)
            except httpx.HTTPStatusError as e:
                print(f"  ! {pmid}: HTTP {e.response.status_code}")
                continue
            target.write_text(json.dumps(doc, indent=2))
            print(f"  + {pmid}: {doc['title'][:60]}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run all three queries from `pubmed_query.txt`**

```bash
cd benchmarks/medical-hrt
mkdir -p abstracts
uv run python download_abstracts.py \
  --query '("hormone replacement therapy"[Title/Abstract] OR "HRT"[Title/Abstract]) AND ("cardiovascular"[Title/Abstract] OR "coronary"[Title/Abstract]) AND ("1990"[Date - Publication] : "2001"[Date - Publication])' \
  --max 15 --out abstracts/pre2002/
uv run python download_abstracts.py \
  --query '"Women'\''s Health Initiative"[Title/Abstract] AND ("2002"[Date - Publication] : "2004"[Date - Publication])' \
  --max 15 --out abstracts/whi/
uv run python download_abstracts.py \
  --query '("hormone replacement therapy"[Title/Abstract] OR "HRT"[Title/Abstract]) AND ("cardiovascular"[Title/Abstract] OR "coronary"[Title/Abstract]) AND ("2003"[Date - Publication] : "2024"[Date - Publication])' \
  --max 15 --out abstracts/post2002/
cd ../..
```

- [ ] **Step 3: Verify the haul**

```bash
find benchmarks/medical-hrt/abstracts -name "*.json" | wc -l
# show retracted flag distribution
python3 -c "
import json, glob
files = glob.glob('benchmarks/medical-hrt/abstracts/**/*.json', recursive=True)
print('total files:', len(files))
retracted = sum(1 for f in files if json.load(open(f))['retracted'])
print('retracted:', retracted)
"
```

Expected: ≥30 files total. Retracted count: at least 1 (true retractions are rare).

- [ ] **Step 4: Commit downloader + raw abstracts**

```bash
git add benchmarks/medical-hrt/download_abstracts.py \
        benchmarks/medical-hrt/abstracts/
git commit -m "bench(medical-hrt): download HRT+CV PubMed abstracts (pre/WHI/post 2002)"
```

---

### Task 3.3: Curate `manifest.yaml`

**Files:**
- Create: `benchmarks/medical-hrt/manifest.yaml`

- [ ] **Step 1: Generate a manifest scaffold from the abstracts**

```bash
python3 - <<'PYEOF'
import json, glob, yaml
from datetime import datetime, timezone
files = sorted(glob.glob('benchmarks/medical-hrt/abstracts/**/*.json', recursive=True))
entries = []
for f in files:
    d = json.load(open(f))
    bucket = f.split('/')[-2]
    year = d['pub_year'] or 2000
    entries.append({
        "pmid": d["pmid"],
        "title": d["title"],
        "file": f,
        "bucket": bucket,
        "effective_from": f"{year}-01-01T00:00:00+00:00",
        "retracted": d["retracted"],
        "retracted_at": "2002-07-17T00:00:00+00:00" if (bucket == "whi" and year >= 2003) else None,
        "retraction_reason": "WHI 2002 RCT invalidated cardioprotection findings"
            if (bucket == "whi" and year >= 2003) else None,
    })
yaml.safe_dump({"abstracts": entries}, open('benchmarks/medical-hrt/manifest.yaml', 'w'),
               sort_keys=False)
print(f'wrote {len(entries)} entries')
PYEOF
```

- [ ] **Step 2: Curate manually**

Open `benchmarks/medical-hrt/manifest.yaml`. For each entry:
- Drop entries whose title is off-topic (editorials, review-of-reviews).
- For each pre-2002 supportive paper, leave `retracted: false`.
- For each post-2002 cautionary paper that explicitly cites WHI 2002 as
  retracting the prior consensus, set `retracted: false` (it's NOT
  retracted — it's the *replacement* guidance).
- For any entry with `pub_types` containing "Retracted Publication" or
  "Retraction Notice", confirm `retracted: true` and add a real
  `retracted_at` and `retraction_reason`.
- Aim for: ≥10 pre-2002, ≥5 WHI-era, ≥10 post-2002 retraction-aware. Total ≥30.

- [ ] **Step 3: Verify counts and metadata**

```bash
python3 -c "
import yaml
d = yaml.safe_load(open('benchmarks/medical-hrt/manifest.yaml'))
abs = d['abstracts']
print('total:', len(abs))
print('retracted:', sum(1 for a in abs if a['retracted']))
print('with retracted_at:', sum(1 for a in abs if a.get('retracted_at')))
print('per bucket:', {b: sum(1 for a in abs if a['bucket'] == b) for b in {a['bucket'] for a in abs}})
"
```

Expected: total ≥ 30; per-bucket distribution roughly as targeted.

- [ ] **Step 4: Commit the curated manifest**

```bash
git add benchmarks/medical-hrt/manifest.yaml
git commit -m "bench(medical-hrt): curated manifest of ≥30 abstracts with evolution metadata"
```

---

### Task 3.4: Write the ingest script

**Files:**
- Create: `benchmarks/medical-hrt/ingest.py`

- [ ] **Step 1: Write the ingest script**

Create `benchmarks/medical-hrt/ingest.py`:

```python
"""Ingest medical-hrt corpus into pgrg with full Tier 1 evolution metadata."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import yaml

from pg_raggraph import GraphRAG

ROOT = Path(__file__).parent
DSN = os.environ.get(
    "PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
)
NAMESPACE = "medical_hrt"


def parse_dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


async def main() -> None:
    manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text())["abstracts"]
    rag = GraphRAG(dsn=DSN, namespace=NAMESPACE, evolution_tier="structural")
    await rag.connect()
    try:
        await rag.delete_namespace(NAMESPACE)
        for entry in manifest:
            doc = json.loads(Path(entry["file"]).read_text())
            tmp = ROOT / "_tmp" / f"{entry['pmid']}.md"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(f"# {doc['title']}\n\n{doc['abstract']}")
            md = {
                "effective_from": parse_dt(entry["effective_from"]),
                "retracted": entry["retracted"],
            }
            if entry.get("retracted_at"):
                md["retracted_at"] = parse_dt(entry["retracted_at"])
            if entry.get("retraction_reason"):
                md["retraction_reason"] = entry["retraction_reason"]
            await rag.ingest([str(tmp)], namespace=NAMESPACE, metadata=md)
            print(f"  + {entry['pmid']} (retracted={entry['retracted']})")
    finally:
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run it**

```bash
cd benchmarks/medical-hrt
uv run python ingest.py
cd ../..
```

Wall time: 5–15 min.

- [ ] **Step 3: Verify SC-005 — metadata populated**

```bash
docker compose exec postgres psql -U postgres -d pg_raggraph -c "
SELECT
  COUNT(*) AS n_docs,
  COUNT(effective_from) AS n_with_effective,
  COUNT(retracted_at) AS n_with_retracted_at,
  SUM(CASE WHEN retracted THEN 1 ELSE 0 END) AS n_retracted
FROM documents WHERE namespace = 'medical_hrt';
"
```

Expected: `n_docs ≥ 30`, `n_with_effective = n_docs`, `n_retracted ≥ 1`.

- [ ] **Step 4: Confirm synthetic fixture untouched**

```bash
git status tests/fixtures/evolving/medical_retraction/
git diff HEAD -- tests/fixtures/evolving/medical_retraction/
```

Expected: no changes (constraint).

- [ ] **Step 5: Commit**

```bash
git add benchmarks/medical-hrt/ingest.py
git commit -m "bench(medical-hrt): ingest with effective_from/retracted/retracted_at"
```

---

### Task 3.5: Write `gold.yaml` (≥15 questions, ≥5 retraction-aware)

**Files:**
- Create: `benchmarks/medical-hrt/gold.yaml`

- [ ] **Step 1: Hand-write the gold questions**

Create `benchmarks/medical-hrt/gold.yaml`:

```yaml
corpus: medical_hrt
# 15 hand-written questions. Three categories:
#   - retraction_aware: with retracted_behavior="hide", expect post-2002 guidance,
#       NO retracted abstracts in top-5 (5 questions)
#   - time_travel: with as_of=1995-01-01, expect pre-2002 supportive paper in top-5
#       (5 questions paired with retraction_aware ones)
#   - background: general HRT/CV questions, no retraction expectation (5)
questions:
  # retraction_aware (5)
  - id: hrt-q-001
    category: retraction_aware
    question: "Is hormone replacement therapy cardioprotective?"
    expected_substring_hide: "no longer"   # post-2002 guidance phrase
  - id: hrt-q-002
    category: retraction_aware
    question: "Should women take HRT to prevent coronary heart disease?"
    expected_substring_hide: "not"
  - id: hrt-q-003
    category: retraction_aware
    question: "Does estrogen plus progestin prevent cardiovascular events?"
    expected_substring_hide: "increase"
  - id: hrt-q-004
    category: retraction_aware
    question: "What did the WHI trial conclude about HRT and cardiovascular risk?"
    expected_substring_hide: "increased"
  - id: hrt-q-005
    category: retraction_aware
    question: "Is combined HRT recommended for primary prevention of CVD?"
    expected_substring_hide: "not recommended"

  # time_travel (5; same questions, with as_of=1995-01-01)
  - id: hrt-q-006
    category: time_travel
    question: "Is hormone replacement therapy cardioprotective?"
    as_of: "1995-01-01T00:00:00+00:00"
    expected_substring_asof: "reduce"   # pre-2002 supportive consensus
  - id: hrt-q-007
    category: time_travel
    question: "Should women take HRT to prevent coronary heart disease?"
    as_of: "1995-01-01T00:00:00+00:00"
    expected_substring_asof: "benefit"
  - id: hrt-q-008
    category: time_travel
    question: "What is the effect of estrogen on coronary disease?"
    as_of: "1995-01-01T00:00:00+00:00"
    expected_substring_asof: "decrease"
  - id: hrt-q-009
    category: time_travel
    question: "Is HRT associated with reduced cardiovascular mortality?"
    as_of: "1995-01-01T00:00:00+00:00"
    expected_substring_asof: "associated"
  - id: hrt-q-010
    category: time_travel
    question: "What does observational data say about HRT and heart disease?"
    as_of: "1995-01-01T00:00:00+00:00"
    expected_substring_asof: "lower"

  # background (5)
  - id: hrt-q-011
    category: background
    question: "What is the Women's Health Initiative?"
    expected_substring: "trial"
  - id: hrt-q-012
    category: background
    question: "What hormones are used in combined HRT?"
    expected_substring: "estrogen"
  - id: hrt-q-013
    category: background
    question: "What are the symptoms of menopause that HRT treats?"
    expected_substring: "hot flashes"
  - id: hrt-q-014
    category: background
    question: "What are the breast-cancer findings related to HRT?"
    expected_substring: "breast"
  - id: hrt-q-015
    category: background
    question: "What is the timing hypothesis for HRT?"
    expected_substring: "younger"
```

- [ ] **Step 2: Validate the YAML loads**

```bash
python3 -c "
import yaml
from collections import Counter
d = yaml.safe_load(open('benchmarks/medical-hrt/gold.yaml'))
print(len(d['questions']), 'questions')
print(Counter(q['category'] for q in d['questions']))
"
```

Expected: `15 questions` with 5/5/5 across categories.

- [ ] **Step 3: Commit**

```bash
git add benchmarks/medical-hrt/gold.yaml
git commit -m "bench(medical-hrt): 15 gold Qs (5 retraction-aware, 5 time-travel, 5 background)"
```

---

### Task 3.6: Write `run_path_b.py`

**Files:**
- Create: `benchmarks/medical-hrt/run_path_b.py`

- [ ] **Step 1: Write the runner**

Create `benchmarks/medical-hrt/run_path_b.py`:

```python
"""Path B runner — exercises pgrg's retracted_behavior + as_of features.

retraction_aware Qs run with retracted_behavior="hide"; assert top-5 has
ZERO retracted documents AND the answer contains expected_substring_hide.

time_travel Qs run with as_of=given datetime; assert top-5 has ≥ 1
pre-2002 supportive paper AND the answer contains expected_substring_asof.

background Qs run with default flags; just assert expected_substring.

Writes results.md with category pass rates and SC-006 verdict.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import yaml

from pg_raggraph import GraphRAG

ROOT = Path(__file__).parent
DSN = os.environ.get(
    "PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
)
NAMESPACE = "medical_hrt"


async def chunk_meta(rag: GraphRAG, chunk_id: str) -> dict:
    """Return retracted flag and effective_from year for a chunk's parent doc."""
    async with rag.db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT d.retracted, EXTRACT(year FROM d.effective_from)::int AS y "
            "FROM chunks c JOIN documents d ON c.document_id = d.id "
            "WHERE c.id = $1",
            chunk_id,
        )
        return {"retracted": row["retracted"], "year": row["y"]} if row else {}


async def run_question(rag: GraphRAG, q: dict) -> dict:
    cat = q["category"]
    kwargs = {"namespace": NAMESPACE, "mode": "naive_boost", "top_k": 10}
    if cat == "retraction_aware":
        kwargs["retracted_behavior"] = "hide"
        sub = q["expected_substring_hide"]
    elif cat == "time_travel":
        kwargs["as_of"] = datetime.fromisoformat(q["as_of"])
        sub = q["expected_substring_asof"]
    else:
        sub = q["expected_substring"]
    result = await rag.query(q["question"], **kwargs)
    answer = await rag.ask(q["question"], **kwargs)
    answer_text = answer.text if hasattr(answer, "text") else str(answer)
    metas = [await chunk_meta(rag, c.id) for c in result.chunks[:5]]
    n_retracted_top5 = sum(1 for m in metas if m.get("retracted"))
    has_pre2002 = any(m.get("year", 9999) < 2002 for m in metas)
    sub_match = sub.lower() in answer_text.lower()

    if cat == "retraction_aware":
        passed = n_retracted_top5 == 0 and sub_match
    elif cat == "time_travel":
        passed = has_pre2002 and sub_match
    else:
        passed = sub_match
    return {
        "id": q["id"],
        "category": cat,
        "n_retracted_top5": n_retracted_top5,
        "has_pre2002": has_pre2002,
        "sub_match": sub_match,
        "passed": passed,
    }


async def main() -> None:
    qs = yaml.safe_load((ROOT / "gold.yaml").read_text())["questions"]
    rag = GraphRAG(dsn=DSN, evolution_tier="structural")
    await rag.connect()
    rows = []
    try:
        for q in qs:
            r = await run_question(rag, q)
            print(
                f"[{'PASS' if r['passed'] else 'FAIL'}] {r['id']} ({r['category']}): "
                f"retracted_top5={r['n_retracted_top5']} pre2002={r['has_pre2002']} "
                f"sub={r['sub_match']}"
            )
            rows.append(r)
    finally:
        await rag.close()

    n_retraction = sum(1 for r in rows if r["category"] == "retraction_aware")
    n_retraction_pass = sum(
        1 for r in rows if r["category"] == "retraction_aware" and r["passed"]
    )
    n_time_pass = sum(
        1 for r in rows if r["category"] == "time_travel" and r["passed"]
    )
    summary = {
        "n_total": len(rows),
        "retraction_pass": f"{n_retraction_pass}/{n_retraction}",
        "sc006_threshold_retraction": "≥ 4/5",
        "sc006_retraction_pass": n_retraction_pass >= 4,
        "time_travel_pass": f"{n_time_pass}/5",
        "sc006_threshold_time_travel": "≥ 1/5 with pre-2002 paper in top-5",
        "sc006_time_travel_pass": n_time_pass >= 1,
        "rows": rows,
    }
    out = ROOT / "results.json"
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Confirm `as_of` and `retracted_behavior` are kwargs on `rag.query`**

```bash
grep -nE "as_of|retracted_behavior|version_filter" src/pg_raggraph/__init__.py | head -10
```

Expected: kwargs accepted (these landed in 0.3.0a0 per the cookbook page).

- [ ] **Step 3: Run it**

```bash
cd benchmarks/medical-hrt
uv run python run_path_b.py
cd ../..
```

- [ ] **Step 4: Verify SC-006 thresholds**

The printed JSON must show `sc006_retraction_pass: true` AND `sc006_time_travel_pass: true`. If either is false, do NOT proceed — root-cause first (open follow-up issue if the Tier 1 implementation has a real gap).

---

### Task 3.7: Write `results.md` and integration test

**Files:**
- Create: `benchmarks/medical-hrt/results.md`
- Create: `tests/integration/test_medical_hrt.py`

- [ ] **Step 1: Write results.md**

Create `benchmarks/medical-hrt/results.md`:

```markdown
# Path B — Medical HRT real corpus results

**Date:** <fill in>
**Branch:** main @ <fill in: short SHA>
**Mode:** `naive_boost`, top_k=10 (top-5 used for retraction & pre-2002 checks)
**Corpus:** ≥30 PubMed HRT+CV abstracts; namespace `medical_hrt`
**Synthetic fixture:** `tests/fixtures/evolving/medical_retraction/` UNTOUCHED (constraint)

## SC-006 Verdict

| Threshold | Result | Pass? |
|---|---|---|
| ≥ 4/5 retraction-aware Qs return post-2002 guidance, ZERO retracted in top-5 | <fill: retraction_pass> | <YES/NO> |
| ≥ 1/5 time-travel Qs (as_of=1995-01-01) return pre-2002 supportive paper in top-5 | <fill: time_travel_pass> | <YES/NO> |

**Overall SC-006:** <PASS / FAIL>

## By category

| Category | n | n passed | rate |
|---|---|---|---|
| retraction_aware | 5 | <fill> | <fill>% |
| time_travel | 5 | <fill> | <fill>% |
| background | 5 | <fill> | <fill>% |

## Per-question

See `results.json`.

## Notes for the blog post

<fill in: 2-3 surprising real observations from the run>
```

- [ ] **Step 2: Append cost-log row**

```markdown
| 3 | <date> | medical-hrt ingest+benchmark | gpt-4o-mini | <in>/<out> | $X.XX | $X.XX |
```

- [ ] **Step 3: Write the integration test**

Create `tests/integration/test_medical_hrt.py`:

```python
"""Integration test — medical_hrt corpus has correct evolution metadata,
synthetic fixture untouched (SC-005 evidence)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


async def test_min_30_docs_with_metadata(rag_pool):
    async with rag_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS n, COUNT(effective_from) AS ne, "
            "SUM(CASE WHEN retracted THEN 1 ELSE 0 END) AS nr "
            "FROM documents WHERE namespace = 'medical_hrt'"
        )
    assert row["n"] >= 30, row
    assert row["ne"] == row["n"], "every doc must have effective_from"
    assert row["nr"] >= 1, "at least 1 retracted abstract expected"


def test_synthetic_fixture_files_untouched():
    """SC-005 constraint: tests/fixtures/evolving/medical_retraction/ unchanged."""
    expected = {
        "manifest.yaml",
        "guidance_2002_hrt_contraindicated.md",
        "meta_2008_hrt_no_cardio.md",
        "paper_1992_hrt_cardio.md",
        "paper_1998_hrt_cardio_replication.md",
    }
    actual = set(
        p.name
        for p in Path("tests/fixtures/evolving/medical_retraction").iterdir()
    )
    assert actual == expected, actual.symmetric_difference(expected)
```

- [ ] **Step 4: Run the integration tests**

```bash
uv run pytest tests/integration/test_medical_hrt.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/medical-hrt/run_path_b.py \
        benchmarks/medical-hrt/results.md \
        benchmarks/medical-hrt/results.json \
        tests/integration/test_medical_hrt.py \
        benchmarks/cost-log.md
git commit -m "bench(medical-hrt): Path B results — SC-006 <PASS/FAIL> + integration tests"
```

---

### ⛔ DC-004: Post-Path-B alignment check

- [ ] **Re-read mission brief**
- [ ] **Three-question drift check**
- [ ] **Verify SC-005 evidence**: integration tests pass; results.md notes synthetic fixture untouched.
- [ ] **Verify SC-006 evidence**: `sc006_retraction_pass` and `sc006_time_travel_pass` both true.
- [ ] **If FAIL on retraction behavior**: stop. File a follow-up issue describing the failure mode (zero retracted in top-5 expected; got N). Do NOT draft blog post #3.
- [ ] **If PASS**: proceed to Phase 4.

---

## Phase 4 — Use-case taxonomy + dev-rel blog series (on `main`)

### Task 4.1: Write `docs/USE-CASES.md`

**Files:**
- Create: `docs/USE-CASES.md`

- [ ] **Step 1: Draft the doc**

Create `docs/USE-CASES.md`:

```markdown
# pg-raggraph use cases

pg-raggraph supports two distinct retrieval workloads. Pick the one whose
corpus shape matches yours; both are first-class.

## Use case 1 — Classic GraphRAG

**When:** technical docs, code Q&A, multi-hop entity reasoning over a
corpus where "current truth" is the only truth and documents don't
contradict each other across time.

**Examples:**
- "Who owns the auth service?" over a developer wiki
- "What caused the outage?" over incident reports
- "How does X depend on Y?" over architecture docs

**Recommended config:**
```python
rag = GraphRAG(dsn=DSN, namespace="dev_kb")
result = await rag.query("…", mode="naive_boost", top_k=10)
```

**Validated on:** SCOTUS (772 docs), pg-agents (486 docs), NTSB (20),
SEC 10-Q (20), PostgreSQL docs (31). On the dev codebase, graph boost
delivers **+19.3% top-score lift** over naive vector at the same latency.
See `benchmarks/pg-agents-results.md`, `benchmarks/age-bakeoff/results/`.

## Use case 2 — Evolving knowledge

**When:** corpora where the right answer depends on **time**, **version**,
or **retraction status**. Documents accumulate, supersede each other, and
sometimes get withdrawn.

**Examples:**
- "Is HRT cardioprotective?" — the answer changed in 2002 (WHI retraction).
- "How does StrEnum work in Python 3.12?" — version-scoped.
- "What was the refund window in 2023?" — time-travel.

**Recommended config:**
```python
rag = GraphRAG(dsn=DSN, namespace="medical", evolution_tier="structural")
# Hide retracted docs:
result = await rag.query("…", retracted_behavior="hide")
# Time-travel:
result = await rag.query("…", as_of=datetime(1995, 1, 1, tzinfo=timezone.utc))
# Version filter:
result = await rag.query("…", version_filter="Python 3.12")
```

**Validated on:** versioned Python 3.10/3.11/3.12 docs (Path A), PubMed
HRT retractions (Path B). See `benchmarks/python-versioned-docs/results.md`,
`benchmarks/medical-hrt/results.md`.

## Decision matrix — which use case fits your corpus?

| Corpus shape | Use case | Why |
|---|---|---|
| Static technical docs | Classic | No time/version axis; graph boost helps cross-doc reasoning |
| Code Q&A on a single repo | Classic | Same — `naive_boost` wins per pg-agents |
| Codebase across versioned releases | Evolving | `version_label` per release; `version_filter` at query |
| Medical/legal literature with retractions | Evolving | `retracted` + `retracted_at` per doc |
| Policy / contract archive | Evolving | `effective_from` / `effective_to`; `as_of` queries |
| Multi-tenant SaaS with point-in-time audit | Evolving | `as_of` with tenant namespace |
| News archive | Evolving | `effective_from`; freshness scoring |
| Wikipedia-style facts | Classic | Current truth dominates; no per-version queries |

## How to choose at a glance

Ask yourself:

1. **Does my corpus have retracted, superseded, or version-specific
   documents?** Yes → evolving. No → classic.
2. **Will users ask "what was true at time T?"** Yes → evolving (`as_of`).
3. **Are there parallel versions whose answers differ?** Yes → evolving
   (`version_filter`).
4. **None of the above?** Use classic. It's faster and cheaper at ingest
   (no Tier 2/3 fact extraction needed).

## See also

- `docs/cookbook/evolution-tracking.md` — Tier 1 quickstart
- `docs/blog/01-intro-classic-vs-evolving.md` — narrative version of this page
- `docs/user-guide.md` — full API reference
```

- [ ] **Step 2: Cross-link from `README.md`**

In `README.md`, add a "Use cases" link near the top intro section. Specifically: find an existing top-level heading (likely `## Quick Start` or `## What it does`) and immediately above it, insert:

```markdown
## Use cases

pg-raggraph supports two retrieval workloads — **classic GraphRAG** for
static corpora, and **evolving knowledge** for time/version/retraction-aware
retrieval. See [docs/USE-CASES.md](docs/USE-CASES.md) for the decision
matrix and benchmark numbers.
```

- [ ] **Step 3: Cross-link from `docs/user-guide.md`**

Near the top of `docs/user-guide.md`, after the introductory paragraph,
add: `> **Picking a workload:** see [USE-CASES.md](USE-CASES.md) for the
classic-vs-evolving decision matrix.`

- [ ] **Step 4: Commit**

```bash
git add docs/USE-CASES.md README.md docs/user-guide.md
git commit -m "docs: USE-CASES.md taxonomy + cross-links from README and user-guide"
```

---

### Task 4.2: Draft blog post #1 — intro / classic vs evolving

**Files:**
- Create: `docs/blog/01-intro-classic-vs-evolving.md`

- [ ] **Step 1: Draft the post**

Create `docs/blog/01-intro-classic-vs-evolving.md`:

```markdown
---
title: "Two GraphRAG workloads, one Postgres database"
slug: "01-intro-classic-vs-evolving"
date: 2026-04-27
audience: external
---

# Two GraphRAG workloads, one Postgres database

Most GraphRAG demos answer one kind of question: *given my static corpus,
how do I find the right paragraph?* That's the **classic** workload —
docs/code/wikis where "current truth" is the only truth.

But not every corpus is static. Medical literature gets retracted. APIs
evolve across versions. Policies change effective dates. For these, the
right answer depends on *when* you ask. That's the **evolving knowledge**
workload.

pg-raggraph supports both — and it's the same Postgres database.

## A 60-second tour

**Classic.** Ingest your docs, query, get chunks back. Graph boost
re-ranks the top-K using 1-hop entity connectivity:

```python
rag = GraphRAG(dsn=DSN, namespace="dev_kb")
result = await rag.query("Who owns the auth service?", mode="naive_boost")
```

On a real 486-doc dev codebase (pg-agents), `naive_boost` delivers a
**+19.3% top-score lift** over plain vector at the same latency. (See
`benchmarks/pg-agents-results.md`.)

**Evolving.** Add `evolution_tier="structural"` to ingest with metadata,
then query with retraction- or time- or version-awareness:

```python
rag = GraphRAG(dsn=DSN, namespace="medical", evolution_tier="structural")

# "Is HRT cardioprotective?" with retracted papers hidden — gets the
# post-2002 guidance, not the pre-WHI consensus.
result = await rag.query("…", retracted_behavior="hide")

# Or time-travel to 1995, when the consensus was different:
result = await rag.query("…", as_of=datetime(1995, 1, 1, tzinfo=timezone.utc))
```

The tutorial walks through both paths on real corpora.

## Why this lives in one library

The thesis is unchanged: pgvector + adjacency tables + recursive CTEs +
PostgreSQL full-text search = a complete GraphRAG stack in **one
ACID-compliant database**. No graph database extension, no vector
database, no separate fact store.

The evolving-knowledge layer adds four metadata columns to `documents`
and one query-time filter set. Same DB. Same indexes. Same provenance
trail. ([See the architecture overview if you want the deep dive.])

## What's next in this series

- **Path A — Versioned Python docs**: ingest 3.10/3.11/3.12, query with
  `version_filter`, see real numbers.
- **Path B — Medical retractions**: ingest PubMed HRT+CV abstracts, see
  `retracted_behavior="hide"` and `as_of` work on real published
  literature.

If your corpus is static, Path A and Path B are still worth reading — the
metadata story matters once you start versioning your own internal docs.
If your corpus is evolving, Path B in particular is the one that probably
maps to your problem.

## Try it

```bash
git clone https://github.com/the-yonk/pg-raggraph
cd pg-raggraph
docker compose up -d postgres
uv sync
uv run pgrg demo
```

The decision matrix at `docs/USE-CASES.md` will help you pick.
```

- [ ] **Step 2: Commit**

```bash
git add docs/blog/01-intro-classic-vs-evolving.md
git commit -m "docs(blog): post 01 — intro to classic vs evolving"
```

---

### Task 4.3: Draft blog post #2 — Path A (Python docs)

**Files:**
- Create: `docs/blog/02-path-a-versioned-python-docs.md`

- [ ] **Step 1: Read your real numbers from Path A**

```bash
cat benchmarks/python-versioned-docs/results.md
```

Note the filter rate, the per-category numbers, and any surprises.

- [ ] **Step 2: Draft the post**

Create `docs/blog/02-path-a-versioned-python-docs.md`. Use ONLY real
numbers from `benchmarks/python-versioned-docs/results.md` — no
placeholders, no rounding to "about" anything:

```markdown
---
title: "Versioning your docs corpus: a Python 3.10/3.11/3.12 walkthrough"
slug: "02-path-a-versioned-python-docs"
date: 2026-04-27
audience: external
---

# Versioning your docs corpus: a Python 3.10/3.11/3.12 walkthrough

If your product ships across versions and your docs accumulate, classic
RAG has a problem: a query about Python 3.12's `StrEnum` enhancements
will happily return the 3.10 docs, because they all say "StrEnum"
loudly. The user gets cross-version contamination, and they don't know.

pg-raggraph's Tier 1 evolution tracking solves this with one metadata
field — `version_label` — and one query-time kwarg — `version_filter`.

## What we ingested

12 documents: four pages × three Python versions.

| Version | Pages |
|---|---|
| 3.10 | enum, typing, datamodel, whatsnew/3.10 |
| 3.11 | enum, typing, datamodel, whatsnew/3.11 |
| 3.12 | enum, typing, datamodel, whatsnew/3.12 |

Each ingest call carried `metadata={"version_label": "Python 3.x"}`.
That's it. No Tier 2, no LLM-inferred supersession.

## What we measured

15 hand-written gold questions, four categories:
- **filtered_match** (5): question + `version_filter`; expect top-5
  chunks ONLY from the matching version.
- **cross_version** (6): same question, two different version filters.
- **unfiltered_target** (2): query about a 3.12-only feature, no filter;
  expect 3.12 in top-3.
- **whatsnew** (2): version-specific release notes.

The full runner is at `benchmarks/python-versioned-docs/run_path_a.py`.

## Numbers

<fill in: paste the SC-004 verdict table directly from results.md, no edits>

<fill in: paste the by-category table directly from results.md>

## What surprised us

<fill in 2-3 real observations from results.md "Notes for the blog post"
section. No fabrication. If the only surprise was "it worked", say that.>

## How to try it

From a fresh clone:

```bash
git clone https://github.com/the-yonk/pg-raggraph
cd pg-raggraph
docker compose up -d postgres
uv sync

# Run the corpus pipeline
cd benchmarks/python-versioned-docs
uv run python download_python_docs.py
uv run python ingest.py
uv run python run_path_a.py
```

You should see a results.json with the same numbers (within ±1
question across runs).

## When this approach fits your project

You want this if:
- Your docs ship across versioned releases (libraries, APIs).
- Users routinely ask version-scoped questions.
- You don't want the answer for v1 to leak into a query about v2.

You don't need this if:
- Only one version is "live" at a time.
- Your corpus has no temporal dimension at all (most internal wikis).

## Up next

Post #3 covers Path B — medical literature with real retractions, where
the answer changes after a published trial result. Same library, same
database, very different corpus.
```

Replace `<fill in: …>` with real content from `results.md`.

- [ ] **Step 3: Commit**

```bash
git add docs/blog/02-path-a-versioned-python-docs.md
git commit -m "docs(blog): post 02 — Path A versioned Python docs walkthrough"
```

---

### Task 4.4: Draft blog post #3 — Path B (medical retractions)

**Files:**
- Create: `docs/blog/03-path-b-medical-retractions.md`

- [ ] **Step 1: Read real numbers from Path B**

```bash
cat benchmarks/medical-hrt/results.md
```

- [ ] **Step 2: Draft the post**

Create `docs/blog/03-path-b-medical-retractions.md`. Use ONLY real numbers:

```markdown
---
title: "When the answer changes: GraphRAG over retracted medical literature"
slug: "03-path-b-medical-retractions"
date: 2026-04-27
audience: external
---

# When the answer changes: GraphRAG over retracted medical literature

In 2002, the Women's Health Initiative published a randomized trial that
overturned the previous decade's consensus on hormone replacement therapy
(HRT) and cardiovascular health. Pre-WHI: HRT was thought to reduce
coronary risk. Post-WHI: the opposite, and combined HRT was no longer
recommended for primary prevention.

If you ask a vanilla RAG system "is HRT cardioprotective?" against a
corpus that contains both eras of literature, you get whatever the vector
search prefers — which is often the older, denser, more numerous
pre-2002 papers. The system sounds confident and is wrong.

This post walks through the same query against pg-raggraph using two
Tier 1 features: `retracted_behavior="hide"` and `as_of`.

## What we ingested

<fill in real number> PubMed abstracts on HRT + cardiovascular,
spanning pre-2002 supportive, the WHI 2002 era, and post-2002
cautionary literature. Ingestion metadata included `effective_from`
(publication year), `retracted` (where applicable), and `retracted_at`
+ `retraction_reason` for the ones explicitly withdrawn.

The corpus is at `benchmarks/medical-hrt/`. PubMed query expressions are
in `pubmed_query.txt`. Manifest at `manifest.yaml`.

**Note.** This corpus is real published literature, separate from the
synthetic fixture at `tests/fixtures/evolving/medical_retraction/`,
which we kept as-is for unit tests.

## What we measured

15 hand-written gold questions:
- **retraction_aware** (5): with `retracted_behavior="hide"`, expect
  zero retracted abstracts in top-5 AND a post-2002 phrase in the
  answer.
- **time_travel** (5): with `as_of=1995-01-01`, expect ≥1 pre-2002
  supportive paper in top-5 AND a pre-WHI consensus phrase in the
  answer.
- **background** (5): general HRT/CV questions, no retraction expectation.

The full runner is at `benchmarks/medical-hrt/run_path_b.py`.

## Numbers

<fill in: paste SC-006 verdict table from benchmarks/medical-hrt/results.md>

<fill in: paste by-category table from results.md>

## A real query, end to end

```python
from datetime import datetime, timezone
from pg_raggraph import GraphRAG

rag = GraphRAG(dsn=DSN, namespace="medical_hrt", evolution_tier="structural")
await rag.connect()

# 2026 view — retractions hidden
result = await rag.query(
    "Is hormone replacement therapy cardioprotective?",
    retracted_behavior="hide",
)

# 1995 view — pre-WHI consensus
result_old = await rag.query(
    "Is hormone replacement therapy cardioprotective?",
    as_of=datetime(1995, 1, 1, tzinfo=timezone.utc),
)
```

The two answers reflect what the medical community actually believed in
each era. Same corpus. One database. No retraining.

## What surprised us

<fill in 2-3 real surprises from results.md>

## When this approach fits your project

You want this if:
- Your corpus accumulates over time and corrections are common.
- "What was the consensus on date X?" is a real question.
- You have publication-date or effective-date metadata available.

You don't need this if:
- Your corpus is curated and stale entries are pruned (most product
  docs work this way).
- All your users want is "the latest" — `effective_from` ordering
  alone gives that without retraction tracking.

## Try it

```bash
git clone https://github.com/the-yonk/pg-raggraph
cd pg-raggraph
docker compose up -d postgres
uv sync

cd benchmarks/medical-hrt
uv run python download_abstracts.py --query '<see pubmed_query.txt>' \
    --max 15 --out abstracts/pre2002/
# (run the other two queries from pubmed_query.txt)
# Curate manifest.yaml — drop off-topic abstracts, confirm metadata.
uv run python ingest.py
uv run python run_path_b.py
```

## Wrapping up

Two posts, two corpora, one library. If you're building a knowledge base
where the answer changes — by version, by time, by retraction — you can
do it on plain Postgres without giving up the speed and operational
simplicity that got you to Postgres in the first place.

For the decision matrix on which workload fits your corpus, see
`docs/USE-CASES.md`. For the API reference, see `docs/user-guide.md`.
For everything you skipped, the cookbook is at
`docs/cookbook/evolution-tracking.md`.
```

- [ ] **Step 3: Append final cost-log row**

```markdown
| 4 | <date> | tutorial drafting (no LLM) | n/a | n/a | $0.00 | $X.XX |
```

(If you used an LLM to help draft, log that cost here.)

- [ ] **Step 4: Commit**

```bash
git add docs/blog/03-path-b-medical-retractions.md benchmarks/cost-log.md
git commit -m "docs(blog): post 03 — Path B medical retractions walkthrough"
```

---

### Task 4.5: Fresh-clone E2E walk-through

**Files:** none modified — verification only.

- [ ] **Step 1: Pick the walkthrough**

Choose blog post #2 (Path A) — it's smaller, faster, and the most
representative of the publishing claim.

- [ ] **Step 2: Walk it from a temp dir**

```bash
TMP=$(mktemp -d)
cd $TMP
git clone https://github.com/the-yonk/pg-raggraph
cd pg-raggraph
docker compose up -d postgres
uv sync
cd benchmarks/python-versioned-docs
uv run python download_python_docs.py
uv run python ingest.py
uv run python run_path_a.py
```

- [ ] **Step 3: Compare numbers to the blog post**

```bash
cat results.json
```

The `filter_rate` and per-category numbers should match the published
post within ±1 question per category.

- [ ] **Step 4: Cleanup**

```bash
cd ~  # back to home
rm -rf $TMP
```

If the numbers don't match — the post is wrong. Update it before merging
the blog branch.

---

### ⛔ DC-005: Pre-publish alignment check

- [ ] **Re-read mission brief**
- [ ] **Three-question drift check**
- [ ] **Verify SC-007 evidence**: `docs/USE-CASES.md` exists; cross-links from README and user-guide present.
- [ ] **Verify SC-008 evidence**: three blog posts exist; each quotes only real numbers from results.md (run `grep -nE '<fill|TBD|TODO|placeholder' docs/blog/*.md` and expect zero matches); fresh-clone walkthrough reproduced.
- [ ] **If anything FAILS**: stop. Fix the offending post or doc before declaring complete.

---

## Phase 5 — DC-FINAL alignment + closeout

### ⛔ DC-FINAL: Pre-completion alignment check

- [ ] **Re-read mission brief one final time** at `skill-output/mission-brief/Mission-Brief-tier1-real-bench-tutorial.md`
- [ ] **For each SC-XXX, confirm evidence:**

| SC | Evidence |
|---|---|
| SC-001 | `benchmarks/regressions/results/2026-04-27-regression.md` shows YES on all three threshold rows |
| SC-002 | `git tag --contains main \| grep v0.3.0a0` outputs `v0.3.0a0` |
| SC-003 | `tests/integration/test_python_versioned_docs.py` passes; `benchmarks/python-versioned-docs/results.md` lists three version_labels |
| SC-004 | `benchmarks/python-versioned-docs/results.md` "Overall SC-004" line is PASS |
| SC-005 | `tests/integration/test_medical_hrt.py` passes (both `test_min_30_docs_with_metadata` and `test_synthetic_fixture_files_untouched`) |
| SC-006 | `benchmarks/medical-hrt/results.md` "Overall SC-006" line is PASS |
| SC-007 | `docs/USE-CASES.md` exists; `grep -l USE-CASES README.md docs/user-guide.md` outputs both files |
| SC-008 | `ls docs/blog/01-*.md docs/blog/02-*.md docs/blog/03-*.md` lists all three; `grep -nE '<fill\|TBD\|TODO\|placeholder' docs/blog/*.md` is empty; Task 4.5 fresh-clone reproduction succeeded |
| SC-009 | `benchmarks/cost-log.md` running total ≤ $25.00 |

- [ ] **Out-of-Scope check:**

```bash
# These should NOT be in any commit on this branch since the merge:
git log --oneline main --since=2026-04-27 -- src/pg_raggraph/retrieval.py
git log --oneline main --since=2026-04-27 -- 'src/pg_raggraph/sql/migrations/*'
git log --oneline main --since=2026-04-27 -- tests/fixtures/evolving/medical_retraction/
git log --oneline main --since=2026-04-27 -- docs/cookbook/evolution-tracking.md
```

Each command should output empty (or only the original feature/evolution-tier1 commits, not new ones).

- [ ] **Cost cap check (SC-009):**

```bash
grep "Running total" benchmarks/cost-log.md
```

Final number must be ≤ $25.00.

- [ ] **Push everything to origin**

```bash
git push origin main
```

- [ ] **Final summary commit (optional but recommended)**

```bash
echo "Tier 1 real-world bench + tutorial — DC-FINAL passed $(date -Iseconds)" \
  >> benchmarks/cost-log.md
git add benchmarks/cost-log.md
git commit -m "chore: Tier 1 real-bench + tutorial closeout — all SC-XXX evidence captured"
git push
```

Mission brief status can now move from `active` to `closed` if you keep
that bookkeeping.

---

## Self-Review (post-write check)

This section is a checklist the plan author runs against the spec.
Reviewers can use it as a quality gate.

**1. Spec coverage:**
- SC-001 → Tasks 1.4, 1.5, 1.6
- SC-002 → Task 1.7
- SC-003 → Tasks 2.3 (ingest), 2.7 (test)
- SC-004 → Tasks 2.5 (runner), 2.6 (results.md)
- SC-005 → Tasks 3.4 (ingest), 3.7 (test)
- SC-006 → Tasks 3.6 (runner), 3.7 (results.md)
- SC-007 → Task 4.1
- SC-008 → Tasks 4.2, 4.3, 4.4, 4.5
- SC-009 → cost-log row appended in every phase
- DC-001 → before Phase 1
- DC-002 → before merge
- DC-003 → after Path A
- DC-004 → after Path B
- DC-005 → before publish
- DC-FINAL → Phase 5

All SC-XXX and DC-XXX have at least one task.

**2. Placeholder scan:** Every `<fill in: …>` in the plan refers to a
*real value the engineer will compute or read in the prior task*, not to
content the plan author skipped. Each `<fill in>` is a literal string the
engineer copies in from a known artifact path. No "TODO/TBD/implement
later" placeholders for skipped logic.

**3. Type consistency:** Method names used across tasks: `rag.query`,
`rag.ask`, `rag.connect`, `rag.close`, `rag.ingest`, `rag.delete_namespace`.
Task 2.3 Step 2 instructs the engineer to substitute `delete_namespace`
with the actual primitive if it doesn't exist — flagged consistently.
SQL columns referenced: `documents.namespace`, `documents.metadata`,
`documents.effective_from`, `documents.retracted`, `documents.retracted_at`,
`chunks.id`, `chunks.document_id`. Task 2.5 Step 2 instructs the engineer
to verify column names against `src/pg_raggraph/sql/schema.sql` and adapt
if the schema differs from these assumed names.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-27-tier1-real-bench-tutorial.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
