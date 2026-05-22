# lede v0.4 Hint-Biased Summary Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, LLM-free `mode="summary"` to pg-raggraph that runs lede v0.4 hint-biased summarization over hybrid-retrieved chunks, plus a smart-mode tier-0 path and a lede-summary replacement for the weak no-LLM fallback in `answer.py`.

**Architecture:** Retrieval is unchanged — `mode="summary"` runs an existing substrate (`summary_base_mode`, default `hybrid`), then concatenates the returned K chunks and feeds them to `lede.summarize(..., hints=...)`. Hints are derived from the query via `lede.extract.top_terms` (rank-weighted seeds) and optionally expanded with `lede_spacy.expand_hints` (lemma/synonym/similar), capped at `max_hints`. Smart mode's high-confidence branch can ship the summary without an LLM. `generate_answer` returns a populated summary directly when present, and falls back to a lede summary when no LLM is configured.

**Tech Stack:** Python 3.12+, lede>=0.4 (core, deterministic), lede-spacy>=0.4 (optional expansion), spaCy, pydantic-settings, asyncpg, pytest/pytest-asyncio.

**Mission Brief:** `skill-output/mission-brief/Mission-Brief-lede-v0.4-hint-biased-summary-retrieval.md` — all SC-XXX and DC-XXX references below map to that brief.

---

## PREREQUISITE GATE — SATISFIED (2026-05-22)

lede **0.4.1** and lede-spacy **0.4.1** are on PyPI and installed into the project venv. API verified live against 0.4.1:
- `lede.summarize(text, max_length, mode, attach, hints, hint_focus, hint_mode).summary` ✓
- `lede.extract.top_terms(text, n, kinds, with_scores, hints, hint_focus, hint_mode)` → `tuple[str, ...]` ✓
- `lede_spacy.expand_hints(hints, kinds, top_k, expand_weight)` → dict-in/dict-out ✓
- `spacy.util.is_package("en_core_web_md"/"_lg")` → both False, `en_core_web_sm` True → SC-005 degradation path is live and testable as-is.

---

## File Structure

**New files:**
- `src/pg_raggraph/summary.py` — hint pipeline (`build_hints`, `_resolve_expansion_tier`, `_has_vector_model`, `_seed_weights`) + `summarize_chunks`. Pure: no DB, no LLM, no network.
- `tests/unit/test_summary_hints.py` — unit tests for the hint pipeline and tier degradation.
- `tests/unit/test_summary_answer.py` — unit tests for `generate_answer` summary/fallback behavior (no DB).
- `tests/integration/test_summary_mode.py` — integration tests for `mode="summary"`, `summary_base_mode`, smart tier-0, and the latency budget.

**Modified files:**
- `src/pg_raggraph/config.py` — new config fields (after line 382, in the smart-mode block).
- `src/pg_raggraph/models.py` — `QueryResult.summary` field.
- `src/pg_raggraph/retrieval.py` — `QueryMode` literal, `valid_modes`, `mode="summary"` dispatch, `_summary_query`, smart tier-0 branch, `summary_base_mode` threading.
- `src/pg_raggraph/answer.py` — `generate_answer` returns populated summary; `_fallback_answer` rewritten to use `summarize_chunks`.
- `src/pg_raggraph/__init__.py` — `GraphRAG.query` accepts `summary_base_mode` kwarg and threads it through; docstring mode list updated.
- `src/pg_raggraph/cli.py` — add `"summary"` to the three `--mode` `click.Choice` lists.
- `pyproject.toml` — bump `lede>=0.4` and `lede-spacy>=0.4` in both the `lede_spacy` extra and the `dev` group.

---

## Task 1: Config fields + dependency pin

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/pg_raggraph/config.py:382` (insert after `graph_boost_factor`)

- [ ] **Step 1: Bump lede pins in pyproject.toml**

In `pyproject.toml`, change the `lede_spacy` extra and the `dev` group pins from `>=0.3` to `>=0.4`:

```toml
lede_spacy = ["lede>=0.4", "lede-spacy>=0.4", "spacy>=3.7"]
```

And in the `dev` dependency group, change the two lines:

```toml
    "lede>=0.4",
    "lede-spacy>=0.4",
```

- [ ] **Step 2: Add config fields**

In `src/pg_raggraph/config.py`, immediately after the line `graph_boost_factor: float = 1.2  # multiplier for chunks connected to seed entities` (line 382), insert:

```python

    # --- lede v0.4 hint-biased summary retrieval ---
    # mode="summary" runs an existing retrieval substrate, then summarizes
    # its K chunks deterministically (no LLM) via lede's hint-biased
    # summarize. See docs/superpowers/plans/2026-05-22-lede-hint-summary-retrieval.md.
    summary_base_mode: Literal["naive", "local", "global", "hybrid"] = "hybrid"
    summary_max_length: int = 2000  # char budget passed to lede.summarize
    summary_hint_focus: float = 0.5  # 0=ignore hints, 1=hints only; 0.5 = "50/50 mix"
    # Query → hint pipeline.
    query_expansion: Literal["off", "lemma", "moderate", "aggressive"] = "moderate"
    summary_seed_terms: int = 4  # top_terms(question, n=) seed count
    expand_top_k: int = 3  # per-seed synonym/similar cap in expand_hints
    expand_weight: float = 0.5  # expansion-term weight multiplier (dict input)
    max_hints: int = 20  # hard cap on total hints after expansion
    # Smart-mode tier-0: ship a deterministic lede summary (no LLM) when the
    # naive top score clears summary_tier_threshold. Off by default.
    smart_summary_tier: bool = False
    summary_tier_threshold: float = 0.85
```

- [ ] **Step 3: Verify config loads**

Run: `uv run python -c "from pg_raggraph.config import PGRGConfig; c = PGRGConfig(); print(c.summary_base_mode, c.query_expansion, c.max_hints, c.summary_hint_focus)"`
Expected: `hybrid moderate 20 0.5`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml src/pg_raggraph/config.py
git commit -m "feat: add summary-retrieval config fields and bump lede to >=0.4"
```

---

## Task 2: QueryResult.summary field

**Files:**
- Modify: `src/pg_raggraph/models.py:209-219`
- Test: `tests/unit/test_summary_hints.py` (created here, extended in Task 3)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_summary_hints.py`:

```python
"""Unit tests for the lede-hint summary pipeline and QueryResult.summary."""

from __future__ import annotations

from pg_raggraph.models import ChunkResult, QueryResult


def test_query_result_has_summary_field_default_empty():
    qr = QueryResult(chunks=[ChunkResult(content="x", score=0.9)])
    assert qr.summary == ""


def test_query_result_summary_roundtrips():
    qr = QueryResult(summary="a deterministic summary")
    assert qr.summary == "a deterministic summary"
    assert qr.model_dump()["summary"] == "a deterministic summary"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_summary_hints.py -v`
Expected: FAIL — `QueryResult` has no field `summary` (the second test raises on `model_dump()["summary"]` KeyError / the first on attribute access).

- [ ] **Step 3: Add the field**

In `src/pg_raggraph/models.py`, in the `QueryResult` class, add the `summary` field directly after `answer: str = ""` (line 210):

```python
    answer: str = ""
    summary: str = ""
    """Deterministic, LLM-free lede summary of the retrieved chunks. Populated
    by mode="summary" and by smart-mode tier-0; empty for other modes. When
    non-empty, generate_answer() ships it directly without an LLM round-trip."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_summary_hints.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/models.py tests/unit/test_summary_hints.py
git commit -m "feat: add QueryResult.summary field"
```

---

## Task 3: Hint pipeline — build_hints (SC-002, SC-003)

**Files:**
- Create: `src/pg_raggraph/summary.py`
- Test: `tests/unit/test_summary_hints.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_summary_hints.py`:

```python
import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph import summary as summary_mod


def test_seed_weights_are_deterministic_and_descending():
    q = "What county does John Smith live in and what taxes apply?"
    w1 = summary_mod._seed_weights(q, n=4)
    w2 = summary_mod._seed_weights(q, n=4)
    assert w1 == w2  # SC-002: deterministic
    weights = list(w1.values())
    assert weights == sorted(weights, reverse=True)  # rank 0 heaviest
    assert all(0.0 < v <= 1.0 for v in weights)


def test_build_hints_deterministic():
    cfg = PGRGConfig(query_expansion="moderate")
    q = "How does pgvector cosine similarity rank chunks?"
    assert summary_mod.build_hints(q, cfg) == summary_mod.build_hints(q, cfg)  # SC-002


def test_build_hints_respects_max_hints_cap():
    cfg = PGRGConfig(query_expansion="moderate", max_hints=2)
    q = "networking tcp packet routing latency throughput congestion window"
    hints = summary_mod.build_hints(q, cfg)
    assert len(hints) <= 2  # SC-003


def test_build_hints_empty_query_returns_empty():
    cfg = PGRGConfig(query_expansion="moderate")
    assert summary_mod.build_hints("", cfg) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_summary_hints.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pg_raggraph.summary'`

- [ ] **Step 3: Create summary.py with the hint pipeline**

Create `src/pg_raggraph/summary.py`:

```python
"""Deterministic, LLM-free summary of retrieved chunks via lede v0.4 hints.

Builds query-derived hints (top_terms seeds, optional lede-spacy lemma /
synonym / similar expansion) and runs lede's hint-biased summarize over the
concatenated retrieved chunks. No LLM, no network, no DB.

Optional deps for expansion — install with:
    pip install 'pg-raggraph[lede_spacy]'
    python -m spacy download en_core_web_sm   # lemma + synonyms
    python -m spacy download en_core_web_md   # also enables "similar"
"""

from __future__ import annotations

import logging
import warnings

from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import QueryResult

logger = logging.getLogger("pg_raggraph.summary")

# spaCy expansion kinds per query_expansion tier.
_EXPANSION_KINDS: dict[str, tuple[str, ...]] = {
    "off": (),
    "lemma": ("lemma",),
    "moderate": ("lemma", "synonyms"),
    "aggressive": ("lemma", "synonyms", "similar"),
}


def _has_vector_model() -> bool:
    """True if a spaCy model with word vectors (md/lg) is installed.

    The "similar" expansion kind needs vectors; sm has none.
    """
    try:
        import spacy.util
    except ModuleNotFoundError:
        return False
    return spacy.util.is_package("en_core_web_md") or spacy.util.is_package("en_core_web_lg")


def _resolve_expansion_tier(tier: str) -> str:
    """Resolve query_expansion tier, degrading 'aggressive' → 'moderate' when
    no vector model (md/lg) is installed. Emits exactly one warning on degrade.
    """
    if tier == "aggressive" and not _has_vector_model():
        warnings.warn(
            "query_expansion='aggressive' needs en_core_web_md or en_core_web_lg "
            "for the 'similar' expansion; falling back to 'moderate'. "
            "Install with: python -m spacy download en_core_web_md",
            stacklevel=2,
        )
        return "moderate"
    return tier


def _seed_weights(question: str, n: int) -> dict[str, float]:
    """Top-N salient terms from the question, weighted by rank position.

    Rank 0 → heaviest, decaying linearly. Deterministic. Returns {} when lede
    yields no terms (e.g. empty or stopword-only query).
    """
    from lede.extract import top_terms

    terms = [t for t in top_terms(question, n=n) if t and t.strip()]
    if not terms:
        return {}
    denom = len(terms) + 1
    return {t: round(1.0 - (i / denom), 4) for i, t in enumerate(terms)}


def build_hints(question: str, config: PGRGConfig) -> dict[str, float]:
    """Query → ordered, weighted, capped hint dict for lede.summarize.

    1. Seed terms via lede.extract.top_terms (weighted by rank).
    2. Optional expansion via lede_spacy.expand_hints, gated by
       config.query_expansion. 'aggressive' degrades to 'moderate' (one
       warning) when no md/lg model is present. If lede-spacy isn't
       installed, expansion is skipped silently and raw seeds are used.
    3. Cap at config.max_hints (highest weight first; deterministic tie-break).
    """
    seeds = _seed_weights(question, config.summary_seed_terms)
    if not seeds:
        return {}

    tier = _resolve_expansion_tier(config.query_expansion)
    kinds = _EXPANSION_KINDS[tier]
    hints: dict[str, float] = dict(seeds)

    if kinds:
        try:
            from lede_spacy import expand_hints

            hints = dict(
                expand_hints(
                    seeds,
                    kinds=kinds,
                    top_k=config.expand_top_k,
                    expand_weight=config.expand_weight,
                )
            )
        except ModuleNotFoundError:
            logger.info("lede-spacy not installed; using raw seed terms without expansion.")
            hints = dict(seeds)

    if len(hints) > config.max_hints:
        ordered = sorted(hints.items(), key=lambda kv: (-kv[1], kv[0]))
        hints = dict(ordered[: config.max_hints])
    return hints


def summarize_chunks(question: str, result: QueryResult, config: PGRGConfig) -> str:
    """Hint-biased lede summary over the retrieved chunks.

    Concatenates chunk contents and runs lede.summarize with query-derived
    hints. Returns "" when there are no chunks. Deterministic given the same
    (question, chunk set, config).
    """
    if not result.chunks:
        return ""
    from lede import summarize as lede_summarize

    text = "\n\n".join(c.content for c in result.chunks)
    hints = build_hints(question, config) or None
    return lede_summarize(
        text,
        max_length=config.summary_max_length,
        hints=hints,
        hint_focus=config.summary_hint_focus,
        hint_mode="soft",
    ).summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_summary_hints.py -v`
Expected: PASS (all tests). Requires lede>=0.4 and en_core_web_sm installed.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/summary.py tests/unit/test_summary_hints.py
git commit -m "feat: add query-derived hint pipeline for summary retrieval"
```

---

## Task 4: Aggressive-tier degradation without vector model (SC-005)

**Files:**
- Test: `tests/unit/test_summary_hints.py` (extend)
- (No source change — `_resolve_expansion_tier` from Task 3 already implements this.)

- [ ] **Step 1: Write the failing/regression test**

Append to `tests/unit/test_summary_hints.py`:

```python
def test_aggressive_degrades_to_moderate_without_vector_model(monkeypatch):
    monkeypatch.setattr(summary_mod, "_has_vector_model", lambda: False)
    with pytest.warns(UserWarning, match="falling back to 'moderate'"):
        resolved = summary_mod._resolve_expansion_tier("aggressive")
    assert resolved == "moderate"  # SC-005


def test_aggressive_kept_when_vector_model_present(monkeypatch):
    monkeypatch.setattr(summary_mod, "_has_vector_model", lambda: True)
    import warnings as _w

    with _w.catch_warnings():
        _w.simplefilter("error")  # any warning would raise
        assert summary_mod._resolve_expansion_tier("aggressive") == "aggressive"


def test_moderate_tier_never_warns(monkeypatch):
    monkeypatch.setattr(summary_mod, "_has_vector_model", lambda: False)
    import warnings as _w

    with _w.catch_warnings():
        _w.simplefilter("error")
        assert summary_mod._resolve_expansion_tier("moderate") == "moderate"
```

- [ ] **Step 2: Run tests to verify behavior**

Run: `uv run pytest tests/unit/test_summary_hints.py -k "tier or degrade or vector" -v`
Expected: PASS. If `test_aggressive_degrades...` fails, `_resolve_expansion_tier` is not emitting the warning or not degrading — fix in `summary.py`.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_summary_hints.py
git commit -m "test: cover aggressive-tier degradation without vector model"
```

---

## Task 5: Wire mode="summary" into retrieval (SC-001, SC-001b)

**Files:**
- Modify: `src/pg_raggraph/retrieval.py:28` (QueryMode), `:617` (valid_modes), `:621-653` (dispatch), and add `_summary_query` near `_smart_query`.
- Modify: `src/pg_raggraph/retrieval.py:594-610` (query signature — add `summary_base_mode` kwarg)
- Test: `tests/integration/test_summary_mode.py` (created here)

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_summary_mode.py`:

```python
"""Integration tests for mode='summary' (requires running Postgres on 5434)."""

from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.asyncio

CORPUS = [
    ("smith.txt", "John Smith lives in Cook County. He runs a small business and pays county taxes."),
    ("jones.txt", "Mary Jones lives in Lake County. She is a teacher and serves on the school board."),
    ("budget.txt", "The county council approved the annual budget. Cook County raised property taxes by two percent."),
]


@pytest.fixture
async def rag(tmp_namespace):
    g = await GraphRAG.connect()
    ns = tmp_namespace
    for src, text in CORPUS:
        await g.ingest(text, source_path=src, namespace=ns)
    g._test_ns = ns
    yield g
    await g.close()


async def test_summary_mode_returns_nonempty_summary_with_citations(rag):
    result = await rag.query(
        "What county does John Smith live in?",
        mode="summary",
        namespace=rag._test_ns,
    )
    assert result.query_mode == "summary"
    assert result.summary  # SC-001: non-empty summary
    assert result.chunks  # SC-001: chunks preserved
    assert all(c.document_source for c in result.chunks)  # source attribution


async def test_summary_base_mode_selects_substrate(rag):
    summ = await rag.query(
        "county taxes", mode="summary", summary_base_mode="naive", namespace=rag._test_ns
    )
    naive = await rag.query("county taxes", mode="naive", namespace=rag._test_ns)
    # SC-001b: summary substrate == the named base mode's chunk set
    assert [c.chunk_id for c in summ.chunks] == [c.chunk_id for c in naive.chunks]
```

> Note: `tmp_namespace` is the existing fixture in `tests/integration/conftest.py` used by other integration tests. If its name differs in this repo, match the local convention — grep `tests/integration/conftest.py` for the per-test namespace fixture.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_summary_mode.py -v`
Expected: FAIL — `ValueError: Invalid mode 'summary'` (mode not yet accepted).

- [ ] **Step 3: Add "summary" to QueryMode and valid_modes**

In `src/pg_raggraph/retrieval.py` line 28:

```python
QueryMode = Literal["local", "global", "hybrid", "naive", "naive_boost", "smart", "summary"]
```

And line 617:

```python
    valid_modes = ("naive", "local", "global", "hybrid", "naive_boost", "smart", "summary")
```

- [ ] **Step 4: Add `summary_base_mode` to the query() signature**

In `src/pg_raggraph/retrieval.py`, add a keyword-only param to `query()` — insert after `top_k_override: int | None = None,` (line 609):

```python
    top_k_override: int | None = None,
    summary_base_mode: str | None = None,
```

- [ ] **Step 5: Add the dispatch branch and `_summary_query`**

In `src/pg_raggraph/retrieval.py`, in `query()`, add a dispatch branch immediately before the `if mode == "smart":` block (line 622):

```python
    if mode == "summary":
        return await _summary_query(
            question,
            db,
            embedder,
            config,
            namespace,
            as_of=as_of,
            version_filter=version_filter,
            evolution_aware=evolution_aware,
            retracted_behavior=retracted_behavior,
            supersession_behavior=supersession_behavior,
            memory_tier=memory_tier,
            retrieval_strategy=retrieval_strategy,
            top_k_override=top_k_override,
            summary_base_mode=summary_base_mode,
        )
```

Then add the function definition immediately above `async def _smart_query(` (line 1062):

```python
async def _summary_query(
    question: str,
    db: Database,
    embedder: EmbeddingProvider,
    config: PGRGConfig,
    namespace: str | None = None,
    *,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
    retrieval_strategy: str | None = None,
    top_k_override: int | None = None,
    summary_base_mode: str | None = None,
) -> QueryResult:
    """Run an existing retrieval substrate, then summarize its chunks via lede.

    The substrate is config.summary_base_mode (default 'hybrid') unless the
    caller overrides it with summary_base_mode. Retrieval scoring is unchanged
    — this only adds a deterministic, LLM-free summary over the K chunks.
    """
    from pg_raggraph.summary import summarize_chunks

    start = time.perf_counter()
    base_mode = summary_base_mode or config.summary_base_mode
    base = await query(
        question=question,
        db=db,
        embedder=embedder,
        config=config,
        mode=base_mode,
        namespace=namespace,
        as_of=as_of,
        version_filter=version_filter,
        evolution_aware=evolution_aware,
        retracted_behavior=retracted_behavior,
        supersession_behavior=supersession_behavior,
        memory_tier=memory_tier,
        retrieval_strategy=retrieval_strategy,
        top_k_override=top_k_override,
    )
    base.summary = summarize_chunks(question, base, config)
    base.query_mode = "summary"
    base.latency_ms = (time.perf_counter() - start) * 1000
    return base
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_summary_mode.py -v`
Expected: PASS (2 tests). Requires Postgres on 5434 (`docker compose up -d postgres`) and lede>=0.4.

- [ ] **⛔ DC-001: Drift check**

Re-read `skill-output/mission-brief/Mission-Brief-lede-v0.4-hint-biased-summary-retrieval.md`. Confirm SC-001 through SC-005 have test evidence (Tasks 3-5). Specifically verify `build_hints` passes dict-coerced seeds to `expand_hints` so `expand_weight` applies, and `max_hints` is enforced. If misaligned, stop and reassess.

- [ ] **Step 7: Commit**

```bash
git add src/pg_raggraph/retrieval.py tests/integration/test_summary_mode.py
git commit -m "feat: add mode='summary' with configurable retrieval substrate"
```

---

## Task 6: GraphRAG.query passes summary_base_mode through (SC-001b)

**Files:**
- Modify: `src/pg_raggraph/__init__.py:1308-1398` (signature + call + docstring)

- [ ] **Step 1: Add the kwarg to GraphRAG.query signature**

In `src/pg_raggraph/__init__.py`, add a keyword-only param to `GraphRAG.query`. Insert after `retrieval_strategy: str | None = None,` (line 1320):

```python
        retrieval_strategy: str | None = None,
        summary_base_mode: str | None = None,
        rerank: bool = False,
```

- [ ] **Step 2: Thread it into the retrieval_query call**

In the same method, add to the `retrieval_query(...)` call args (after `retrieval_strategy=retrieval_strategy,`, around line 1396):

```python
                    retrieval_strategy=retrieval_strategy,
                    summary_base_mode=summary_base_mode,
                    top_k_override=top_k_override,
```

- [ ] **Step 3: Update the docstring mode list**

In the `GraphRAG.query` docstring, add to the Modes list (after the `hybrid` line, ~line 1331):

```python
            hybrid - local + global combined
            summary - run summary_base_mode substrate, then return a
                deterministic lede hint-biased summary in result.summary (no LLM)
```

- [ ] **Step 4: Verify the kwarg reaches retrieval**

Run: `uv run pytest tests/integration/test_summary_mode.py::test_summary_base_mode_selects_substrate -v`
Expected: PASS (this test calls `rag.query(..., summary_base_mode="naive")`, which only works once the kwarg is threaded through `GraphRAG.query`).

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/__init__.py
git commit -m "feat: expose summary_base_mode on GraphRAG.query"
```

---

## Task 7: Smart-mode tier-0 (SC-006)

**Files:**
- Modify: `src/pg_raggraph/retrieval.py:1166-1170` (the high-confidence branch in `_smart_query`)
- Test: `tests/integration/test_summary_mode.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_summary_mode.py`:

```python
async def test_smart_tier0_populates_summary_above_threshold(rag):
    rag.config.smart_summary_tier = True
    rag.config.summary_tier_threshold = 0.0  # force tier-0 on any high-confidence hit
    rag.config.boost_confidence_threshold = 0.0  # make naive top score "high"
    result = await rag.query(
        "What county does John Smith live in?",
        mode="smart",
        namespace=rag._test_ns,
    )
    assert result.query_mode == "smart[summary]"  # SC-006
    assert result.summary


async def test_smart_tier0_off_by_default(rag):
    result = await rag.query(
        "What county does John Smith live in?",
        mode="smart",
        namespace=rag._test_ns,
    )
    # Default config.smart_summary_tier is False — no summary path.
    assert result.query_mode != "smart[summary]"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_summary_mode.py -k tier0 -v`
Expected: FAIL — `test_smart_tier0_populates_summary_above_threshold` fails because `query_mode` is `smart[naive]`, not `smart[summary]`.

- [ ] **Step 3: Add the tier-0 branch**

In `src/pg_raggraph/retrieval.py`, replace the high-confidence branch in `_smart_query` (lines 1166-1170):

```python
    # High confidence — ship it
    if result.confidence == "high":
        result.query_mode = "smart[naive]"
        result.latency_ms = (time.perf_counter() - start) * 1000
        return result
```

with:

```python
    # High confidence — ship it. Optional tier-0: ship a deterministic lede
    # summary instead of raw chunks (no LLM) when the top score clears the
    # summary tier threshold and the feature is enabled.
    if result.confidence == "high":
        if config.smart_summary_tier and result.top_score >= config.summary_tier_threshold:
            from pg_raggraph.summary import summarize_chunks

            result.summary = summarize_chunks(question, result, config)
            result.query_mode = "smart[summary]"
        else:
            result.query_mode = "smart[naive]"
        result.latency_ms = (time.perf_counter() - start) * 1000
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_summary_mode.py -k tier0 -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/retrieval.py tests/integration/test_summary_mode.py
git commit -m "feat: add smart-mode tier-0 lede summary path"
```

---

## Task 8: answer.py — ship summary, replace fallback (SC-007, SC-006 LLM-skip)

**Files:**
- Modify: `src/pg_raggraph/answer.py:72-91` (`_fallback_answer`), `:94-140` (`generate_answer`)
- Test: `tests/unit/test_summary_answer.py` (created here)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_summary_answer.py`:

```python
"""Unit tests for generate_answer summary/fallback behavior (no DB)."""

from __future__ import annotations

import pytest

from pg_raggraph.answer import generate_answer
from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import ChunkResult, QueryResult

pytestmark = pytest.mark.asyncio


class _ExplodingLLM:
    """Asserts it is never called."""

    async def complete_text(self, messages):
        raise AssertionError("LLM must not be called when summary is present")

    async def complete(self, messages):
        raise AssertionError("LLM must not be called when summary is present")


async def test_populated_summary_skips_llm():
    result = QueryResult(
        summary="John Smith lives in Cook County.",
        chunks=[ChunkResult(content="John Smith lives in Cook County.", score=0.9)],
    )
    answer = await generate_answer("where?", result, _ExplodingLLM(), PGRGConfig())
    assert answer == "John Smith lives in Cook County."  # SC-006: zero LLM calls


async def test_no_llm_falls_back_to_lede_summary():
    result = QueryResult(
        chunks=[
            ChunkResult(content="John Smith lives in Cook County and pays county taxes.", score=0.8, document_source="smith.txt"),
            ChunkResult(content="The county council raised property taxes.", score=0.6, document_source="budget.txt"),
        ]
    )
    answer = await generate_answer("what county?", result, None, PGRGConfig())
    assert answer  # non-empty
    assert "INSUFFICIENT" not in answer
    assert "smith.txt" in answer  # SC-007: source attribution preserved


async def test_no_chunks_returns_not_found():
    answer = await generate_answer("q", QueryResult(), None, PGRGConfig())
    assert answer == "No relevant content found in the knowledge base."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_summary_answer.py -v`
Expected: FAIL — `test_populated_summary_skips_llm` fails (current code calls the LLM regardless of `result.summary`); `test_no_llm_falls_back_to_lede_summary` fails on the `smith.txt` assertion (old fallback only shows the top chunk + a config hint, and uses different wording).

- [ ] **Step 3: Rewrite `_fallback_answer`**

In `src/pg_raggraph/answer.py`, replace `_fallback_answer` (lines 72-91) with:

```python
def _fallback_answer(question: str, result: QueryResult, config: PGRGConfig) -> str:
    """Deterministic lede summary across all retrieved chunks (no LLM).

    Used when no LLM is configured or LLM synthesis fails. Returns a
    hint-biased summary plus source attribution. Falls back to a plain
    not-found message only when summarization yields nothing.
    """
    from pg_raggraph.summary import summarize_chunks

    summary = summarize_chunks(question, result, config)
    if not summary:
        return "No relevant content found in the knowledge base."
    sources = ", ".join(sorted({c.document_source or "unknown" for c in result.chunks}))
    return f"{summary}\n\n(Sources: {sources})"
```

- [ ] **Step 4: Update `generate_answer`**

In `src/pg_raggraph/answer.py`, change the body of `generate_answer`. Replace the early-guard block (lines 111-115):

```python
    if not result.chunks:
        return "No relevant content found in the knowledge base."

    if llm is None:
        return _fallback_answer(result)
```

with:

```python
    if not result.chunks:
        return "No relevant content found in the knowledge base."

    # mode="summary" / smart tier-0 already produced a deterministic summary —
    # ship it without an LLM round-trip.
    if result.summary:
        return result.summary

    if llm is None:
        return _fallback_answer(question, result, config)
```

And update the exception handler (line 138-140) to pass the new args:

```python
    except Exception as e:
        logger.warning(f"Answer generation failed: {e}")
        return _fallback_answer(question, result, config)
```

> Note on `short_answer`: the factoid path is unaffected — when `short_answer=True` and an LLM is present, behavior is unchanged. When `short_answer=True` and no LLM is configured, the lede summary fallback applies (best effort, not a factoid). This matches the brief (no factoid-fallback requirement).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_summary_answer.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Find and update any test asserting the old fallback wording**

Run: `grep -rn "No LLM configured for answer synthesis\|Set PGRG_LLM_BASE_URL" tests/`
For each hit, update the assertion to expect the new lede-summary fallback (non-empty summary + `(Sources: ...)`), or delete the stale assertion if it only checked the removed wording. Then:

Run: `uv run pytest tests/ -k "fallback or answer" -v`
Expected: PASS (no references to the removed wording remain).

- [ ] **⛔ DC-002: Drift check**

Re-read the mission brief. Confirm SC-001, SC-007, and SC-008 are progressing and that **no existing retrieval mode logic was changed** beyond adding the `summary` branch and the smart tier-0 branch. Verify you did not "improve" naive/local/global/hybrid scoring. If you touched them, revert that and reassess.

- [ ] **Step 7: Commit**

```bash
git add src/pg_raggraph/answer.py tests/unit/test_summary_answer.py
git commit -m "feat: ship summary without LLM; replace truncation fallback with lede summary"
```

---

## Task 9: CLI — add summary mode

**Files:**
- Modify: `src/pg_raggraph/cli.py:162`, `:207`, `:452` (the three `click.Choice` lists)

- [ ] **Step 1: Add "summary" to each --mode choice**

In `src/pg_raggraph/cli.py`, in all three `--mode` option definitions (query at line 162, ask at line 207, devmem at line 452), add `"summary"` to the choices:

```python
    type=click.Choice(["smart", "naive", "naive_boost", "local", "global", "hybrid", "summary"]),
```

- [ ] **Step 2: Verify the CLI accepts the mode**

Run: `uv run pgrg query --help`
Expected: help text lists `summary` among the `--mode` choices (Click renders the Choice set).

- [ ] **Step 3: Commit**

```bash
git add src/pg_raggraph/cli.py
git commit -m "feat: expose --mode summary in the CLI"
```

---

## Task 10: Determinism + E2E coverage (SC-004, SC-009)

**Files:**
- Test: `tests/integration/test_summary_mode.py` (extend)
- Test: `tests/test_e2e.py` (extend)

- [ ] **Step 1: Write the determinism test (SC-004)**

Append to `tests/integration/test_summary_mode.py`:

```python
async def test_summary_is_deterministic_across_runs(rag):
    q = "What county does John Smith live in?"
    r1 = await rag.query(q, mode="summary", namespace=rag._test_ns)
    r2 = await rag.query(q, mode="summary", namespace=rag._test_ns)
    assert r1.summary == r2.summary  # SC-004: byte-identical across runs


async def test_summary_with_expansion_off_is_deterministic(rag):
    rag.config.query_expansion = "off"
    q = "county taxes"
    r1 = await rag.query(q, mode="summary", namespace=rag._test_ns)
    r2 = await rag.query(q, mode="summary", namespace=rag._test_ns)
    assert r1.summary == r2.summary  # SC-004: no-expansion path is stable
    assert r1.summary
```

- [ ] **Step 2: Add E2E coverage (SC-009)**

Open `tests/test_e2e.py` and locate the existing cumulative test that ingests then queries (grep for `mode=` to find the query section). Add the following assertions to the query phase, using the same `rag`/namespace already set up in that test (adapt variable names to the local test):

```python
    # --- mode="summary": deterministic LLM-free summary over retrieved chunks ---
    summ = await rag.query("What county does John Smith live in?", mode="summary")
    assert summ.query_mode == "summary"
    assert summ.summary  # SC-009: non-empty summary
    assert summ.chunks and all(c.document_source for c in summ.chunks)

    # --- smart tier-0: ship summary without LLM when confidence is high ---
    rag.config.smart_summary_tier = True
    rag.config.summary_tier_threshold = 0.0
    rag.config.boost_confidence_threshold = 0.0
    tier0 = await rag.query("What county does John Smith live in?", mode="smart")
    assert tier0.query_mode == "smart[summary]"  # SC-009
    assert tier0.summary
    rag.config.smart_summary_tier = False  # restore for any later assertions
```

> If `tests/test_e2e.py` does not already ingest a corpus mentioning a county/person, add one document in its ingest phase: `await rag.ingest("John Smith lives in Cook County and pays county taxes.", source_path="smith.txt")` before the query phase.

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/integration/test_summary_mode.py tests/test_e2e.py -v`
Expected: PASS (all summary/tier0 assertions green). Requires Postgres on 5434 + lede>=0.4.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_summary_mode.py tests/test_e2e.py
git commit -m "test: determinism + E2E coverage for summary retrieval"
```

---

## Task 11: Latency budget + benchmark sweep + full gate (SC-008, SC-010)

**Files:**
- Test: `tests/integration/test_summary_mode.py` (extend — latency)
- Modify: `benchmarks/e2e/config.py` (add "summary" to the modes list)

- [ ] **Step 1: Write the latency test (SC-010)**

Append to `tests/integration/test_summary_mode.py`:

```python
import time as _time


async def test_summary_mode_latency_budget(rag):
    q = "What county does John Smith live in?"
    await rag.query(q, mode="summary", namespace=rag._test_ns)  # warm caches
    start = _time.perf_counter()
    await rag.query(q, mode="summary", namespace=rag._test_ns)
    elapsed_ms = (_time.perf_counter() - start) * 1000
    # SC-010: loose budget on the dev machine; not a hard prod SLA.
    assert elapsed_ms < 250, f"summary mode took {elapsed_ms:.0f}ms (budget 250ms)"
```

- [ ] **Step 2: Run the latency test**

Run: `uv run pytest tests/integration/test_summary_mode.py::test_summary_mode_latency_budget -v`
Expected: PASS. If it fails by a small margin on a loaded machine, re-run once; if it fails consistently, record the observed number — the budget is documented, not a hard gate (note it in the commit message rather than loosening silently).

- [ ] **Step 3: Add "summary" to the benchmark sweep**

Open `benchmarks/e2e/config.py` and find the list of retrieval modes the harness sweeps (the 7-mode list referenced in the e2e harness). Add `"summary"` to that list following the existing format. Then confirm `benchmarks/e2e/run.py` passes the mode straight through to `rag.query(question, mode=mode)` (it already does for the other modes — no special-casing needed; the summary lives in `result.summary`, and the harness's answer extraction should read `result.answer or result.summary`).

If `run.py` reads only `result.answer`, add a one-line coalesce where it extracts the answer text:

```python
    answer_text = result.answer or result.summary
```

- [ ] **Step 4: Smoke-run the harness for the new mode only**

Run: `uv run python -m benchmarks.e2e.run --modes summary --limit 5` (use the harness's actual flag for mode/limit selection; check `benchmarks/e2e/run.py --help` or its `argparse`/`click` setup if the flags differ).
Expected: completes without error and reports metrics for the `summary` mode over 5 questions.

- [ ] **⛔ DC-003: Drift check**

Re-read the mission brief. Confirm SC-006 (smart tier-0 makes zero LLM calls — verified by `test_populated_summary_skips_llm`) and that smart mode's existing routing thresholds (naive/naive_boost/local/global) are unchanged. If you altered any existing threshold, revert and reassess.

- [ ] **Step 5: Full test-suite gate (SC-008)**

Run: `uv run pytest tests/ -v`
Expected: PASS — all pre-existing mode tests green (SC-008), all new tests green. If any pre-existing test changed behavior unexpectedly, that's drift — investigate before proceeding.

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_summary_mode.py benchmarks/e2e/config.py benchmarks/e2e/run.py
git commit -m "test: summary-mode latency budget + add summary to benchmark sweep"
```

- [ ] **⛔ DC-FINAL: Completion drift check**

Re-read the mission brief one final time. For each SC, confirm evidence:
- **SC-001 / SC-001b** → `test_summary_mode_returns_nonempty_summary_with_citations`, `test_summary_base_mode_selects_substrate`
- **SC-002** → `test_seed_weights_are_deterministic...`, `test_build_hints_deterministic`
- **SC-003** → `test_build_hints_respects_max_hints_cap`
- **SC-004** → `test_summary_is_deterministic_across_runs`, `test_summary_with_expansion_off_is_deterministic`
- **SC-005** → `test_aggressive_degrades_to_moderate_without_vector_model`
- **SC-006** → `test_populated_summary_skips_llm`, `test_smart_tier0_populates_summary_above_threshold`
- **SC-007** → `test_no_llm_falls_back_to_lede_summary` + removed truncation fallback
- **SC-008** → full `uv run pytest tests/` green
- **SC-009** → `tests/test_e2e.py` summary + tier-0 assertions
- **SC-010** → `test_summary_mode_latency_budget`

Confirm NEVER constraints hold: lede-spacy still optional (expansion degrades to raw seeds when absent — `build_hints` ModuleNotFoundError path), no new mandatory deps, no schema/migration changes, byte-identical behavior for existing modes with `hints=None`. Confirm `lede>=0.4` is pinned in `pyproject.toml` and `uv sync` resolves. If any SC lacks evidence, the work is not complete.

---

## Self-Review Notes

- **Spec coverage:** SC-001 through SC-010 each map to a named test in Task 11's DC-FINAL list. All Constraints (lede pin, optional lede-spacy, no schema change, byte-identical existing modes) are enforced by Tasks 1, 3, 8, and the DC-FINAL check.
- **Type consistency:** `build_hints` / `_resolve_expansion_tier` / `_seed_weights` / `_has_vector_model` / `summarize_chunks` signatures are defined in Task 3 and used unchanged in Tasks 5, 7, 8. `_fallback_answer(question, result, config)` is defined and called consistently in Task 8. `summary_base_mode` kwarg flows: CLI/`GraphRAG.query` (Task 6) → `retrieval.query` (Task 5) → `_summary_query` (Task 5).
- **Known external dependency:** every test that exercises hints/summarization requires lede>=0.4 + `en_core_web_sm` (installed); integration tests also require Postgres on 5434.
- **API verified against lede 0.4.1 (2026-05-22):** `lede.summarize(...).summary`, `lede.extract.top_terms(text, n=)` → tuple, and `lede_spacy.expand_hints(hints, kinds=, top_k=, expand_weight=)` dict-in/dict-out all confirmed live. No kwarg drift from the integration doc.
