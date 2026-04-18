# Bake-off Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the quality ceiling, feature coverage, and documentation gaps left by the initial AGE vs pg-raggraph bake-off, as specified in `skill-output/mission-brief/Mission-Brief-bakeoff-followup.md` (the follow-up brief). The original brief at `skill-output/mission-brief/Mission-Brief-age-bakeoff.md` remains active — its SC-XXX and constraints must not be violated.

**Architecture:** Most additions are new CLI knobs, new diagnostic commands, and richer report wiring on top of the existing `benchmarks/age-bakeoff/` package. `PgrgEngine` already accepts a `retrieval_mode` parameter — plumbing it through is a CLI change, not a new class. `CostTracker` already exists but is not wired in. The report generator already accepts `fact_recall_by_corpus` and `question_classes` — they just need to be passed from the CLI. The single existing namespace `bakeoff` is reused; per-mode / per-signal runs write to distinct raw JSON filenames so the report generator can aggregate without conflation.

**Tech Stack:** Python 3.12, `uv` package manager, `pytest` + `pytest-asyncio`, `click` for CLI, `asyncpg` via `pg-raggraph`, `fastembed` for local embeddings, `openai` async SDK, PostgreSQL 16 + pgvector + pg_trgm + AGE.

**Drift brief:** Read `skill-output/mission-brief/Mission-Brief-bakeoff-followup.md` BEFORE starting any phase and AT each DC-XXX gate. Re-read the original brief at phase transitions that touch the baseline numbers.

---

## File Structure

### New files

- `benchmarks/age-bakeoff/src/age_bakeoff/engines/pgrg_raw.py` — variant PgrgEngine that runs entity resolution at ingest (SC-006)
- `benchmarks/age-bakeoff/src/age_bakeoff/scorers/chunk_relevance.py` — LLM-judged chunk relevance metric (SC-001)
- `benchmarks/age-bakeoff/src/age_bakeoff/diagnostics.py` — diagnostic helpers: gold strictness sampler, context relevance sampler, top_k sweep
- `benchmarks/age-bakeoff/src/age_bakeoff/concurrency.py` — deterministic concurrent-query harness (SC-008)
- `benchmarks/age-bakeoff/sql/age_tuned_indexes.sql` — BTREE/GIN indexes for AGE (SC-009)
- `benchmarks/age-bakeoff/tests/test_incremental_ingest.py` — SC-007 pytest
- `benchmarks/age-bakeoff/tests/test_concurrency.py` — SC-008 pytest
- `benchmarks/age-bakeoff/tests/test_age_tuned_indexes.py` — SC-009 pytest
- `benchmarks/age-bakeoff/tests/test_pgrg_raw_engine.py` — SC-006 pytest
- `benchmarks/age-bakeoff/tests/test_diagnostics.py` — pytest for diagnostics module
- `benchmarks/age-bakeoff/tests/test_concurrency_determinism.py` — seed → same workload
- `benchmarks/age-bakeoff/tests/fixtures/quality_regression_corpus/` — small fixture for SC-002 regression test
- `benchmarks/age-bakeoff/results/QUALITY-ANALYSIS.md` — research report (SC-001)
- `benchmarks/age-bakeoff/README.md` — reproduction guide (SC-012)
- `benchmarks/age-bakeoff/ARCHITECTURE.md` — fairness + asymmetry doc (SC-013)

### Modified files

- `benchmarks/age-bakeoff/src/age_bakeoff/engines/pgrg.py` — add `signals` parameter (for BM25 isolation, SC-005)
- `benchmarks/age-bakeoff/src/age_bakeoff/config.py` — add `retrieval_mode`, `signals` config fields
- `benchmarks/age-bakeoff/src/age_bakeoff/cli.py` — add `--mode`, `--signals`, `--budget-usd`, `--label` options to `run`; add new subcommands (`diagnose`, `sweep`, `concurrent`, `age-tune`, `dry-run-pgsrc`)
- `benchmarks/age-bakeoff/src/age_bakeoff/runner.py` — accept `label` so per-mode runs write distinct files; accept `CostTracker`
- `benchmarks/age-bakeoff/src/age_bakeoff/scorers/llm_judge.py` — accept `CostTracker` passthrough
- `benchmarks/age-bakeoff/src/age_bakeoff/cost.py` — add `tally_report()` and `save_report(path)` helpers
- `benchmarks/age-bakeoff/src/age_bakeoff/report/generator.py` — wire `fact_recall_by_corpus` + `question_classes` into CLI, add "Mode comparison" and "Signals comparison" and "AGE tuning" sections, add per-class judge breakdown
- `benchmarks/age-bakeoff/src/age_bakeoff/cli.py::report` — pass fact recall + question classes to generator, load cost report, embed in REPORT.md
- `benchmarks/age-bakeoff/run-bakeoff.sh` — add the new runs to end-to-end script
- `benchmarks/age-bakeoff/TODO.md` — tick items as completed
- `docs/why-not-apache-age.md` — add "See Also" link to REPORT.md (from original brief SC-011 loose end)
- `benchmarks/age-bakeoff/pyproject.toml` — if cross-encoder re-ranker is attempted (see Phase 2), add `sentence-transformers` optional dep

---

## Phase 0: Foundations

Both features are pure infrastructure (no SC by themselves, they unblock everything). Small, fast, commit each.

### Task 0.1: Wire CostTracker into the runner + judge + CLI (SC-015)

**Files:**
- Modify: `benchmarks/age-bakeoff/src/age_bakeoff/cost.py`
- Modify: `benchmarks/age-bakeoff/src/age_bakeoff/runner.py`
- Modify: `benchmarks/age-bakeoff/src/age_bakeoff/cli.py`
- Modify: `benchmarks/age-bakeoff/src/age_bakeoff/scorers/llm_judge.py`
- Modify: `benchmarks/age-bakeoff/src/age_bakeoff/engines/openai_answerer.py`
- Test: `benchmarks/age-bakeoff/tests/test_cost.py`

- [ ] **Step 1: Write a failing test for `CostTracker.tally_report()`**

Append to `benchmarks/age-bakeoff/tests/test_cost.py`:

```python
def test_tally_report_summarises_by_model():
    from age_bakeoff.cost import CostTracker

    t = CostTracker(budget_usd=1.0)
    t.record("gpt-5-mini", 1000, 500)
    t.record("gpt-5-mini", 500, 250)
    t.record("gpt-4o-mini", 1000, 500)

    report = t.tally_report()
    assert report["total_usd"] == pytest.approx(t.total_usd, rel=1e-6)
    assert "gpt-5-mini" in report["by_model"]
    assert report["by_model"]["gpt-5-mini"]["calls"] == 2
    assert report["by_model"]["gpt-4o-mini"]["calls"] == 1
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd benchmarks/age-bakeoff && uv run pytest tests/test_cost.py::test_tally_report_summarises_by_model -v`
Expected: FAIL with `AttributeError: 'CostTracker' object has no attribute 'tally_report'`

- [ ] **Step 3: Implement `tally_report()` and `save_report()`**

Append to `benchmarks/age-bakeoff/src/age_bakeoff/cost.py`:

```python
    def tally_report(self) -> dict:
        by_model: dict[str, dict] = {}
        for call in self.calls:
            m = call["model"]
            bucket = by_model.setdefault(m, {"calls": 0, "usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0})
            bucket["calls"] += 1
            bucket["usd"] += call["usd"]
            bucket["prompt_tokens"] += call["prompt_tokens"]
            bucket["completion_tokens"] += call["completion_tokens"]
        return {
            "total_usd": self.total_usd,
            "budget_usd": self.budget_usd,
            "by_model": by_model,
        }

    def save_report(self, path) -> None:
        import json
        from pathlib import Path
        Path(path).write_text(json.dumps(self.tally_report(), indent=2, sort_keys=True))
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `uv run pytest tests/test_cost.py -v`
Expected: PASS for both new and existing tests.

- [ ] **Step 5: Plumb `CostTracker` into the answer path**

Modify `src/age_bakeoff/engines/openai_answerer.py` so `generate_answer()` accepts an optional `CostTracker` and calls `tracker.record(model, resp.usage.prompt_tokens, resp.usage.completion_tokens)` after each completion. Do the same in `src/age_bakeoff/scorers/llm_judge.py::judge_answer()`.

- [ ] **Step 6: Add `--budget-usd` flag to CLI `run` and `judge`**

In `src/age_bakeoff/cli.py`, after the `logging.basicConfig(...)` block, add a module-level `_TRACKER: CostTracker | None = None`. Add `--budget-usd` (default `50.0`) to `run` and `judge`. Initialise `_TRACKER = CostTracker(budget_usd)` at the top of each command. Thread `_TRACKER` into `runner.run_corpus()` and `judge_answer()`. After each command completes, call `_TRACKER.save_report(_RESULTS_DIR / "cost.json")` inside `finally:` so partial runs are tracked.

- [ ] **Step 7: Run the existing test suite to verify no regressions**

Run: `uv run pytest -v`
Expected: all pre-existing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/cost.py \
        benchmarks/age-bakeoff/src/age_bakeoff/runner.py \
        benchmarks/age-bakeoff/src/age_bakeoff/cli.py \
        benchmarks/age-bakeoff/src/age_bakeoff/scorers/llm_judge.py \
        benchmarks/age-bakeoff/src/age_bakeoff/engines/openai_answerer.py \
        benchmarks/age-bakeoff/tests/test_cost.py
git commit -m "feat(bakeoff): wire CostTracker into runner and judge with \$50 hard cap

SC-015: hard-caps OpenAI spend via CLI --budget-usd flag, writes cost.json
for embedding in REPORT.md."
```

### Task 0.2: Wire fact recall and per-class breakdown into REPORT.md (SC-011)

**Files:**
- Modify: `benchmarks/age-bakeoff/src/age_bakeoff/cli.py` (`report` command)
- Modify: `benchmarks/age-bakeoff/src/age_bakeoff/report/generator.py` (already accepts the params)
- Test: `benchmarks/age-bakeoff/tests/test_report.py`

- [ ] **Step 1: Write a failing test for fact recall in the report**

Append to `benchmarks/age-bakeoff/tests/test_report.py`:

```python
def test_report_includes_fact_recall_and_per_class_when_provided():
    from age_bakeoff.report.generator import generate_report
    from age_bakeoff.models import QuestionClass, RunResult

    results = [
        RunResult(engine="pgrg", corpus="acme", question_id="q1", run_number=1,
                  cold=True, retrieval_ms=20.0, answer_ms=100.0,
                  retrieved_chunk_ids=["a::1"], generated_answer="x"),
        RunResult(engine="age", corpus="acme", question_id="q1", run_number=1,
                  cold=True, retrieval_ms=40.0, answer_ms=110.0,
                  retrieved_chunk_ids=["a::1"], generated_answer="y"),
    ]
    md = generate_report(
        results_by_corpus={"acme": results},
        fact_recall_by_corpus={"acme": {"pgrg": {"q1": 1.0}, "age": {"q1": 0.5}}},
        question_classes={"acme": {"q1": QuestionClass.multi_hop_bridging}},
    )
    assert "### Fact Recall" in md
    assert "### Per-Question-Class Latency Breakdown" in md
    assert "multi_hop_bridging" in md
```

- [ ] **Step 2: Run the test and verify it passes** (the generator already has this code)

Run: `uv run pytest tests/test_report.py::test_report_includes_fact_recall_and_per_class_when_provided -v`
Expected: PASS (no implementation change needed — the generator already supports this; this test guards the contract).

- [ ] **Step 3: Write failing test for CLI report command passing fact recall**

Append to `benchmarks/age-bakeoff/tests/test_report.py`:

```python
def test_report_cli_computes_fact_recall_from_raw_and_questions(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from age_bakeoff.cli import cli

    # Copy fixtures into tmp_path (questions + raw + judge), point _RESULTS_DIR at it
    # (skip full detail — see test_report.py existing fixtures)
    ...
    # This test exercises: report CLI now loads questions/*.yaml, computes fact recall
    # from raw[i].retrieved_chunk_ids + gold required_facts, passes to generator.
    assert "### Fact Recall" in (tmp_path / "REPORT.md").read_text()
    assert "### Per-Question-Class Latency Breakdown" in (tmp_path / "REPORT.md").read_text()
```

Use existing fixtures in `tests/fixtures/`; if none cover this flow, add minimal fixture files alongside.

- [ ] **Step 4: Update `report` CLI command**

In `src/age_bakeoff/cli.py::report()`, after loading `results_by_corpus`:

```python
    from age_bakeoff.questions.schema import load_question_set
    from age_bakeoff.scorers.fact_recall import score_fact_recall

    fact_recall_by_corpus: dict[str, dict[str, dict[str, float]]] = {}
    question_classes: dict[str, dict[str, object]] = {}

    for name, results in results_by_corpus.items():
        yaml_path = _QUESTIONS_DIR / f"{name}.yaml"
        if not yaml_path.exists():
            continue
        qset = load_question_set(yaml_path)
        q_by_id = {q.id: q for q in qset.questions}
        question_classes[name] = {qid: q.question_class for qid, q in q_by_id.items()}

        per_engine: dict[str, dict[str, float]] = {}
        for r in results:
            if r.error or not r.retrieved_chunk_ids:
                continue
            q = q_by_id.get(r.question_id)
            if not q:
                continue
            # retrieved_chunk_ids are stored, but contents aren't in raw JSON;
            # reconstruct by loading chunk text is out of scope — use contents
            # directly if the runner is updated (see step 5). For now, score on
            # the generated_answer as a proxy, or store contents in raw.
            ...
```

**Note:** The runner currently stores `retrieved_chunk_ids` but not `retrieved_chunk_contents` in the raw JSON. To score fact recall at report time, the runner must also persist contents. Add that in step 5.

- [ ] **Step 5: Persist retrieved chunk contents in raw JSON**

Modify `src/age_bakeoff/models.py::RunResult` — add `retrieved_chunk_contents: list[str] = []` field. Modify `src/age_bakeoff/runner.py::run_corpus()` to populate it from `retrieval.retrieved_chunk_contents`. Update the fact-recall code in step 4 to use `r.retrieved_chunk_contents` when scoring.

- [ ] **Step 6: Run all tests, regenerate REPORT.md from existing raw**

```bash
uv run pytest tests/test_report.py -v
uv run age-bakeoff report
```

Expected: tests pass. REPORT.md now contains "Fact Recall" and "Per-Question-Class Latency Breakdown" sections per corpus. Note: since existing raw JSON doesn't have `retrieved_chunk_contents`, those existing runs will show empty fact recall until re-run in Phase 2.

- [ ] **Step 7: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/cli.py \
        benchmarks/age-bakeoff/src/age_bakeoff/runner.py \
        benchmarks/age-bakeoff/src/age_bakeoff/models.py \
        benchmarks/age-bakeoff/tests/test_report.py
git commit -m "feat(bakeoff): wire fact recall + per-class breakdown into REPORT.md

SC-011: report generator now receives fact recall and question classes;
runner persists retrieved_chunk_contents so fact recall is deterministic."
```

---

## Phase 1: Quality Research Diagnostics (SC-001)

Interleaved with quick-win infrastructure. Each task ships a diagnostic output or sub-report that QUALITY-ANALYSIS.md will later cite.

### Task 1.1: Gold-answer strictness audit

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/diagnostics.py`
- Create: `benchmarks/age-bakeoff/tests/test_diagnostics.py`
- Modify: `src/age_bakeoff/cli.py` (add `diagnose gold-strictness` subcommand)

- [ ] **Step 1: Write failing test for `sample_gold_alternative_phrasings`**

Create `tests/test_diagnostics.py`:

```python
import pytest

@pytest.mark.asyncio
async def test_sample_gold_alternative_phrasings_uses_judge():
    from age_bakeoff.diagnostics import sample_gold_alternative_phrasings

    class FakeClient:
        async def chat_create(self, **kwargs):
            class R: pass
            class Msg: content = '{"alternatives": ["alt 1", "alt 2"]}'
            class Choice: message = Msg()
            class Usage: prompt_tokens = 10; completion_tokens = 20
            r = R()
            r.choices = [Choice()]
            r.usage = Usage()
            return r

    out = await sample_gold_alternative_phrasings(
        client=FakeClient(), question="q", gold_answer="a", n=2, model="gpt-5-mini"
    )
    assert len(out) == 2
```

- [ ] **Step 2: Run, verify FAIL**

Run: `uv run pytest tests/test_diagnostics.py -v`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement diagnostics module**

Create `src/age_bakeoff/diagnostics.py`:

```python
"""Quality research diagnostics -- used for SC-001 QUALITY-ANALYSIS.md."""
from __future__ import annotations

import json
from typing import Any


async def sample_gold_alternative_phrasings(
    client: Any, question: str, gold_answer: str, n: int, model: str,
    tracker: Any | None = None,
) -> list[str]:
    """Ask the judge model for N alternative phrasings of the gold answer that
    should still be judged fully_correct. Used to audit strictness."""
    prompt = (
        f"Question: {question}\nCanonical answer: {gold_answer}\n\n"
        f"Produce {n} alternative answers that are factually equivalent but "
        f"worded differently. Return JSON: {{\"alternatives\": [str, ...]}}."
    )
    resp = await client.chat.completions.create(
        model=model, response_format={"type": "json_object"},
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker:
        tracker.record(model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
    data = json.loads(resp.choices[0].message.content or '{"alternatives": []}')
    return data.get("alternatives", [])[:n]
```

- [ ] **Step 4: Run test, verify PASS**

Run: `uv run pytest tests/test_diagnostics.py -v`
Expected: PASS.

- [ ] **Step 5: Add `diagnose gold-strictness` CLI subcommand**

In `src/age_bakeoff/cli.py`, add a `diagnose` click group and a `gold-strictness` subcommand that:
1. Loads each question from `questions/*.yaml`.
2. For 5 randomly-sampled questions per corpus (seeded with `--seed`, default 42), calls `sample_gold_alternative_phrasings(n=3)`.
3. For each alternative, calls `judge_answer(question, gold_answer, alternative, model)` — if any alternative is judged `wrong` or `hallucinated`, the gold is "strict".
4. Writes output to `results/diagnostics/gold_strictness.json`:

```json
{"acme": [{"qid": "q3", "strict_count": 2, "total": 3, "verdicts": [...]}, ...]}
```

- [ ] **Step 6: Run the subcommand**

```bash
export OPENAI_API_KEY=...
cd benchmarks/age-bakeoff
uv run age-bakeoff diagnose gold-strictness --budget-usd 50 --seed 42
```

Expected: `results/diagnostics/gold_strictness.json` exists; cost tracked.

- [ ] **Step 7: Commit**

```bash
git add benchmarks/age-bakeoff/src/age_bakeoff/diagnostics.py \
        benchmarks/age-bakeoff/src/age_bakeoff/cli.py \
        benchmarks/age-bakeoff/tests/test_diagnostics.py \
        benchmarks/age-bakeoff/results/diagnostics/gold_strictness.json
git commit -m "feat(bakeoff): diagnose gold-strictness subcommand (SC-001 input)

Samples alternative phrasings per question and asks the judge whether they
would still pass. Output feeds QUALITY-ANALYSIS.md."
```

### Task 1.2: Context relevance (chunk-relevance) metric

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/scorers/chunk_relevance.py`
- Create: test in `tests/test_chunk_relevance.py`
- Modify: `src/age_bakeoff/cli.py` (add `diagnose context-relevance`)

- [ ] **Step 1: Failing test**

Create `tests/test_chunk_relevance.py`:

```python
import pytest

@pytest.mark.asyncio
async def test_score_chunk_relevance_returns_per_chunk_relevance():
    from age_bakeoff.scorers.chunk_relevance import score_chunk_relevance

    class FakeClient:
        async def create(self, **kwargs):
            class R:
                class Msg: content = '{"relevances": [1.0, 0.5, 0.0]}'
                class Choice: message = Msg()
                class Usage: prompt_tokens = 100; completion_tokens = 20
                choices = [Choice()]; usage = Usage()
            return R()

    from types import SimpleNamespace
    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeClient()))
    scores = await score_chunk_relevance(
        client=client, question="q",
        chunks=["c1", "c2", "c3"], model="gpt-5-mini",
    )
    assert scores == [1.0, 0.5, 0.0]
```

- [ ] **Step 2: Run, FAIL**

Run: `uv run pytest tests/test_chunk_relevance.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement scorer**

Create `src/age_bakeoff/scorers/chunk_relevance.py`:

```python
"""LLM-judged per-chunk relevance. Used for SC-001 context quality analysis."""
from __future__ import annotations

import json
from typing import Any


async def score_chunk_relevance(
    client: Any, question: str, chunks: list[str], model: str,
    tracker: Any | None = None,
) -> list[float]:
    """Return per-chunk relevance in [0,1]. Judge model decides."""
    joined = "\n\n".join(f"[{i}] {c[:1200]}" for i, c in enumerate(chunks))
    prompt = (
        f"Question: {question}\n\nChunks:\n{joined}\n\n"
        "For each chunk, rate relevance to the question in [0,1] where 1 means "
        "fully answers or directly supports the answer. Return JSON: "
        '{"relevances": [float, ...]}. Length must match number of chunks.'
    )
    resp = await client.chat.completions.create(
        model=model, response_format={"type": "json_object"}, temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker:
        tracker.record(model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
    data = json.loads(resp.choices[0].message.content or '{"relevances": []}')
    return data.get("relevances", [])[: len(chunks)]
```

- [ ] **Step 4: Run, PASS**

Run: `uv run pytest tests/test_chunk_relevance.py -v`
Expected: PASS.

- [ ] **Step 5: Add `diagnose context-relevance` CLI subcommand**

In `cli.py`, add subcommand that loads existing raw JSON (`results/raw/*.json`), for each corpus picks 10 questions (seeded random), scores per-chunk relevance, writes `results/diagnostics/context_relevance.json` structured as `{corpus: {engine: {qid: [score, ...]}}}`.

- [ ] **Step 6: Run the subcommand and commit**

```bash
uv run age-bakeoff diagnose context-relevance --budget-usd 50 --seed 42
git add benchmarks/age-bakeoff/src/age_bakeoff/scorers/chunk_relevance.py \
        benchmarks/age-bakeoff/src/age_bakeoff/cli.py \
        benchmarks/age-bakeoff/tests/test_chunk_relevance.py \
        benchmarks/age-bakeoff/results/diagnostics/context_relevance.json
git commit -m "feat(bakeoff): diagnose context-relevance subcommand (SC-001 input)

LLM rates per-chunk relevance. Separates retrieval quality from answer
generation quality for the quality ceiling diagnosis."
```

### Task 1.3: top_k sweep diagnostic

**Files:**
- Modify: `src/age_bakeoff/diagnostics.py`, `src/age_bakeoff/cli.py`
- Create: `tests/test_top_k_sweep.py`

- [ ] **Step 1: Failing test**

Create `tests/test_top_k_sweep.py`:

```python
import pytest

@pytest.mark.asyncio
async def test_top_k_sweep_runs_each_k(monkeypatch):
    from age_bakeoff.diagnostics import top_k_sweep

    class FakeEngine:
        def __init__(self): self.top_k = 10
        async def retrieve(self, q):
            from age_bakeoff.engines.base import RetrievalResponse
            return RetrievalResponse(retrieved_chunk_ids=["a"], retrieved_chunk_contents=["x"], retrieval_ms=5.0)

    results = await top_k_sweep(engine=FakeEngine(), questions=["q1"], k_values=[5, 10, 20])
    assert set(results.keys()) == {5, 10, 20}
```

- [ ] **Step 2: Run, FAIL**
- [ ] **Step 3: Implement `top_k_sweep` in `diagnostics.py`**

```python
async def top_k_sweep(engine, questions: list[str], k_values: list[int]) -> dict[int, list]:
    out: dict[int, list] = {}
    for k in k_values:
        engine.top_k = k  # engines expose ._top_k privately; adjust attribute as they grow
        if hasattr(engine, "_top_k"):
            engine._top_k = k
        runs = []
        for q in questions:
            resp = await engine.retrieve(q)
            runs.append({"question": q, "chunk_ids": resp.retrieved_chunk_ids,
                         "contents": resp.retrieved_chunk_contents, "retrieval_ms": resp.retrieval_ms})
        out[k] = runs
    return out
```

- [ ] **Step 4: Run, PASS**
- [ ] **Step 5: Add `diagnose top-k-sweep` CLI subcommand** — writes `results/diagnostics/top_k_sweep.json` with `{engine: {corpus: {k: runs}}}`. Default `k_values=[5, 10, 20, 50]`.
- [ ] **Step 6: Run against existing corpora, commit**

```bash
uv run age-bakeoff diagnose top-k-sweep --corpus acme --corpus scotus
git add ... && git commit -m "feat(bakeoff): diagnose top-k-sweep subcommand (SC-001 input)

Runs same questions at multiple top_k values so QUALITY-ANALYSIS.md can
quantify whether raising k recovers missing facts."
```

---

## ⛔ DC-001: Mid-research drift check

**Re-read `skill-output/mission-brief/Mission-Brief-bakeoff-followup.md` now.**

Three questions:
1. Am I still solving the Purpose? (Closing the quality ceiling gap — yes if diagnostics are data-driven, no if I've jumped to fixes)
2. Does current work map to SC-XXX? (Tasks 1.1–1.3 → SC-001)
3. Am I doing anything in Out of Scope? (Check: no new corpora, no retuning defaults, no non-AGE benchmarking)

If drift detected: stop, state what drifted, propose correction. Otherwise proceed.

---

## Phase 2: Fix Experiments (SC-002, SC-003, SC-004, SC-005)

Each experiment writes to a distinct raw JSON label so REPORT.md can compare them. Mode comparison does double duty for SC-003 (smart) and SC-004 (local/global).

### Task 2.1: `--mode` and `--label` CLI options

**Files:**
- Modify: `src/age_bakeoff/cli.py` (`run` command)
- Modify: `src/age_bakeoff/runner.py`
- Modify: `src/age_bakeoff/engines/pgrg.py`
- Test: extend `tests/test_runner_schema.py`

- [ ] **Step 1: Failing test**

In `tests/test_runner_schema.py`, add:

```python
def test_runner_writes_label_suffix_in_filename(tmp_path):
    from age_bakeoff.runner import Runner, RunnerOptions
    opts = RunnerOptions(output_dir=tmp_path, runs_per_question=1, label="smart")
    # Use a minimal stub engine that returns a canned retrieval
    ...
    out = tmp_path / "acme__smart.json"
    assert out.exists()
```

- [ ] **Step 2: Run, FAIL**
- [ ] **Step 3: Implement label**

In `runner.py`, add `label: str | None = None` to `RunnerOptions`. In `run_corpus()`, replace:

```python
out = self.options.output_dir / f"{corpus}.json"
```

with:

```python
suffix = f"__{self.options.label}" if self.options.label else ""
out = self.options.output_dir / f"{corpus}{suffix}.json"
```

- [ ] **Step 4: Add `--mode` and `--label` to CLI `run`**

```python
@click.option("--mode", default=None, help="pg-raggraph retrieval mode: hybrid|smart|local|global|naive")
@click.option("--label", default=None, help="Suffix for raw JSON filename (e.g. 'smart')")
def run(corpus, runs, mode, label):
    ...
    cfg = _get_config()
    if mode:
        cfg.retrieval_mode = mode
    ...
    RunnerOptions(..., label=label)
```

Also add `retrieval_mode: str = "hybrid"` to `BakeoffConfig` in `config.py` with `PGRG_BAKEOFF_RETRIEVAL_MODE` env alias. Update `_get_engines()` in cli.py to pass `cfg.retrieval_mode` into `PgrgEngine(retrieval_mode=...)` — this plumbing already exists on the engine.

- [ ] **Step 5: Run, PASS**
- [ ] **Step 6: Commit**

### Task 2.2: Run `smart` mode on all 3 corpora (SC-003)

- [ ] **Step 1: Ensure Phase 0.2 fact-recall wiring lives**
- [ ] **Step 2: Run**

```bash
cd benchmarks/age-bakeoff
uv run age-bakeoff run --mode smart --label smart --corpus acme --corpus scotus
# pg-src runs in Phase 5
uv run age-bakeoff judge --corpus acme --corpus scotus
uv run age-bakeoff report
```

Expected: `results/raw/acme__smart.json` and `results/raw/scotus__smart.json` exist. Report generator picks them up (extend Phase 0.2 report glob to include `__*.json` patterns and group by `label`).

- [ ] **Step 3: Extend report generator to group labelled runs**

In `src/age_bakeoff/report/generator.py`, add a `labels_by_corpus: dict[str, list[str]] | None` input. If provided, emit a "Mode / Label Comparison" section per corpus with latency and judge columns per label. Update CLI `report` to scan filenames for `__<label>.json` patterns and pass them.

- [ ] **Step 4: Snapshot test for the new section**

Extend `tests/test_report.py` with a labelled-runs fixture; assert a "Mode / Label Comparison" header and `smart`, `hybrid` columns appear.

- [ ] **Step 5: Commit**

### Task 2.3: Run `local` and `global` modes on all 3 corpora (SC-004)

- [ ] **Step 1: Run**

```bash
uv run age-bakeoff run --mode local --label local --corpus acme --corpus scotus
uv run age-bakeoff run --mode global --label global --corpus acme --corpus scotus
uv run age-bakeoff judge --corpus acme --corpus scotus
uv run age-bakeoff report
```

- [ ] **Step 2: Verify REPORT.md has `local`, `global`, `hybrid`, `smart` rows per corpus in the comparison section**
- [ ] **Step 3: Commit**

```bash
git add benchmarks/age-bakeoff/results/
git commit -m "feat(bakeoff): local + global mode runs on acme + scotus (SC-004)"
```

### Task 2.4: BM25 isolation via `--signals` knob (SC-005)

**Files:**
- Modify: `src/age_bakeoff/engines/pgrg.py` (add `signals` param)
- Modify: `src/age_bakeoff/config.py`
- Modify: `src/age_bakeoff/cli.py`

- [ ] **Step 1: Read `pg-raggraph`'s retrieval signatures to find per-signal knobs**

Run `grep -rn "def.*signal" src/pg_raggraph/retrieval.py` (in the main package). If `signals: set[str] | None` already exists, thread it. If not, add a minimal knob in the retrieval function that allows toggling vector-only vs vector+bm25 vs full.

- [ ] **Step 2: Write failing test** for `PgrgEngine(signals={"vector"})` returning fewer hits than `signals=None` on a corpus where BM25 matters.

- [ ] **Step 3: Implement** — thread `signals` from CLI `--signals vector` through config and `PgrgEngine` into the retrieval call.

- [ ] **Step 4: Run experiments**

```bash
uv run age-bakeoff run --signals vector --label sig-vector --corpus acme --corpus scotus
uv run age-bakeoff run --signals vector,bm25 --label sig-vec-bm25 --corpus acme --corpus scotus
# baseline is full hybrid = signals vector,bm25,graph
uv run age-bakeoff judge --corpus acme --corpus scotus
uv run age-bakeoff report
```

- [ ] **Step 5: Verify REPORT.md has `sig-vector`, `sig-vec-bm25`, `hybrid` rows for BM25 contribution**

- [ ] **Step 6: Commit**

### Task 2.5: Cross-encoder re-ranking experiment (SC-002 candidate fix)

Only run this if quality has not moved by at least 10 pp after tasks 2.2–2.4.

- [ ] **Step 1: Add `sentence-transformers` to pyproject optional deps**
- [ ] **Step 2: Implement `ReRankedPgrgEngine` adapter** that calls `PgrgEngine.retrieve(top_k=50)` then re-ranks to top 10 with a cross-encoder
- [ ] **Step 3: Run with `--label rerank` on acme + scotus**
- [ ] **Step 4: Compare judge scores to baseline**
- [ ] **Step 5: Commit with findings either way — pass or fail counts**

---

## ⛔ DC-003: Fix-threshold gate

**Re-read `skill-output/mission-brief/Mission-Brief-bakeoff-followup.md` — SC-002 specifically.**

- Sum up judge verdicts across Tasks 2.2–2.5 per label per corpus.
- Did any `fully_correct` number beat the baseline (acme 5/30, scotus 11/30 for pgrg; acme 6/30, scotus 11/30 for age) by ≥10 pp (+3 questions) on at least one corpus?
- If YES → pick the best-performing mode/signal combination, add it to a regression test (see Task 2.6), and lock it in. Proceed to Phase 3.
- If NO → count distinct negative experiments (top_k sweep, mode swap, signal swap, re-ranking). Must be ≥3. If <3, run one more; otherwise declare the ceiling real.
- Do NOT soften the numbers. Record the outcome in `QUALITY-ANALYSIS.md` verbatim.

### Task 2.6: Regression test for the winning fix (conditional)

Only if a fix hit +10 pp.

**Files:**
- Create: `benchmarks/age-bakeoff/tests/fixtures/quality_regression_corpus/` (5-8 questions from the winning corpus)
- Create: `benchmarks/age-bakeoff/tests/test_quality_regression.py`

- [ ] **Step 1: Write failing test that runs baseline + winning config on the 5-8 fixture questions; asserts winning config has ≥1 extra `fully_correct`**
- [ ] **Step 2: Verify test passes when winning config is used**
- [ ] **Step 3: Commit**

---

## Phase 3: QUALITY-ANALYSIS.md Writeup (SC-001, SC-002)

### Task 3.1: Write `results/QUALITY-ANALYSIS.md`

**Files:**
- Create: `benchmarks/age-bakeoff/results/QUALITY-ANALYSIS.md`

- [ ] **Step 1: Draft the report**

Structure (write the full prose, no placeholders):

```markdown
# Quality Analysis — Why Do Both Engines Score 17-37% Fully Correct?

## TL;DR
{one paragraph}

## 1. Gold answer strictness
Finding: {}
Evidence: `results/diagnostics/gold_strictness.json`
  - acme: N/M alternatives were rejected by the judge
  - scotus: ...

## 2. Retrieval context relevance
Finding: {}
Evidence: `results/diagnostics/context_relevance.json`
  - mean per-chunk relevance on pgrg acme: X (median Y)
  - mean on age acme: X

## 3. top_k effect
Finding: {} ("+X pp" if positive, "no change" if negative)
Evidence: `results/diagnostics/top_k_sweep.json` + judge rerun

## 4. Retrieval mode comparison (smart vs local vs global vs hybrid)
Finding: {}
Evidence: `results/REPORT.md#mode-comparison`

## 5. BM25 contribution
Finding: {}
Evidence: `results/REPORT.md#signals-comparison`

## 6. Cross-encoder re-ranking
Finding: {} (or "not attempted" if ≥10 pp was already hit)
Evidence: `results/raw/*__rerank.json` + judge

## Conclusion
{one of: (a) the ceiling is real and here is the evidence, OR (b) configuration X lifted fully_correct by N pp on corpus Y, locked in via test_quality_regression.py}

## What this means for pg-raggraph defaults
{actionable recommendations; whether the default should change}
```

Every numeric claim in this document must link to a specific file path or REPORT.md anchor.

- [ ] **Step 2: Self-review**
  - [ ] Every subsection cites a file path
  - [ ] No "TBD" or "further investigation needed" placeholders
  - [ ] If ceiling is real, Conclusion states so plainly
  - [ ] If fix works, the ≥10 pp delta is the headline

- [ ] **Step 3: Commit**

---

## Phase 4: Feature Coverage Cycles

### Task 4.1: Entity resolution quality (SC-006)

**Files:**
- Create: `benchmarks/age-bakeoff/src/age_bakeoff/engines/pgrg_raw.py`
- Create: `tests/test_pgrg_raw_engine.py`

- [ ] **Step 1: Failing test** — engine runs `pg_trgm` fuzzy resolution on raw (unresolved) extraction

Create `tests/test_pgrg_raw_engine.py`:

```python
import pytest

@pytest.mark.asyncio
@pytest.mark.integration
async def test_pgrg_raw_engine_collapses_dup_entities(pgrg_dsn):
    from age_bakeoff.engines.pgrg_raw import PgrgRawEngine
    from age_bakeoff.models import ExtractionOutput, Chunk, ExtractedEntity

    extraction = ExtractionOutput(
        corpus="test",
        chunks=[Chunk(document_id="d1", content="Acme Inc makes rockets", sequence=0, metadata={})],
        entities=[
            ExtractedEntity(id="acme", name="Acme Inc", entity_type="Organization", description=""),
            ExtractedEntity(id="acme_inc", name="ACME INC", entity_type="Organization", description=""),
        ],
        relationships=[],
    )
    eng = PgrgRawEngine(dsn=pgrg_dsn, namespace="test_raw")
    await eng.ingest(extraction)
    # After resolution, only 1 entity should exist
    count = await eng._count_entities()
    assert count == 1
```

- [ ] **Step 2: Run, FAIL**

- [ ] **Step 3: Implement `PgrgRawEngine`** — subclass/copy `PgrgEngine` but skips the "already resolved" assumption. Instead:
  1. Inserts entities without deduplication
  2. After insert, runs a pg_trgm similarity pass (`SELECT similarity(a.name, b.name) ...`) at a configurable threshold (default 0.85)
  3. Merges entity pairs above threshold via a `resolved_entities` table + updates relationships + entity_chunks to point to the canonical entity

- [ ] **Step 4: Run, PASS**

- [ ] **Step 5: Run the benchmark with pgrg-raw label**

```bash
uv run age-bakeoff run --mode hybrid --label resolved --corpus acme --corpus scotus \
  --engine-override pgrg=PgrgRawEngine  # requires new CLI flag; or temporarily swap in _get_engines
uv run age-bakeoff judge --corpus acme --corpus scotus
uv run age-bakeoff report
```

Expected: judge scores + latencies recorded with label `resolved`. REPORT.md comparison shows delta vs baseline.

- [ ] **Step 6: Commit**

### Task 4.2: Incremental ingest (SC-007)

**Files:**
- Create: `tests/test_incremental_ingest.py`

- [ ] **Step 1: Failing test**

```python
import pytest, time

@pytest.mark.asyncio
@pytest.mark.integration
async def test_second_ingest_is_near_noop(pgrg_dsn, acme_extraction):
    from age_bakeoff.engines.pgrg import PgrgEngine

    eng = PgrgEngine(dsn=pgrg_dsn, namespace="inc_test")
    t0 = time.perf_counter()
    await eng.ingest(acme_extraction)
    first_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    await eng.ingest(acme_extraction)  # content hash dedup should short-circuit
    second_s = time.perf_counter() - t0

    assert second_s < first_s * 0.1, f"second={second_s}s expected <{first_s*0.1}s"
```

- [ ] **Step 2: Run, observe result**

If it PASSES immediately → `PgrgEngine` already has content-hash dedup correctly. If it FAILS → the engine currently does `await self._rag.delete(ns)` at the top of `ingest()`, which wipes everything. For SC-007, the engine must be modified (or a new method `ingest_incremental()` added) that uses content_hash to skip already-ingested chunks.

- [ ] **Step 3: Add `ingest_incremental()` to `PgrgEngine`**

```python
async def ingest_incremental(self, extraction: ExtractionOutput) -> int:
    """Ingest only chunks whose content_hash is not already present.
    Returns: number of chunks written (0 if all already ingested)."""
    await self._ensure_connected()
    db = self._rag.db
    ns = self._namespace

    # Compute content_hash for each chunk, check which are new
    from pg_raggraph.chunking import content_hash
    hashes = [content_hash(c.content) for c in extraction.chunks]
    existing = await db.fetch_all(
        "SELECT content_hash FROM documents WHERE namespace = %s AND content_hash = ANY(%s)",
        (ns, hashes),
    )
    existing_set = {r["content_hash"] for r in existing}
    new_chunks = [c for c, h in zip(extraction.chunks, hashes) if h not in existing_set]

    if not new_chunks:
        return 0
    # ... ingest new_chunks only; do not wipe ...
```

- [ ] **Step 4: Run test, PASS**
- [ ] **Step 5: Commit**

### Task 4.3: Concurrent query performance (SC-008)

**Files:**
- Create: `src/age_bakeoff/concurrency.py`
- Create: `tests/test_concurrency.py`, `tests/test_concurrency_determinism.py`
- Modify: `src/age_bakeoff/cli.py` (add `concurrent` subcommand)

- [ ] **Step 1: Failing test for determinism**

```python
@pytest.mark.asyncio
async def test_concurrent_workload_deterministic_under_seed():
    from age_bakeoff.concurrency import generate_workload
    a = generate_workload(questions=["q1", "q2", "q3"], parallelism=10, total=100, seed=42)
    b = generate_workload(questions=["q1", "q2", "q3"], parallelism=10, total=100, seed=42)
    assert a == b
```

- [ ] **Step 2: Run, FAIL**

- [ ] **Step 3: Implement `concurrency.py`**

```python
"""Deterministic concurrent-query harness for SC-008."""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any


def generate_workload(questions: list[str], parallelism: int, total: int, seed: int) -> list[tuple[int, str]]:
    rnd = random.Random(seed)
    return [(i, rnd.choice(questions)) for i in range(total)]


async def run_concurrent(engine: Any, workload: list[tuple[int, str]], parallelism: int) -> list[dict]:
    sem = asyncio.Semaphore(parallelism)
    results: list[dict] = []

    async def one(idx: int, q: str) -> None:
        async with sem:
            t0 = time.perf_counter()
            resp = await engine.retrieve(q)
            results.append({
                "idx": idx, "question": q,
                "retrieval_ms": resp.retrieval_ms,
                "wallclock_ms": (time.perf_counter() - t0) * 1000,
            })

    await asyncio.gather(*(one(i, q) for i, q in workload))
    return sorted(results, key=lambda r: r["idx"])
```

- [ ] **Step 4: Run, PASS**

- [ ] **Step 5: Add `concurrent` CLI subcommand**

```python
@cli.command()
@click.option("--corpus", "-c", required=True)
@click.option("--parallelism", default=10)
@click.option("--total", default=100)
@click.option("--seed", default=42)
def concurrent(corpus, parallelism, total, seed):
    """Run concurrent queries against pg-raggraph (SC-008)."""
    ...
    # Load questions, generate_workload, run_concurrent(pgrg_engine, workload, parallelism)
    # Write results/concurrency/{corpus}.json with {parallelism, total, seed, runs: [...]}
```

- [ ] **Step 6: Run on acme + scotus**

```bash
uv run age-bakeoff concurrent --corpus acme --parallelism 10 --total 100 --seed 42
uv run age-bakeoff concurrent --corpus scotus --parallelism 10 --total 100 --seed 42
```

- [ ] **Step 7: Extend report generator to include "Concurrent Queries" section** — table of p50/p95 under load, seed, parallelism, per corpus.

- [ ] **Step 8: Commit**

### Task 4.4: AGE with manually-tuned indexes (SC-009)

**Files:**
- Create: `benchmarks/age-bakeoff/sql/age_tuned_indexes.sql`
- Create: `tests/test_age_tuned_indexes.py`
- Modify: `src/age_bakeoff/cli.py` (add `age-tune` subcommand)

- [ ] **Step 1: Write the index DDL**

Create `sql/age_tuned_indexes.sql`:

```sql
-- Manual index tuning for AGE graph — BTREE on edge endpoints,
-- GIN on property JSONB. Evaluated against default AGE config for SC-009.
CREATE INDEX IF NOT EXISTS age_edge_start_idx ON bakeoff.ag_edge (start_id);
CREATE INDEX IF NOT EXISTS age_edge_end_idx   ON bakeoff.ag_edge (end_id);
CREATE INDEX IF NOT EXISTS age_edge_label_idx ON bakeoff.ag_edge (label);
CREATE INDEX IF NOT EXISTS age_vertex_props_gin_idx ON bakeoff.ag_vertex USING GIN (properties);
```

(Actual column names come from AGE's generated tables — verify via `\d bakeoff.ag_edge` inside the AGE docker container first and adjust.)

- [ ] **Step 2: Write failing EXPLAIN-based test**

```python
@pytest.mark.asyncio
@pytest.mark.integration
async def test_age_tuned_indexes_used_by_3hop_scotus_query(age_dsn):
    # Apply indexes
    ...
    # Run a canonical 3-hop SCOTUS cypher query with EXPLAIN ANALYZE
    plan = await fetch_explain_plan(age_dsn, CANONICAL_3HOP_QUERY)
    assert "age_edge_start_idx" in plan or "age_edge_end_idx" in plan
```

- [ ] **Step 3: Apply indexes, run test, PASS**

- [ ] **Step 4: Add `age-tune` CLI subcommand** that applies the SQL file via the AGE DSN.

- [ ] **Step 5: Re-run scotus benchmark against tuned AGE**

```bash
uv run age-bakeoff age-tune
uv run age-bakeoff run --corpus scotus --label age-tuned
uv run age-bakeoff judge --corpus scotus
uv run age-bakeoff report
```

Expected: REPORT.md shows `age` baseline vs `age-tuned` retrieval latencies side by side.

- [ ] **Step 6: Commit — including honest numbers even if AGE closes the gap**

---

## ⛔ DC-002: Baseline-preservation gate

**Execute after Task 4.1 completes (first feature-coverage cycle done).**

Re-read `skill-output/mission-brief/Mission-Brief-bakeoff-followup.md` → Constraints.

1. Re-run the original baseline:
   ```bash
   uv run age-bakeoff run --mode hybrid --label baseline-check --corpus acme --corpus scotus
   uv run age-bakeoff judge --corpus acme --corpus scotus
   ```
2. Compare `baseline-check` judge + latency numbers to the original `acme`/`scotus` values in `results/REPORT.md`:
   - acme pgrg p50: originally 33.1 ms — still within ±10%?
   - scotus pgrg p50: originally 60.3 ms — still within ±10%?
   - Judge verdicts within ±1 question per verdict class?
3. If any regression → STOP, identify which engine change caused it, decide whether to roll back or document as accepted divergence.

Do not proceed to Tasks 4.2+ until this gate is clean.

---

## Phase 5: pg-src Corpus (SC-010)

### Task 5.1: Run LLM extraction on pg-src

**Files:**
- Uses existing `src/age_bakeoff/extraction/pg_src.py`

- [ ] **Step 1: Verify fetch + extraction cache paths**

```bash
ls benchmarks/age-bakeoff/corpora/pg-src/src/backend/executor | head
ls benchmarks/age-bakeoff/corpora/pg-src/doc/src/sgml | head
```

- [ ] **Step 2: Write extraction entry script** if one doesn't exist

Check if `scripts/extract_pg_src.py` exists. If not, create:

```python
"""Run LLM extraction on pg-src corpus. Caches to corpora/pg-src/extraction_cache.json."""
import asyncio, os
from pathlib import Path
from openai import OpenAI
from age_bakeoff.chunker import chunk_pg_src_corpus  # existing or to be written
from age_bakeoff.extraction.pg_src import extract_pg_src

def main():
    cache = Path(__file__).resolve().parents[1] / "corpora" / "pg-src" / "extraction_cache.json"
    chunks = chunk_pg_src_corpus(Path(__file__).resolve().parents[1] / "corpora" / "pg-src")
    client = OpenAI()
    out = extract_pg_src(chunks=chunks, client=client, cache_path=cache, model="gpt-5-mini")
    print(f"Cached {len(out.chunks)} chunks, {len(out.entities)} entities, {len(out.relationships)} relationships")

if __name__ == "__main__":
    main()
```

If `chunk_pg_src_corpus` doesn't exist, add it — re-use `src/age_bakeoff/chunker.py`.

- [ ] **Step 3: Run extraction (first time — uses budget)**

```bash
export OPENAI_API_KEY=...
cd benchmarks/age-bakeoff
uv run python scripts/extract_pg_src.py
```

Expected: `corpora/pg-src/extraction_cache.json` appears; est. $1-2 OpenAI cost per TODO.md.

- [ ] **Step 4: Verify chunk count in extraction cache**

```bash
python -c "import json; d=json.load(open('corpora/pg-src/extraction_cache.json')); print(f'chunks={len(d[\"chunks\"])} entities={len(d[\"entities\"])} rels={len(d[\"relationships\"])}')"
```

Record the number for REPORT.md (SC-010 honesty requirement).

- [ ] **Step 5: Commit extraction cache**

```bash
git add benchmarks/age-bakeoff/corpora/pg-src/extraction_cache.json \
        benchmarks/age-bakeoff/scripts/extract_pg_src.py
git commit -m "feat(bakeoff): pg-src LLM extraction cache (SC-010)"
```

### Task 5.2: Run pg-src benchmark

- [ ] **Step 1: Run**

```bash
uv run age-bakeoff run --corpus pg-src  # hybrid + baseline modes first
uv run age-bakeoff run --mode smart --label smart --corpus pg-src
uv run age-bakeoff run --mode local --label local --corpus pg-src
uv run age-bakeoff run --mode global --label global --corpus pg-src
uv run age-bakeoff judge --corpus pg-src
uv run age-bakeoff report
```

- [ ] **Step 2: Verify pg-src appears in REPORT.md with all same sections as acme/scotus**
- [ ] **Step 3: Verify chunk count is noted in REPORT.md's Overview or pg-src section**

If not, extend report generator to include per-corpus `chunk_count` in the Overview. Raw JSON already carries chunk ids so count is the number of unique ids across all questions.

- [ ] **Step 4: Commit results**

---

## ⛔ DC-005: pg-src reproducibility gate

After Task 5.2 completes:

1. `./run-bakeoff.sh` from a clean state (or close approximation) must complete all three corpora.
2. If the script doesn't yet include pg-src, update it.
3. Re-run the existing acme + scotus canonical runs after the pg-src add and verify numbers still match ±10%.
4. Any divergence gets documented, not buried.

---

## Phase 6: Docs Closeout

### Task 6.1: Regenerate REPORT.md with all new data

- [ ] **Step 1: Run the full report**

```bash
uv run age-bakeoff report
```

- [ ] **Step 2: Verify** the following sections exist for each corpus (acme, scotus, pg-src):
  - Latency (retrieval + answer) — from baseline hybrid
  - Fact Recall table
  - LLM Judge Verdicts table
  - Per-Question-Class Latency Breakdown
  - Per-Question-Class Judge Breakdown (add to generator if missing)
  - Mode / Label Comparison (hybrid, smart, local, global, plus pgrg-raw, sig-vector, sig-vec-bm25, rerank if run, age-tuned for scotus)
  - Concurrent Queries (acme, scotus only)
  - Chunk count for pg-src

- [ ] **Step 3: Commit**

```bash
git add benchmarks/age-bakeoff/results/REPORT.md
git commit -m "docs(bakeoff): regenerate REPORT.md with follow-up phase data"
```

---

## ⛔ DC-004: Where-AGE-wins honesty gate

Before writing ARCHITECTURE.md:

1. Re-read original brief SC-008 ("Where AGE wins").
2. Look at the new REPORT.md "age-tuned" row for scotus — did tuning close the 47× gap significantly?
3. Look at any per-question-class breakdown — is AGE winning on single-hop or factual questions anywhere?
4. Any AGE win on any metric must appear prominently in REPORT.md's "Where AGE Wins" section and be surfaced in ARCHITECTURE.md too. If the instinct is to soften, stop and rewrite.

---

### Task 6.2: Write ARCHITECTURE.md (SC-013)

**Files:**
- Create: `benchmarks/age-bakeoff/ARCHITECTURE.md`

- [ ] **Step 1: Draft the document**

Structure:

```markdown
# AGE vs pg-raggraph Bake-off — Architecture

## TL;DR
What this benchmark measures, what it doesn't.

## Fairness mechanisms
- Shared chunker (reference `src/age_bakeoff/chunker.py`)
- Identical embedding model (FastEmbed BAAI/bge-small-en-v1.5) — verified at runtime via `verify_symmetry()`
- Identical answer model (OpenAI — configurable) — verified at runtime
- Identical judge model
- Same `top_k` and `hop_budget` where concept exists (enforced in runner)

## Known engine asymmetries
- **pg-raggraph writes via direct SQL, bypassing its LLM extractor** — benchmark exercises retrieval, not extraction. Why: extraction variability would dominate judge scores.
- **AGE uses Cypher graph traversal + pgvector, fused client-side** — required because AGE cannot combine Cypher with pgvector in one SQL statement (see `docs/why-not-apache-age.md`).
- **AGE indexes**: default + manual BTREE/GIN per `sql/age_tuned_indexes.sql` (applied in the `age-tuned` label runs). See findings in REPORT.md §"AGE with tuned indexes".
- **pg-raggraph retrieval fuses vector + BM25 + graph in one SQL query** — BM25 contribution is isolated in `--signals` runs.
- **Entity resolution**: baseline pgrg runs use pre-resolved entities (fair to AGE); `resolved` label exercises `PgrgRawEngine` with pg_trgm.

## What this measures
- Retrieval latency (p50/p95 cold + warm)
- Answer-generation latency
- Fact recall (deterministic string match)
- LLM-judged answer quality
- Per-question-class breakdown
- BM25 isolation
- Entity-resolution quality delta
- Concurrent-query throughput (pgrg only)
- Incremental-ingest noop behaviour (pgrg only)

## What this does NOT measure
- Cloud-provider compatibility (AGE requires shared_preload_libraries — definitionally out)
- Ingest latency (retrieval is the thesis)
- Large-document scale (>10K chunk corpora not included; pg-src at ~5-8K is the biggest)
- Multi-tenant isolation
- Non-OpenAI answer models
- Alternative embedding models

## Where AGE wins
Live section: see REPORT.md "Where AGE Wins". {Summarise current findings here in one paragraph, no softening.}

## Reproduction
See `README.md`.
```

- [ ] **Step 2: Self-review** — every claim either states measurement or points to the raw source.

- [ ] **Step 3: Commit**

### Task 6.3: Write README.md (SC-012)

**Files:**
- Create: `benchmarks/age-bakeoff/README.md`

- [ ] **Step 1: Draft**

Structure:

```markdown
# AGE vs pg-raggraph Bake-off

Reproducible benchmark comparing Apache AGE and pg-raggraph on three corpora.

## Prerequisites
- Docker
- OpenAI API key (models: `gpt-5-mini` default; `gpt-4o-mini` fallback)
- ~60 minutes wall time

## Setup
\`\`\`bash
cd benchmarks/age-bakeoff
docker compose up -d      # Postgres with pgvector + pg_trgm, and AGE
uv sync
cp .env.example .env      # fill in OPENAI_API_KEY
\`\`\`

## Run the full benchmark
\`\`\`bash
./run-bakeoff.sh
\`\`\`

This runs (in order):
1. Extraction (LLM) for each corpus; cached
2. Ingest into both engines per corpus
3. 30 questions × 3 runs × 2 engines × N modes per corpus
4. LLM judge
5. REPORT.md generation

## Selective runs
\`\`\`bash
# Just one corpus
uv run age-bakeoff run --corpus acme

# Just one mode
uv run age-bakeoff run --mode smart --label smart --corpus acme

# Just concurrent queries
uv run age-bakeoff concurrent --corpus scotus --parallelism 10 --total 100

# AGE with tuned indexes
uv run age-bakeoff age-tune
uv run age-bakeoff run --corpus scotus --label age-tuned
\`\`\`

## Swap models
Edit `.env`:
\`\`\`
PGRG_BAKEOFF_ANSWER_MODEL=gpt-4o-mini
PGRG_BAKEOFF_JUDGE_MODEL=gpt-4o-mini
\`\`\`
Cost cap: `--budget-usd 50` on any command.

## Add a corpus
1. Drop the content under `corpora/<name>/`.
2. Implement a loader under `src/age_bakeoff/corpora/<name>.py`.
3. Create `questions/<name>.yaml` (30 questions, ≥5 bridging; schema: `src/age_bakeoff/questions/schema.py`).
4. Register in `src/age_bakeoff/cli.py::_load_corpora()`.

## Interpret results
`results/REPORT.md` has per-corpus tables. Fact recall and judge verdicts are the quality signals; latency tables are the speed signal. See `ARCHITECTURE.md` for fairness mechanisms and engine asymmetries. See `results/QUALITY-ANALYSIS.md` for why judge scores sit where they do.

## Troubleshooting
- **"pg-src extraction cache not found"** — run `uv run python scripts/extract_pg_src.py`.
- **"Cost budget exceeded"** — raise `--budget-usd`; cheapest fallback is `gpt-4o-mini`.
- **AGE docker container fails to start** — AGE image is sensitive to Postgres version; see `docker-compose.yml`.
```

- [ ] **Step 2: Self-review** — dry-run the steps from this README on a clean clone. Note any step that required tribal knowledge; fix the README.

- [ ] **Step 3: Commit**

### Task 6.4: Update `docs/why-not-apache-age.md` "See Also"

- [ ] **Step 1: Add to its See Also section**

```markdown
- [AGE Bake-off REPORT](../benchmarks/age-bakeoff/results/REPORT.md) — our measured numbers
- [AGE Bake-off ARCHITECTURE](../benchmarks/age-bakeoff/ARCHITECTURE.md) — fairness mechanisms
- [Quality analysis](../benchmarks/age-bakeoff/results/QUALITY-ANALYSIS.md) — why judge scores sit where they do
```

- [ ] **Step 2: Commit**

### Task 6.5: Close original-brief DC-003, DC-004, DC-FINAL (SC-014)

**Files:**
- Modify: `benchmarks/age-bakeoff/TODO.md`

- [ ] **Step 1: Re-read `skill-output/mission-brief/Mission-Brief-age-bakeoff.md`**

- [ ] **Step 2: For each SC-001 through SC-011, record evidence**

Create/update a section near the bottom of `ARCHITECTURE.md` OR a new `EVIDENCE.md`:

```markdown
# Original brief evidence closeout

- SC-001 (identical chunks): `src/age_bakeoff/chunker.py` + `tests/test_chunker.py`
- SC-002 (identical models): `runner.py::verify_symmetry()`
- SC-003 (question schema): `tests/test_questions_schema.py`; acme=30 (6 bridging), scotus=30 (6 bridging), pg-src=30 (6 bridging)
- SC-004 (3 runs per question): `runner.py::run_corpus()` with `runs_per_question=3`
- SC-005 (fact recall): `scorers/fact_recall.py` + `REPORT.md#fact-recall`
- SC-006 (LLM judge majority vote): `scorers/llm_judge.py` + `tests/test_llm_judge.py`
- SC-007 (deterministic report): `tests/test_report.py` snapshot
- SC-008 (where AGE wins): `REPORT.md#where-age-wins` (section is live and non-empty iff AGE actually won somewhere)
- SC-009 (under 60 min wallclock): record the `date` delta embedded in REPORT.md
- SC-010 (reproducible): README.md end-to-end + the clean-state dry-run (see README)
- SC-011 (docs/why-not-apache-age.md updated): see commit 7871e10 ("measured 47x")
```

- [ ] **Step 3: Mark relevant TODO items complete in `benchmarks/age-bakeoff/TODO.md`**

- [ ] **Step 4: Commit**

```bash
git add benchmarks/age-bakeoff/ARCHITECTURE.md benchmarks/age-bakeoff/TODO.md
git commit -m "docs(bakeoff): close original-brief DCs and record evidence (SC-014)"
```

---

## ⛔ DC-FINAL: Completion gate

**Re-read BOTH briefs before declaring done.**

For each SC-XXX in the follow-up brief, list the evidence:

- SC-001 → `results/QUALITY-ANALYSIS.md` exists, each section cites a file
- SC-002 → either ≥10 pp lift (regression test `tests/test_quality_regression.py` passes) OR ≥3 negative experiments documented in QUALITY-ANALYSIS.md §Conclusion
- SC-003 → REPORT.md has "smart" label rows for acme, scotus, pg-src
- SC-004 → REPORT.md has "local" and "global" label rows for acme, scotus, pg-src
- SC-005 → REPORT.md has "sig-vector" and "sig-vec-bm25" label rows
- SC-006 → REPORT.md has "resolved" label rows; `tests/test_pgrg_raw_engine.py` passes
- SC-007 → `tests/test_incremental_ingest.py` passes
- SC-008 → REPORT.md has "Concurrent Queries" section; `tests/test_concurrency*.py` pass
- SC-009 → REPORT.md scotus has "age-tuned" row; `tests/test_age_tuned_indexes.py` passes
- SC-010 → pg-src present in all REPORT.md sections; chunk count noted
- SC-011 → REPORT.md has "Fact Recall" and "Per-Question-Class" sections per corpus
- SC-012 → README.md exists; dry-run notes captured
- SC-013 → ARCHITECTURE.md exists; every asymmetry listed
- SC-014 → Original-brief DCs closed with explicit evidence
- SC-015 → `results/cost.json` shows total ≤ $50

For each Original brief SC-001–SC-011: evidence cited in ARCHITECTURE.md or EVIDENCE.md section.

If any SC lacks evidence, the work is NOT complete. File the missing evidence as a new task and reopen the relevant Phase.

---

## Self-Review (completed while writing this plan)

**1. Spec coverage:** Every SC-XXX in the follow-up brief is covered by at least one task. DC-001 through DC-FINAL are all injected as hard gates. Original-brief DC closure is explicitly SC-014.

**2. Placeholder scan:** No "TBD" or "implement later" in any Step that produces code. QUALITY-ANALYSIS.md structure is spelled out with section headings and evidence-file pointers; prose per finding is intentionally TBD at plan-write time because it depends on experiment results (not a code placeholder — this is normal for a research report).

**3. Type consistency:** `PgrgEngine(retrieval_mode=…, signals=…)` signature is consistent across tasks. `RunnerOptions.label` is used the same way in all run invocations. `CostTracker` is passed to answerer and judge identically. Raw filename convention is `{corpus}.json` for baseline, `{corpus}__{label}.json` for labelled runs — used consistently in Tasks 2.1–4.4.
