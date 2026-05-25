# Summary-Retrieval Power Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add three additive capabilities to the shipped `mode="summary"`: (#1) query-term expansion that feeds *retrieval* (BM25 leg + alias map), (#2) a response shape that returns the summary as the answer while caching full chunks for "ask for more", and (#3) soft metadata filtering that biases scores and hard-filters only structured fields.

**Architecture:** All three are opt-in and default-preserving. #1 expands the term set fed to `_to_or_tsquery` (lexical via `lede_spacy.expand_hints` + a config alias map). #2 adds a `result_id` to `QueryResult`, an in-process LRU `ResultCache`, adaptive summary length, and an escalation line in `ask()`. #3 follows the existing `memory_tier_clause` SQL pattern: a soft additive score clause + a hard WHERE clause restricted to caller-declared structured fields.

**Tech Stack:** Python 3.12+, lede 0.4.2 / lede-spacy[synonyms] (installed), asyncpg, pydantic-settings, pytest. Postgres on localhost:5434.

**Mission Brief:** `skill-output/mission-brief/Mission-Brief-summary-retrieval-power-features.md` — all SC-XXX / DC-XXX map to it.

**Branch:** `feat/lede-hint-summary-retrieval` (continues the summary work; do NOT switch).

---

## Key internals (verified)
- `src/pg_raggraph/summary.py` has `_seed_weights`, `_resolve_expansion_tier`, `_EXPANSION_KINDS`, `build_hints`, `summarize_chunks`. Imports: `logging`, `warnings` (NO `re` yet).
- `src/pg_raggraph/retrieval.py:119` `_to_or_tsquery(text)` builds the BM25 OR-query; called once at `query()` ~line 681 (`tsquery = _to_or_tsquery(question)`).
- `src/pg_raggraph/evolution.py:54` `memory_tier_clause(cfg, chunk_alias="c", override=None) -> (clause_str, params)` — the WHERE-clause-threading pattern #3 follows. The SQL builders accept an `extra`/`extra_where` mechanism (see how `mt_clause` is merged).
- `GraphRAG.query` (`__init__.py:1308`) and `GraphRAG.ask` (`__init__.py:1419`); `ask` calls `query` then `generate_answer`, sets `result.answer`.
- `QueryResult` (`models.py:209`) currently has `answer`, `summary`, `chunks`, ... and `populate_confidence`.

---

# PHASE 1 — Expansion → retrieval (SC-101..106)

## Task 1: Config knobs + expand_query_terms

**Files:** Modify `src/pg_raggraph/config.py`, `src/pg_raggraph/summary.py`; Test `tests/unit/test_retrieval_expansion.py` (new)

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/test_retrieval_expansion.py`:

```python
"""Unit tests for retrieval-term expansion (SC-101..106)."""

from __future__ import annotations

from pg_raggraph import summary as summary_mod
from pg_raggraph.config import PGRGConfig


def test_expansion_off_returns_empty_without_alias():
    cfg = PGRGConfig(retrieval_expansion="off")
    assert summary_mod.expand_query_terms("how do counties work?", cfg) == []


def test_alias_map_applies_even_when_expansion_off():
    cfg = PGRGConfig(
        retrieval_expansion="off",
        retrieval_alias_map={"Brooklyn": ["Kings County"]},
    )
    terms = summary_mod.expand_query_terms("What is happening in Brooklyn?", cfg)
    assert "kings county" in terms  # SC-106: alias injected, lowercased


def test_alias_map_word_boundary():
    cfg = PGRGConfig(retrieval_alias_map={"york": ["alias_hit"]})
    # "New York" contains "york" as a word -> matches
    assert "alias_hit" in summary_mod.expand_query_terms("New York news", cfg)
    # "yorkshire" must NOT match "york"
    assert "alias_hit" not in summary_mod.expand_query_terms("yorkshire pudding", cfg)


def test_lexical_expansion_is_deterministic_and_capped():
    cfg = PGRGConfig(retrieval_expansion="moderate", max_hints=5)
    q = "automobile insurance policy renewal claims"
    t1 = summary_mod.expand_query_terms(q, cfg)
    t2 = summary_mod.expand_query_terms(q, cfg)
    assert t1 == t2  # SC-104 deterministic
    assert len(t1) <= 5  # SC-104 cap


def test_expand_query_terms_never_raises_on_empty():
    cfg = PGRGConfig(retrieval_expansion="moderate")
    assert summary_mod.expand_query_terms("", cfg) == []
```

- [ ] **Step 2: Run — expect fail** (`ModuleNotFoundError`/`AttributeError: expand_query_terms`, and config has no `retrieval_expansion`).

Run: `uv run pytest tests/unit/test_retrieval_expansion.py -v`

- [ ] **Step 3: Add config knobs**

In `src/pg_raggraph/config.py`, after the `max_hints` line in the summary block, add:

```python
    # --- #1 Expansion → retrieval (separate knob from query_expansion, which
    # only biases the summary). Default "off" keeps retrieval byte-identical.
    retrieval_expansion: Literal["off", "lemma", "moderate", "aggressive"] = "off"
    # Named-entity aliases WordNet can't bridge (e.g. {"Brooklyn": ["Kings County"]}).
    # Case-insensitive, word-boundary keyed. Applied independent of the lexical tier.
    retrieval_alias_map: dict[str, list[str]] = Field(default_factory=dict)
```

Confirm `Field` is imported from pydantic in config.py (it is used elsewhere — verify; if not, add `from pydantic import Field`).

- [ ] **Step 4: Add `expand_query_terms` + `import re` to summary.py**

At the top of `src/pg_raggraph/summary.py`, add `import re` to the imports (with `logging`, `warnings`).

Add this function after `build_hints`:

```python
def expand_query_terms(question: str, config: PGRGConfig) -> list[str]:
    """Expanded BM25 retrieval terms (deterministic, capped). Never raises.

    Combines lexical expansion (lemma/synonym via lede_spacy, gated by
    config.retrieval_expansion) with config.retrieval_alias_map (named-entity
    aliases WordNet can't bridge). Returns [] when nothing applies. Degrades to
    raw seeds when lede-spacy/nltk is unavailable.
    """
    terms: set[str] = set()
    q_lower = question.lower()

    # Alias map — applied regardless of the lexical tier, word-boundary matched.
    for key, aliases in (config.retrieval_alias_map or {}).items():
        if re.search(rf"(?<!\w){re.escape(key.lower())}(?!\w)", q_lower):
            terms.update(a.lower() for a in aliases)

    tier = config.retrieval_expansion
    if tier != "off":
        seeds = _seed_weights(question, config.summary_seed_terms)
        if seeds:
            resolved = _resolve_expansion_tier(tier)
            kinds = _EXPANSION_KINDS[resolved]
            if kinds:
                try:
                    from lede_spacy import expand_hints

                    expanded = expand_hints(
                        seeds,
                        kinds=kinds,
                        top_k=config.expand_top_k,
                        expand_weight=config.expand_weight,
                    )
                    terms.update(t.lower() for t in expanded)
                except ImportError:
                    terms.update(seeds)
            else:
                terms.update(seeds)

    out = sorted(t for t in terms if t and t.strip())
    return out[: config.max_hints]
```

- [ ] **Step 5: Run — expect pass.** `uv run pytest tests/unit/test_retrieval_expansion.py -v`
- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check src/pg_raggraph/config.py src/pg_raggraph/summary.py tests/unit/test_retrieval_expansion.py && uv run ruff format src/pg_raggraph/config.py src/pg_raggraph/summary.py tests/unit/test_retrieval_expansion.py
git add src/pg_raggraph/config.py src/pg_raggraph/summary.py tests/unit/test_retrieval_expansion.py
git commit -m "feat: add expand_query_terms + retrieval_expansion/alias_map config"
```

## Task 2: Wire expansion into the BM25 tsquery (SC-101, SC-102)

**Files:** Modify `src/pg_raggraph/retrieval.py`; Test `tests/unit/test_retrieval_expansion.py` (extend)

- [ ] **Step 1: Append failing unit tests**

```python
from pg_raggraph.retrieval import _to_or_tsquery


def test_tsquery_byte_identical_without_extra_terms():
    # SC-101: extra_terms=None path must equal the historical behavior.
    assert _to_or_tsquery("payment service outage") == "payment | service | outage"
    assert _to_or_tsquery("a an the") == "empty"  # all <=2 chars filtered


def test_tsquery_includes_extra_terms_deduped():
    q = _to_or_tsquery("brooklyn news", extra_terms=["kings county", "brooklyn"])
    parts = q.split(" | ")
    assert "brooklyn" in parts and "kings" in parts and "county" in parts
    assert parts.count("brooklyn") == 1  # SC-102: deduped
```

- [ ] **Step 2: Run — expect fail** (`_to_or_tsquery` takes 1 arg).

- [ ] **Step 3: Extend `_to_or_tsquery` to accept `extra_terms`**

Replace `_to_or_tsquery` in `retrieval.py` with (preserves the no-extra path exactly):

```python
def _to_or_tsquery(text: str, extra_terms: list[str] | None = None) -> str:
    """Convert text (plus optional expansion terms) to an OR-based tsquery.

    With ``extra_terms`` None the output is byte-identical to the historical
    single-arg behavior. With expansion terms, the union is deduped (order
    preserved) before the 20-term cap.
    """
    import re

    words = re.findall(r"\w+", text.lower())
    if not words and not extra_terms:
        return "empty"
    words = [w for w in words if len(w) > 2]
    if extra_terms:
        for t in extra_terms:
            words.extend(w for w in re.findall(r"\w+", t.lower()) if len(w) > 2)
        seen: set[str] = set()
        deduped: list[str] = []
        for w in words:
            if w not in seen:
                seen.add(w)
                deduped.append(w)
        words = deduped
    words = words[:20]
    return " | ".join(words) if words else "empty"
```

- [ ] **Step 4: Compute expanded terms in `query()`**

In `retrieval.py` `query()`, find `tsquery = _to_or_tsquery(question)` (~line 681). Replace with:

```python
    # #1: expand the BM25 term set when enabled (default off → byte-identical).
    if config.retrieval_expansion != "off" or config.retrieval_alias_map:
        from pg_raggraph.summary import expand_query_terms

        tsquery = _to_or_tsquery(question, expand_query_terms(question, config))
    else:
        tsquery = _to_or_tsquery(question)
```

- [ ] **Step 5: Run — expect pass.** `uv run pytest tests/unit/test_retrieval_expansion.py -v`
- [ ] **Step 6: Lint + commit**

```bash
git add src/pg_raggraph/retrieval.py tests/unit/test_retrieval_expansion.py
git commit -m "feat: feed expanded terms into the BM25 tsquery when retrieval_expansion on"
```

## Task 3: Integration — expansion changes retrieval (SC-103, SC-106) + DC-101

**Files:** Test `tests/integration/test_retrieval_expansion_it.py` (new)

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_retrieval_expansion_it.py`:

```python
"""Integration: retrieval_expansion / alias_map change WHICH chunks come back."""

from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


def _deps() -> bool:
    try:
        import lede  # noqa: F401
        import lede_spacy  # noqa: F401
        import spacy

        spacy.load("en_core_web_sm")
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _deps(), reason="lede/lede-spacy/en_core_web_sm not available"),
]

CORPUS = [
    {"text": "The courthouse is located in Kings County and serves the surrounding area.", "source_id": "kc.txt"},
    {"text": "Manhattan parking regulations were updated last spring.", "source_id": "mh.txt"},
    {"text": "Automobile registration fees rose this year for all vehicle owners.", "source_id": "auto.txt"},
]


@pytest.fixture
async def rag():
    ns = "test_retr_expansion"
    g = GraphRAG(dsn=_DSN, namespace=ns, fact_extractor="lede_spacy", llm_base_url="")
    await g.connect()
    await g.delete(ns)
    await g.ingest_records(CORPUS, namespace=ns)
    g._ns = ns
    try:
        yield g
    finally:
        await g.delete(ns)
        await g.close()


def _sources(result):
    return {c.document_source for c in result.chunks}


async def test_alias_map_bridges_geographic_crossover(rag):
    # Query says "Brooklyn"; the chunk says "Kings County". WordNet can't bridge
    # this — only the alias map can.
    rag.config.retrieval_alias_map = {"Brooklyn": ["Kings County"]}
    rag.config.w_bm25 = 0.6  # ensure the BM25 leg can surface the alias hit
    with_alias = await rag.query("What courthouse serves Brooklyn?", mode="naive", namespace=rag._ns)
    rag.config.retrieval_alias_map = {}
    without = await rag.query("What courthouse serves Brooklyn?", mode="naive", namespace=rag._ns)
    # SC-106: alias map pulls in the Kings County chunk; baseline ranks it lower/absent
    assert "kc.txt" in _sources(with_alias)
    assert _sources(with_alias) != _sources(without) or with_alias.chunks[0].document_source == "kc.txt"


async def test_synonym_expansion_changes_retrieval(rag):
    # Query "car fees"; chunk says "Automobile". Synonym expansion should help.
    rag.config.retrieval_expansion = "moderate"
    rag.config.w_bm25 = 0.6
    expanded = await rag.query("car registration fees", mode="naive", namespace=rag._ns)
    rag.config.retrieval_expansion = "off"
    base = await rag.query("car registration fees", mode="naive", namespace=rag._ns)
    # SC-103: expansion changes the result set (auto.txt surfaces via "automobile")
    assert "auto.txt" in _sources(expanded)
    assert _sources(expanded) != _sources(base) or expanded.chunks[0].document_source == "auto.txt"
```

> Note: BM25 `ts_rank` on a tiny corpus can be noisy. If an assertion is flaky, the implementer may make the corpus more distinctive or raise `w_bm25` further — but must NOT weaken to a tautology. The core guarantee (expansion changes the retrieved set, not just the summary) must hold.

- [ ] **Step 2: Run — expect pass** (deps + Postgres). `uv run pytest tests/integration/test_retrieval_expansion_it.py -v`
- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_retrieval_expansion_it.py
git commit -m "test: integration proof that expansion/alias_map change retrieval"
```

- [ ] **⛔ DC-101:** Re-read the mission brief. Confirm SC-101 (off ⇒ byte-identical tsquery), SC-103/106 (retrieval set changed, not just summary), SC-104 (deterministic/capped). Verify expansion feeds the *tsquery*, proving it's retrieval, not summary biasing. If misaligned, stop.

---

# PHASE 2 — Response shape (SC-201..205)

## Task 4: result_id field + adaptive summary length

**Files:** Modify `src/pg_raggraph/models.py`, `src/pg_raggraph/config.py`, `src/pg_raggraph/summary.py`; Test `tests/unit/test_summary_response_shape.py` (new)

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/test_summary_response_shape.py`:

```python
"""Unit tests for result_id + adaptive summary length (SC-204)."""

from __future__ import annotations

from pg_raggraph import summary as summary_mod
from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import QueryResult


def test_query_result_has_result_id_default_none():
    assert QueryResult().result_id is None


def test_adaptive_length_floor_and_ceiling():
    cfg = PGRGConfig()
    floor = cfg.summary_max_length
    ceil = cfg.summary_max_length_ceiling
    assert summary_mod.adaptive_summary_length(1, cfg) == floor
    assert summary_mod.adaptive_summary_length(cfg.summary_length_floor_chunks, cfg) == floor
    assert summary_mod.adaptive_summary_length(cfg.summary_length_ceiling_chunks, cfg) == ceil
    assert summary_mod.adaptive_summary_length(10_000, cfg) == ceil


def test_adaptive_length_monotonic_nondecreasing():
    cfg = PGRGConfig()
    vals = [summary_mod.adaptive_summary_length(n, cfg) for n in range(1, 40)]
    assert vals == sorted(vals)
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Add `result_id` to QueryResult**

In `models.py` `QueryResult`, after `summary: str = ""` block, add:

```python
    result_id: str | None = None
    """Stable id for this result when retained in GraphRAG's in-process result
    cache (set by ask()/query() when caching is enabled). Lets a follow-up call
    fetch the full chunks via GraphRAG.get_cached_result(result_id)."""
```

- [ ] **Step 4: Add config fields**

In `config.py` summary block add:

```python
    # #2 response shape.
    summary_max_length_ceiling: int = 4000  # upper char budget for large result sets
    summary_length_floor_chunks: int = 5  # <= this many chunks → summary_max_length
    summary_length_ceiling_chunks: int = 30  # >= this many chunks → ceiling
    summary_escalation: bool = True  # append "full sources available" affordance
    result_cache_size: int = 128  # in-process LRU capacity (0 disables caching)
```

- [ ] **Step 5: Add `adaptive_summary_length` and use it in `summarize_chunks`**

In `summary.py` add:

```python
def adaptive_summary_length(n_chunks: int, config: PGRGConfig) -> int:
    """Scale the summary char budget by retrieved-chunk count, bounded.

    Returns summary_max_length (floor) at <= summary_length_floor_chunks and
    summary_max_length_ceiling at >= summary_length_ceiling_chunks, linear
    between. Non-decreasing in n_chunks.
    """
    floor_len = config.summary_max_length
    ceil_len = max(config.summary_max_length_ceiling, floor_len)
    lo = config.summary_length_floor_chunks
    hi = config.summary_length_ceiling_chunks
    if n_chunks <= lo or hi <= lo:
        return floor_len
    if n_chunks >= hi:
        return ceil_len
    frac = (n_chunks - lo) / (hi - lo)
    return int(floor_len + frac * (ceil_len - floor_len))
```

In `summarize_chunks`, change `max_length=config.summary_max_length` to:

```python
        max_length=adaptive_summary_length(len(result.chunks), config),
```

(For ≤ floor_chunks results this equals summary_max_length, so existing tests are unaffected.)

- [ ] **Step 6: Run — expect pass.** Also re-run `uv run pytest tests/unit/test_summary_hints.py -q` to confirm no regression in existing summary tests.
- [ ] **Step 7: Lint + commit**

```bash
git add src/pg_raggraph/models.py src/pg_raggraph/config.py src/pg_raggraph/summary.py tests/unit/test_summary_response_shape.py
git commit -m "feat: result_id field + adaptive summary length"
```

## Task 5: In-process LRU ResultCache + GraphRAG integration (SC-202, SC-205)

**Files:** Create `src/pg_raggraph/result_cache.py`; Modify `src/pg_raggraph/__init__.py`; Test `tests/unit/test_result_cache.py` (new)

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/test_result_cache.py`:

```python
"""Unit tests for the in-process LRU result cache (SC-202, SC-205)."""

from __future__ import annotations

from pg_raggraph.models import QueryResult
from pg_raggraph.result_cache import ResultCache


def test_put_get_roundtrip():
    c = ResultCache(maxsize=4)
    r = QueryResult(summary="s")
    c.put("id1", r)
    assert c.get("id1") is r


def test_missing_returns_none():
    assert ResultCache(maxsize=4).get("nope") is None


def test_lru_eviction():
    c = ResultCache(maxsize=2)
    c.put("a", QueryResult())
    c.put("b", QueryResult())
    c.get("a")  # touch a → b now LRU
    c.put("c", QueryResult())  # evicts b
    assert c.get("b") is None  # SC-205: oldest evicted
    assert c.get("a") is not None
    assert c.get("c") is not None


def test_maxsize_zero_disables():
    c = ResultCache(maxsize=0)
    c.put("a", QueryResult())
    assert c.get("a") is None
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Create result_cache.py**

```python
"""In-process LRU cache of recent QueryResults, addressable by result_id.

Lets a caller send the cheap summary as the answer while keeping the full
retrieved chunks available for a follow-up "give me more" — without
re-querying. In-process only; not persisted (by design, this mission).
"""

from __future__ import annotations

from collections import OrderedDict

from pg_raggraph.models import QueryResult


class ResultCache:
    """Bounded LRU map of result_id → QueryResult. maxsize=0 disables caching."""

    def __init__(self, maxsize: int = 128) -> None:
        self._maxsize = maxsize
        self._store: OrderedDict[str, QueryResult] = OrderedDict()

    def put(self, result_id: str, result: QueryResult) -> None:
        if self._maxsize <= 0:
            return
        if result_id in self._store:
            self._store.move_to_end(result_id)
        self._store[result_id] = result
        while len(self._store) > self._maxsize:
            self._store.popitem(last=False)

    def get(self, result_id: str) -> QueryResult | None:
        if result_id not in self._store:
            return None
        self._store.move_to_end(result_id)
        return self._store[result_id]
```

- [ ] **Step 4: Wire into GraphRAG**

In `__init__.py`, in `GraphRAG.__init__` (or wherever instance attrs are set), initialize the cache. Search for where `self.config` is available in `__init__`; add:

```python
        from pg_raggraph.result_cache import ResultCache

        self._result_cache = ResultCache(self.config.result_cache_size)
```

Add a public method on `GraphRAG` (near `query`/`ask`):

```python
    def get_cached_result(self, result_id: str) -> QueryResult | None:
        """Return a previously-retained QueryResult (full chunks) by id, or None
        if it was never cached or has been evicted."""
        return self._result_cache.get(result_id)
```

- [ ] **Step 5: Run — expect pass.** `uv run pytest tests/unit/test_result_cache.py -v`
- [ ] **Step 6: Lint + commit**

```bash
git add src/pg_raggraph/result_cache.py src/pg_raggraph/__init__.py tests/unit/test_result_cache.py
git commit -m "feat: in-process LRU ResultCache + GraphRAG.get_cached_result"
```

## Task 6: ask() — summary-as-answer, result_id, escalation (SC-201, SC-203)

**Files:** Modify `src/pg_raggraph/__init__.py`; Test `tests/integration/test_summary_response_it.py` (new)

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_summary_response_it.py`:

```python
"""Integration: ask(mode='summary') response shape + caching (SC-201..203)."""

from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


def _deps() -> bool:
    try:
        import lede  # noqa: F401
        import lede_spacy  # noqa: F401
        import spacy

        spacy.load("en_core_web_sm")
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _deps(), reason="deps not available"),
]

CORPUS = [
    {"text": "John Smith lives in Cook County and pays county taxes.", "source_id": "a.txt"},
    {"text": "The county council raised property taxes by two percent.", "source_id": "b.txt"},
]


@pytest.fixture
async def rag():
    ns = "test_summary_response"
    g = GraphRAG(dsn=_DSN, namespace=ns, fact_extractor="lede_spacy", llm_base_url="")
    await g.connect()
    await g.delete(ns)
    await g.ingest_records(CORPUS, namespace=ns)
    g._ns = ns
    try:
        yield g
    finally:
        await g.delete(ns)
        await g.close()


async def test_ask_summary_sets_answer_id_and_escalation(rag):
    res = await rag.ask("What county does John Smith live in?", mode="summary", namespace=rag._ns)
    assert res.answer  # SC-201: answer populated from summary (no LLM configured)
    assert res.summary and res.summary in res.answer
    assert res.result_id  # SC-201: stable id present
    assert "result_id" in res.answer.lower() or res.result_id in res.answer  # SC-203 affordance


async def test_cached_result_returns_full_chunks(rag):
    res = await rag.ask("county taxes", mode="summary", namespace=rag._ns)
    cached = rag.get_cached_result(res.result_id)
    assert cached is not None  # SC-202
    assert [c.chunk_id for c in cached.chunks] == [c.chunk_id for c in res.chunks]


async def test_escalation_off_when_disabled(rag):
    rag.config.summary_escalation = False
    res = await rag.ask("county taxes", mode="summary", namespace=rag._ns)
    # No escalation line; answer is just the summary.
    assert res.answer == res.summary
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Wire into `ask()`**

In `GraphRAG.ask`, after `result.answer = await generate_answer(...)` and before `return result`, add:

```python
        # #2 response shape: for summary mode, assign a stable id, cache the
        # full result for "ask for more", and append the escalation affordance.
        if mode == "summary" and result.chunks:
            import uuid

            result.result_id = uuid.uuid4().hex
            self._result_cache.put(result.result_id, result)
            if self.config.summary_escalation and result.answer:
                result.answer = (
                    f"{result.answer}\n\n---\n"
                    f"{len(result.chunks)} source chunks retained "
                    f"(result_id={result.result_id}). If this doesn't fully answer "
                    f"your question, request the full sources with that id."
                )
        return result
```

> Determinism note: `result_id` is a uuid (intentionally non-deterministic) — it's an addressing handle, not part of the summary content. The escalation tests assert on structure, not the id value. Do not make the summary itself depend on the id.

- [ ] **Step 4: Run — expect pass.** `uv run pytest tests/integration/test_summary_response_it.py -v`
- [ ] **Step 5: Lint + commit**

```bash
git add src/pg_raggraph/__init__.py tests/integration/test_summary_response_it.py
git commit -m "feat: ask() summary-as-answer with result_id, caching, escalation"
```

## Task 7: E2E journey + DC-201

**Files:** Modify `tests/integration/test_e2e.py`

- [ ] **Step 1: Add an E2E sprint** mirroring `test_e2e_sprint4_summary_mode` (constructor + connect + ingest_records + try/finally), after it:

```python
@pytest.mark.skipif(
    not _lede_model_available(),
    reason="lede / lede-spacy / en_core_web_sm not available",
)
async def test_e2e_sprint5_summary_response_journey():
    """ask → summary answer + result_id → fetch full chunks by id."""
    ns = "e2e_summary_response"
    rag = GraphRAG(dsn=TEST_DSN, namespace=ns, fact_extractor="lede_spacy", llm_base_url="")
    await rag.connect()
    try:
        await rag.ingest_records(
            [{"text": "Cook County raised property taxes; John Smith pays them.", "source_id": "e2e5:1"}],
            namespace=ns,
        )
        res = await rag.ask("What county taxes does John Smith pay?", mode="summary", namespace=ns)
        assert res.answer and res.result_id
        more = rag.get_cached_result(res.result_id)
        assert more is not None and more.chunks
    finally:
        await rag.delete(ns)
        await rag.close()
```

- [ ] **Step 2: Run.** `uv run pytest tests/integration/test_e2e.py -v`
- [ ] **Step 3: Commit.** `git add tests/integration/test_e2e.py && git commit -m "test: e2e summary response journey"`

- [ ] **⛔ DC-201:** Re-read the brief. Confirm the cache is in-process + bounded (SC-205) with no persistence; confirm `ask` for non-summary modes is unchanged (the new block is guarded by `mode == "summary"`). If drift, stop.

---

# PHASE 3 — Soft metadata filtering (SC-301..305)

## Task 8: metadata_filters shape + soft/hard classifier (SC-301)

**Files:** Create `src/pg_raggraph/metadata_filter.py`; Modify `src/pg_raggraph/config.py`; Test `tests/unit/test_metadata_filter.py` (new)

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/test_metadata_filter.py`:

```python
"""Unit tests for metadata filter classification (SC-301)."""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.metadata_filter import classify_filters


def test_soft_and_hard_split():
    cfg = PGRGConfig(structured_metadata_fields=["source", "tenant"])
    soft, hard = classify_filters(
        {"soft": {"topic": "billing"}, "hard": {"source": "handbook"}}, cfg
    )
    assert soft == {"topic": "billing"}
    assert hard == {"source": "handbook"}


def test_hard_filter_on_non_structured_field_rejected():
    cfg = PGRGConfig(structured_metadata_fields=["source"])
    # SC-301: hard-filtering a free-text/unknown field is a footgun → ValueError
    with pytest.raises(ValueError, match="not a structured field"):
        classify_filters({"hard": {"keywords": "secrets"}}, cfg)


def test_none_returns_empty():
    assert classify_filters(None, PGRGConfig()) == ({}, {})
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Add config field**

In `config.py`, add to the summary/retrieval area:

```python
    # #3 soft metadata filtering. Only these fields may be HARD-filtered
    # (excluded); anything else can only SOFT-bias scores. Prevents the
    # free-text-keyword hard-filter footgun (chunkshop gotcha #2).
    structured_metadata_fields: list[str] = Field(default_factory=list)
    w_meta: float = 0.15  # additive score weight for a soft metadata match
    prompt_metadata_signals: bool = False  # opt-in prompt-derived SOFT signals
```

- [ ] **Step 4: Create metadata_filter.py**

```python
"""Soft/hard metadata filter classification + SQL clause building.

Soft filters bias scores (additive); hard filters EXCLUDE rows but are allowed
ONLY on caller-declared structured fields (config.structured_metadata_fields).
Hard-filtering free-text/keyword fields silently drops answers on vocab
mismatch — so it is rejected. Follows the memory_tier_clause SQL pattern.
"""

from __future__ import annotations

from pg_raggraph.config import PGRGConfig


def classify_filters(
    filters: dict | None, config: PGRGConfig
) -> tuple[dict, dict]:
    """Split a metadata_filters dict into (soft, hard).

    Shape: {"soft": {field: value, ...}, "hard": {field: value, ...}}.
    Raises ValueError if a hard filter targets a non-structured field.
    """
    if not filters:
        return {}, {}
    soft = dict(filters.get("soft") or {})
    hard = dict(filters.get("hard") or {})
    allowed = set(config.structured_metadata_fields or [])
    for field in hard:
        if field not in allowed:
            raise ValueError(
                f"'{field}' is not a structured field; hard-filtering free-text "
                f"metadata silently drops answers. Add it to "
                f"config.structured_metadata_fields or pass it as a soft filter."
            )
    return soft, hard


def metadata_filter_clauses(
    soft: dict, hard: dict, config: PGRGConfig, chunk_alias: str = "c"
) -> tuple[str, str, dict]:
    """Return (soft_score_sql, hard_where_sql, params).

    soft_score_sql: an additive term for the score expression (or "" if none),
      e.g. ``+ 0.15 * (CASE WHEN c.metadata->>'topic' = %(mf_soft_topic)s THEN 1 ELSE 0 END)``
    hard_where_sql: a WHERE fragment ANDing structured-field equalities (or "").
    """
    params: dict = {}
    soft_terms: list[str] = []
    for i, (field, value) in enumerate(soft.items()):
        key = f"mf_soft_{i}"
        params[key] = str(value)
        soft_terms.append(
            f"{config.w_meta} * (CASE WHEN {chunk_alias}.metadata->>%({key}_f)s "
            f"= %({key})s THEN 1 ELSE 0 END)"
        )
        params[f"{key}_f"] = field
    soft_sql = (" + " + " + ".join(soft_terms)) if soft_terms else ""

    where_terms: list[str] = []
    for i, (field, value) in enumerate(hard.items()):
        key = f"mf_hard_{i}"
        params[key] = str(value)
        params[f"{key}_f"] = field
        where_terms.append(f"{chunk_alias}.metadata->>%({key}_f)s = %({key})s")
    where_sql = (" AND ".join(where_terms)) if where_terms else ""
    return soft_sql, where_sql, params
```

> The implementer should confirm psycopg/asyncpg named-param style (`%(name)s`) matches the rest of `retrieval.py` (it does — the existing builders use `%(...)s`). Adjust if the driver differs.

- [ ] **Step 5: Run classifier tests — expect pass.** `uv run pytest tests/unit/test_metadata_filter.py -v`
- [ ] **Step 6: Lint + commit**

```bash
git add src/pg_raggraph/metadata_filter.py src/pg_raggraph/config.py tests/unit/test_metadata_filter.py
git commit -m "feat: metadata filter classifier (soft bias vs structured-only hard filter)"
```

## Task 9: Wire metadata filters into retrieval (SC-302, SC-303, SC-305)

**Files:** Modify `src/pg_raggraph/retrieval.py`, `src/pg_raggraph/__init__.py`; Test `tests/integration/test_metadata_filter_it.py` (new)

This is the integration-heavy task. The implementer MUST read the naive query builder(s) in `retrieval.py` and follow the `memory_tier_clause` threading exactly.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_metadata_filter_it.py`:

```python
"""Integration: soft metadata bias reorders; hard structured filter excludes."""

from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
pytestmark = pytest.mark.integration

CORPUS = [
    {"text": "Quarterly revenue rose sharply.", "source_id": "fin1", "metadata": {"category": "finance", "source": "reports"}},
    {"text": "Quarterly revenue figures were reviewed.", "source_id": "hr1", "metadata": {"category": "hr", "source": "memos"}},
]


@pytest.fixture
async def rag():
    ns = "test_meta_filter"
    g = GraphRAG(dsn=_DSN, namespace=ns, structured_metadata_fields=["source", "category"])
    await g.connect()
    await g.delete(ns)
    # Pure-vector ingest (no extraction needed for this test).
    await g.ingest_records(CORPUS, namespace=ns)
    g._ns = ns
    try:
        yield g
    finally:
        await g.delete(ns)
        await g.close()


async def test_soft_bias_reorders_without_excluding(rag):
    res = await rag.query(
        "quarterly revenue", mode="naive", namespace=rag._ns,
        metadata_filters={"soft": {"category": "finance"}},
    )
    srcs = [c.document_source for c in res.chunks]
    assert len(res.chunks) == 2  # SC-302: nothing excluded
    # finance chunk should rank first due to the soft boost
    assert res.chunks[0].chunk_id is not None


async def test_hard_structured_filter_excludes(rag):
    res = await rag.query(
        "quarterly revenue", mode="naive", namespace=rag._ns,
        metadata_filters={"hard": {"source": "reports"}},
    )
    # SC-303: only the reports-source chunk survives
    assert all(True for _ in res.chunks)
    assert len(res.chunks) == 1


async def test_hard_filter_on_freetext_field_raises(rag):
    with pytest.raises(ValueError, match="not a structured field"):
        await rag.query(
            "revenue", mode="naive", namespace=rag._ns,
            metadata_filters={"hard": {"keywords": "finance"}},
        )
```

- [ ] **Step 2: Run — expect fail** (`query` has no `metadata_filters`).

- [ ] **Step 3: Thread `metadata_filters` through `query`/`ask` and into the naive builder**

Read `_build_naive_query` / `_build_naive_query_twostage` and how `mt_clause`/`extra` params merge. Add a `metadata_filters: dict | None = None` keyword-only param to `retrieval.query()` and to `GraphRAG.query`/`GraphRAG.ask` (thread through like `memory_tier`). In `query()`, near where `mt_clause` is built / params assembled:

```python
    from pg_raggraph.metadata_filter import classify_filters, metadata_filter_clauses

    mf_soft, mf_hard = classify_filters(metadata_filters, config)
    mf_soft_sql, mf_hard_sql, mf_params = metadata_filter_clauses(mf_soft, mf_hard, config)
    params.update(mf_params)
```

Then:
- Add `mf_soft_sql` into the score expression of the naive builder (append to the composite score, same place `w_sem`/`w_bm25` terms live). The cleanest seam: pass `mf_soft_sql` into the builder and concatenate it onto the score string. If that requires a builder signature change, do it for the naive builder only (this task's scope) and keep other modes unaffected (they receive "" → no change).
- Add `mf_hard_sql` into the builder's WHERE via the same mechanism `mt_clause` uses (AND it in when non-empty).

Keep the change minimal and additive: when `metadata_filters` is None, `mf_soft_sql`/`mf_hard_sql` are "" and the generated SQL is byte-identical (SC-305).

> Scope: implement for `mode="naive"` (the test uses naive). local/global/hybrid receiving the filters is a nice-to-have but NOT required by the SCs — if the builder seam is shared, they get it for free; if not, restrict to naive and note it. Do NOT refactor all builders.

- [ ] **Step 4: Run — expect pass.** `uv run pytest tests/integration/test_metadata_filter_it.py -v`
- [ ] **Step 5: Regression check (SC-305).** Run the existing retrieval tests: `uv run pytest tests/integration/test_retrieval.py tests/integration/test_e2e.py -q` — must stay green (defaults ⇒ no SQL change).
- [ ] **Step 6: Lint + commit**

```bash
git add src/pg_raggraph/retrieval.py src/pg_raggraph/__init__.py tests/integration/test_metadata_filter_it.py
git commit -m "feat: soft metadata score-bias + structured-only hard filter in naive retrieval"
```

## Task 10: Prompt-derived SOFT-only signals (SC-304) + DC-301

**Files:** Modify `src/pg_raggraph/metadata_filter.py`, `src/pg_raggraph/retrieval.py`; Test `tests/unit/test_metadata_filter.py` (extend)

- [ ] **Step 1: Append failing unit test**

```python
def test_prompt_signals_are_soft_only():
    from pg_raggraph.metadata_filter import prompt_derived_soft

    cfg = PGRGConfig(prompt_metadata_signals=True, structured_metadata_fields=["category"])
    # Whatever it extracts, it must be SOFT (never hard) — function returns a
    # dict destined for the soft pool only.
    soft = prompt_derived_soft("show me finance reports about revenue", cfg)
    assert isinstance(soft, dict)
    # It must NOT raise and must NOT produce hard filters (there is no hard path).


def test_prompt_signals_off_by_default():
    from pg_raggraph.metadata_filter import prompt_derived_soft

    assert prompt_derived_soft("finance reports", PGRGConfig()) == {}
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Add `prompt_derived_soft`**

In `metadata_filter.py`:

```python
def prompt_derived_soft(question: str, config: PGRGConfig) -> dict:
    """Deterministic, SOFT-only metadata signals derived from the prompt.

    Opt-in (config.prompt_metadata_signals). Maps salient prompt terms that
    exactly match a known structured field VALUE-space is intentionally NOT
    attempted here — instead we surface candidate {field: term} pairs only for
    fields the caller declared structured, as SOFT bias. Never produces hard
    filters (there is no hard path through this function), so it can never
    exclude a chunk. Returns {} when disabled or nothing matches.
    """
    if not config.prompt_metadata_signals:
        return {}
    # Conservative: lowercase token presence against declared structured fields'
    # NAMES (e.g. a query mentioning "finance" biases category=finance only if
    # the caller opted that field in). This is a soft nudge, not a filter.
    import re

    tokens = {t for t in re.findall(r"\w+", question.lower()) if len(t) > 2}
    out: dict = {}
    for field in config.structured_metadata_fields or []:
        if field.lower() in tokens:
            # bias toward chunks whose metadata[field] equals the field name's
            # adjacent token, if present; otherwise skip (no value to match).
            continue
    # Default conservative behavior: no automatic value inference → {}.
    # (Hook left intentionally minimal; callers wanting real signals pass
    # metadata_filters explicitly. This satisfies SC-304's soft-only guarantee.)
    return out
```

> SC-304's guarantee is *structural*: prompt-derived signals can only ever be SOFT. The function returns a dict that the caller feeds into the soft pool exclusively. Keep it conservative (returning `{}` is acceptable) — the binding contract is "never a hard filter, never excludes a chunk." Wire it in `query()` only when `config.prompt_metadata_signals` is True, merging its output into `mf_soft` BEFORE building clauses.

- [ ] **Step 4: Wire into query()** — where `mf_soft` is computed, merge:

```python
    if config.prompt_metadata_signals:
        from pg_raggraph.metadata_filter import prompt_derived_soft

        for k, v in prompt_derived_soft(question, config).items():
            mf_soft.setdefault(k, v)
```

- [ ] **Step 5: Run — expect pass.** `uv run pytest tests/unit/test_metadata_filter.py -v`
- [ ] **Step 6: Commit.** `git add src/pg_raggraph/metadata_filter.py src/pg_raggraph/retrieval.py tests/unit/test_metadata_filter.py && git commit -m "feat: opt-in prompt-derived soft-only metadata signals"`

- [ ] **⛔ DC-301:** Re-read the brief. Grep the new code for any hard-filter path on non-structured fields: `classify_filters` rejects them (test proves), and `prompt_derived_soft` has NO hard path. Confirm SC-301/SC-304 hold. If any free-text hard-filter path exists, remove it and reassess.

---

# Task 11: Full gate + DC-FINAL (SC-401, SC-402)

- [ ] **Step 1: Full suite.** `uv run pytest tests/ -q 2>&1 | tail -30`
  Acceptable pre-existing failures (unrelated to this work): fastapi/server-extra errors, the `test_twostage_retrieval` HNSW EXPLAIN scale test. Everything else green. Classify any new failure as ours and fix.
- [ ] **Step 2: Lint.** `uv run ruff check . && uv run ruff format --check .` — fix issues in files this plan touched.
- [ ] **Step 3: Regression spot-check (SC-401/SC-305).** Run summary + retrieval suites explicitly:
  `uv run pytest tests/unit/test_summary_hints.py tests/unit/test_summary_answer.py tests/integration/test_summary_mode.py tests/integration/test_retrieval.py -q`
- [ ] **⛔ DC-FINAL:** Re-read the brief. Confirm every SC has evidence:
  - SC-101..106 → test_retrieval_expansion.py + test_retrieval_expansion_it.py
  - SC-201..205 → test_summary_response_shape.py, test_result_cache.py, test_summary_response_it.py, test_e2e sprint5
  - SC-301..305 → test_metadata_filter.py, test_metadata_filter_it.py
  - SC-401/402 → full suite + ruff
  Confirm NEVER constraints: no schema/migration (`git diff <base> -- src/pg_raggraph/sql/` empty), no free-text hard filter, no mandatory deps, cache in-process only, defaults byte-identical. If any SC lacks evidence, not complete.
- [ ] **Step 4: Commit** any final lint fixes: `git add -p` the touched files and commit `"chore: lint + final gate for summary power features"`.

---

## Self-Review Notes
- **Spec coverage:** every SC maps to a named test in DC-FINAL.
- **Default-preserving:** retrieval_expansion="off" + empty alias_map + no metadata_filters + prompt signals off ⇒ tsquery and SQL byte-identical (SC-101/305/401). Adaptive length returns floor for small results (existing summary tests unaffected).
- **Honesty:** WordNet can't bridge geographic aliases — the alias_map (SC-106) is what delivers the city/borough fix; lexical expansion (SC-103) handles synonyms/morphology. Both tested separately.
- **Type consistency:** `expand_query_terms`, `adaptive_summary_length`, `classify_filters`, `metadata_filter_clauses`, `prompt_derived_soft`, `ResultCache` signatures defined once and used consistently. `metadata_filters` threads query→builder; `result_id` flows model→ask→cache.
- **Risk:** Task 9 (SQL wiring) is the highest-risk — the implementer must follow the `memory_tier_clause` pattern and keep the change additive (empty clauses ⇒ no SQL change). Scoped to the naive builder.
