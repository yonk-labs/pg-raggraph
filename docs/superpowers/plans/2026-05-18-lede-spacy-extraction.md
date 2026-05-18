# lede_spacy Non-LLM Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `fact_extractor="lede_spacy"` a real, deterministic, LLM-free extractor that builds an entity + co-occurrence-edge graph through the existing ingest pipeline, with fail-loud on missing optional deps.

**Architecture:** A new `lede_extraction.py` module exposes `extract_from_chunks_lede()` with the same signature as `extraction.extract_from_chunks()`, so it drops into the existing `extract_from_chunks_fn` seam with zero downstream change. Entities come from `lede.extract.metadata(text, backend="spacy").entities` (untyped strings, verified `lede==0.3.0`); edges from `lede.sentences.split_sentences()` sentence-level co-occurrence. The two ingest gates in `__init__.py` learn to select this extractor without requiring `llm_base_url`.

**Tech Stack:** Python 3.12, `lede>=0.3`, `lede-spacy>=0.3`, `spacy>=3.7` + `en_core_web_sm`, pytest/pytest-asyncio, PostgreSQL 16 (pgvector) for integration.

**Reference spec:** `docs/superpowers/specs/2026-05-18-lede-spacy-extraction-design.md`

---

## Verified upstream API (probed against installed `lede==0.3.0` / `lede-spacy==0.3.0`, 2026-05-18)

```python
import lede, lede_spacy                       # importing lede_spacy registers the "spacy" backend (side effect)
m = lede.extract.metadata(text, backend="spacy")
m.entities                                     # tuple[str, ...]  e.g. ("NASA", "Neil Armstrong", "Moon") — NO type labels
from lede.sentences import split_sentences
split_sentences(text)                          # (text: str) -> list[str]   deterministic regex splitter, zero-dep
```

Model shapes (`src/pg_raggraph/models.py`):

```python
class ExtractedEntity(BaseModel):
    name: str
    entity_type: str = "concept"
    description: str = ""

class ExtractedRelationship(BaseModel):
    source: str
    target: str
    rel_type: str = "RELATED_TO"
    description: str = ""
    weight: float | None = 1.0

class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
```

Existing seam signature (`src/pg_raggraph/extraction.py:308`):
`async def extract_from_chunks(chunks: list[dict], llm, db, config) -> list[ExtractionResult]`

---

## File Structure

- **Create** `src/pg_raggraph/lede_extraction.py` — fail-loud check + the non-LLM extractor. One responsibility: turn chunks into `ExtractionResult`s via lede/lede-spacy. No DB, no LLM.
- **Create** `tests/unit/test_lede_extraction.py` — pure-logic unit tests (entity build, co-occurrence edges, fail-loud messages, gate selection).
- **Create** `tests/integration/test_lede_extraction_ingest.py` — real-PG ingest with `fact_extractor="lede_spacy"`, no LLM URL.
- **Modify** `src/pg_raggraph/__init__.py` — gate selection at `:368` and `:596`; `_extract_and_store` short-circuit at `:865`.
- **Modify** `pyproject.toml:44-52` — add `[lede_spacy]` extra, add to `all`.
- **Modify** `src/pg_raggraph/config.py:231-235` — correct the SPO-triple comment.
- **Modify** `docs/Config-Reference.md`, `docs/cookbook/evolution-tracking.md`, `docs/user-guide.md`, `tests/test_e2e.py`.

---

## Task 1: Packaging extra (`pyproject.toml`)

**Files:**
- Modify: `pyproject.toml:44-52`

- [ ] **Step 1: Add the `lede_spacy` extra and add it to `all`**

Replace lines 42-52 (the `chunkshop` extra through the `all` line) with:

```toml
# Sibling library for richer chunking strategies + optional metadata extraction.
# Optional but recommended — see docs/cookbook/chunkshop-integration.md.
chunkshop = ["chunkshop>=0.3"]
# Deterministic, LLM-free entity + co-occurrence-edge extraction.
# Requires the spaCy model too: python -m spacy download en_core_web_sm
# See docs/superpowers/specs/2026-05-18-lede-spacy-extraction-design.md
lede_spacy = ["lede>=0.3", "lede-spacy>=0.3", "spacy>=3.7"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.5",
    "coverage>=7.0",
    "beautifulsoup4>=4.14.3",
    "lede>=0.3",
    "lede-spacy>=0.3",
    "spacy>=3.7",
]
all = ["pg-raggraph[server,community,langchain,llamaindex,mcp,chunkshop,lede_spacy]"]
```

(`lede`/`lede-spacy`/`spacy` are added to `dev` so the unit + integration tests have them without a separate extra install.)

- [ ] **Step 2: Sync and verify the deps + spaCy model resolve**

Run:
```bash
uv sync --extra dev && uv run python -m spacy download en_core_web_sm && \
uv run python -c "import lede, lede_spacy; print(lede.extract.metadata('NASA launched Saturn V.', backend='spacy').entities)"
```
Expected: prints a tuple like `('NASA', 'Saturn')` with no traceback.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build(deps): add [lede_spacy] extra (lede + lede-spacy + spacy)"
```

---

## Task 2: Fail-loud dependency check

**Files:**
- Create: `src/pg_raggraph/lede_extraction.py`
- Test: `tests/unit/test_lede_extraction.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_lede_extraction.py`:

```python
import builtins
import importlib

import pytest

from pg_raggraph import lede_extraction


def test_ensure_lede_available_passes_when_installed():
    # lede/lede_spacy/en_core_web_sm are in the dev extra — should not raise.
    lede_extraction.ensure_lede_available()


def test_ensure_lede_available_message_when_lede_missing(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "lede" or name.startswith("lede."):
            raise ModuleNotFoundError("No module named 'lede'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError) as exc:
        lede_extraction.ensure_lede_available()
    msg = str(exc.value)
    assert "pg-raggraph[lede_spacy]" in msg
    assert "spacy download en_core_web_sm" in msg
    assert 'fact_extractor="lede_spacy"' in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_lede_extraction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pg_raggraph.lede_extraction'`

- [ ] **Step 3: Write minimal implementation**

Create `src/pg_raggraph/lede_extraction.py`:

```python
"""Deterministic, LLM-free extraction via lede + lede-spacy.

`fact_extractor="lede_spacy"` selects this path. Entities come from
lede's spaCy NER backend (untyped surface strings in lede 0.3.0);
edges are sentence-level co-occurrence. No LLM, no network.

Optional deps — install with:
    pip install 'pg-raggraph[lede_spacy]'
    python -m spacy download en_core_web_sm
"""

from __future__ import annotations

import asyncio
import logging

from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
)

logger = logging.getLogger("pg_raggraph.lede_extraction")

_INSTALL_HINT = (
    'fact_extractor="lede_spacy" requires the optional extra and the '
    "spaCy model:\n"
    "    pip install 'pg-raggraph[lede_spacy]'\n"
    "    python -m spacy download en_core_web_sm"
)


def ensure_lede_available() -> None:
    """Raise RuntimeError with exact remediation if the lede path can't run.

    Distinguishes missing `lede`, missing `lede_spacy`, and missing
    spaCy model so the operator knows which command to run.
    """
    try:
        import lede  # noqa: F401
    except ModuleNotFoundError as e:
        raise RuntimeError(f"`lede` not installed. {_INSTALL_HINT}") from e
    try:
        import lede_spacy  # noqa: F401  (import registers the spacy backend)
    except ModuleNotFoundError as e:
        raise RuntimeError(f"`lede-spacy` not installed. {_INSTALL_HINT}") from e
    try:
        import spacy

        spacy.load("en_core_web_sm")
    except (ModuleNotFoundError, OSError) as e:
        raise RuntimeError(
            f"spaCy model `en_core_web_sm` not available. {_INSTALL_HINT}"
        ) from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_lede_extraction.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/lede_extraction.py tests/unit/test_lede_extraction.py
git commit -m "feat(lede): fail-loud dependency check for lede_spacy path"
```

---

## Task 3: Entity extraction from a chunk

**Files:**
- Modify: `src/pg_raggraph/lede_extraction.py`
- Test: `tests/unit/test_lede_extraction.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_lede_extraction.py`:

```python
def test_entities_from_text_are_untyped_and_filtered():
    text = (
        "NASA launched the Saturn V rocket from Kennedy Space Center. "
        "Neil Armstrong and Buzz Aldrin walked on the Moon."
    )
    ents = lede_extraction._entities_from_text(text)
    names = {e.name for e in ents}
    assert "NASA" in names
    assert "Neil Armstrong" in names
    # generic type for v1 (lede 0.3.0 exposes no NER labels)
    assert all(e.entity_type == "entity" for e in ents)
    # blocklist/short-token filter from extraction._is_valid_entity applied
    assert all(len(e.name) >= 2 for e in ents)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_lede_extraction.py::test_entities_from_text_are_untyped_and_filtered -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_entities_from_text'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/pg_raggraph/lede_extraction.py`:

```python
def _entities_from_text(text: str) -> list[ExtractedEntity]:
    """Untyped entity strings via lede's spaCy backend → ExtractedEntity.

    lede 0.3.0's public API returns a flat tuple of surface strings with
    no NER labels, so entity_type is the generic "entity". Reuses the
    existing false-positive filter.
    """
    import lede
    import lede_spacy  # noqa: F401  (registers the spacy backend on import)

    from pg_raggraph.extraction import _is_valid_entity

    if not text or not text.strip():
        return []
    raw = lede.extract.metadata(text, backend="spacy").entities
    seen: set[str] = set()
    out: list[ExtractedEntity] = []
    for name in raw:
        name = (name or "").strip()
        if name in seen or not _is_valid_entity(name):
            continue
        seen.add(name)
        out.append(ExtractedEntity(name=name, entity_type="entity", description=""))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_lede_extraction.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/lede_extraction.py tests/unit/test_lede_extraction.py
git commit -m "feat(lede): untyped entity extraction with existing FP filter"
```

---

## Task 4: Sentence-level co-occurrence edges

**Files:**
- Modify: `src/pg_raggraph/lede_extraction.py`
- Test: `tests/unit/test_lede_extraction.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_lede_extraction.py`:

```python
def test_cooccurrence_edges_weighted_and_supported():
    names = ["NASA", "Saturn V", "Congress"]
    sentences = [
        "NASA launched the Saturn V rocket.",
        "Congress funded NASA that decade.",
        "NASA and Saturn V appeared together again here.",
    ]
    rels = lede_extraction._cooccurrence_edges(names, sentences)
    by_pair = {(r.source, r.target): r for r in rels}
    # NASA<->Saturn V co-occur in 2 sentences
    key = ("NASA", "Saturn V") if ("NASA", "Saturn V") in by_pair else ("Saturn V", "NASA")
    assert by_pair[key].weight == 2.0
    assert by_pair[key].rel_type == "RELATED_TO"
    assert "NASA" in by_pair[key].description  # verbatim supporting sentence
    # substring false-positives avoided: "NASA" must not match inside a word
    assert lede_extraction._mentions("NASASAT orbiter", "NASA") is False
    assert lede_extraction._mentions("NASA launched.", "NASA") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_lede_extraction.py::test_cooccurrence_edges_weighted_and_supported -v`
Expected: FAIL — `AttributeError: ... '_cooccurrence_edges'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/pg_raggraph/lede_extraction.py`:

```python
import re


def _mentions(sentence: str, name: str) -> bool:
    """True if `name` appears in `sentence` on word-ish boundaries.

    Avoids substring false positives ("NASA" inside "NASASAT").
    """
    return re.search(
        rf"(?<!\w){re.escape(name)}(?!\w)", sentence, flags=re.IGNORECASE
    ) is not None


def _cooccurrence_edges(
    names: list[str], sentences: list[str]
) -> list[ExtractedRelationship]:
    """RELATED_TO edges for entities co-occurring in the same sentence.

    weight = number of sentences the pair co-occurs in. description = the
    first supporting sentence verbatim. Deterministic: pairs are ordered
    by first appearance in `names`.
    """
    counts: dict[tuple[str, str], int] = {}
    support: dict[tuple[str, str], str] = {}
    for sent in sentences:
        present = [n for n in names if _mentions(sent, n)]
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                a, b = present[i], present[j]
                if a == b:
                    continue
                pair = (a, b)
                counts[pair] = counts.get(pair, 0) + 1
                support.setdefault(pair, sent.strip())
    return [
        ExtractedRelationship(
            source=a,
            target=b,
            rel_type="RELATED_TO",
            description=support[(a, b)],
            weight=float(n),
        )
        for (a, b), n in counts.items()
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_lede_extraction.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/lede_extraction.py tests/unit/test_lede_extraction.py
git commit -m "feat(lede): sentence-level co-occurrence RELATED_TO edges"
```

---

## Task 5: The `extract_from_chunks_lede` seam function

**Files:**
- Modify: `src/pg_raggraph/lede_extraction.py`
- Test: `tests/unit/test_lede_extraction.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_lede_extraction.py`:

```python
import asyncio


def test_extract_from_chunks_lede_returns_one_result_per_chunk():
    chunks = [
        {"content": "NASA launched the Saturn V rocket. NASA and Saturn V again.",
         "embedded_content": "NASA launched the Saturn V rocket. NASA and Saturn V again."},
        {"content": "", "embedded_content": ""},
    ]
    results = asyncio.run(
        lede_extraction.extract_from_chunks_lede(chunks, None, None, None)
    )
    assert len(results) == 2
    assert any(e.name == "NASA" for e in results[0].entities)
    assert results[1].entities == [] and results[1].relationships == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_lede_extraction.py::test_extract_from_chunks_lede_returns_one_result_per_chunk -v`
Expected: FAIL — `AttributeError: ... 'extract_from_chunks_lede'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/pg_raggraph/lede_extraction.py`:

```python
def _extract_one(text: str) -> ExtractionResult:
    from lede.sentences import split_sentences

    from pg_raggraph.extraction import filter_extraction

    entities = _entities_from_text(text)
    if not entities:
        return ExtractionResult()
    names = [e.name for e in entities]
    sentences = split_sentences(text) if text and text.strip() else []
    rels = _cooccurrence_edges(names, sentences)
    return filter_extraction(
        ExtractionResult(entities=entities, relationships=rels)
    )


async def extract_from_chunks_lede(
    chunks: list[dict],
    llm,  # ignored — accepted for seam parity with extract_from_chunks
    db,  # unused — no LLM cache on the deterministic path
    config: PGRGConfig | None,
) -> list[ExtractionResult]:
    """Deterministic, LLM-free analogue of extraction.extract_from_chunks.

    One ExtractionResult per chunk. CPU-bound lede/spaCy work is run in a
    thread so the event loop is not blocked. Order is preserved.
    """

    def _work(text: str) -> ExtractionResult:
        try:
            return _extract_one(text)
        except Exception as e:  # never fail the whole ingest on one chunk
            logger.warning("lede extraction failed for a chunk: %s", e)
            return ExtractionResult()

    texts = [c.get("embedded_content") or c.get("content") or "" for c in chunks]
    return await asyncio.gather(
        *(asyncio.to_thread(_work, t) for t in texts)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_lede_extraction.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/lede_extraction.py tests/unit/test_lede_extraction.py
git commit -m "feat(lede): extract_from_chunks_lede seam (async, per-chunk)"
```

---

## Task 6: Wire `fact_extractor` into the two ingest gates

**Files:**
- Modify: `src/pg_raggraph/__init__.py:362-376` (file-ingest gate)
- Modify: `src/pg_raggraph/__init__.py:594-604` (records-ingest gate)
- Modify: `src/pg_raggraph/__init__.py:864-868` (`_extract_and_store` short-circuit)
- Test: `tests/unit/test_lede_extraction.py`

- [ ] **Step 1: Write the failing test (gate selection helper)**

Append to `tests/unit/test_lede_extraction.py`:

```python
from pg_raggraph.lede_extraction import select_extractor


class _Cfg:
    def __init__(self, fact_extractor, skip_extraction=False, llm_base_url=""):
        self.fact_extractor = fact_extractor
        self.skip_extraction = skip_extraction
        self.llm_base_url = llm_base_url


def test_select_extractor_lede_path_needs_no_llm():
    fn, needs_llm = select_extractor(_Cfg("lede_spacy"))
    assert needs_llm is False
    assert fn is lede_extraction.extract_from_chunks_lede


def test_select_extractor_llm_path_unchanged():
    fn, needs_llm = select_extractor(_Cfg("llm", llm_base_url="http://x"))
    assert needs_llm is True
    assert fn is None  # caller uses the existing extract_from_chunks

    fn, needs_llm = select_extractor(_Cfg("none"))
    assert needs_llm is True and fn is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_lede_extraction.py -k select_extractor -v`
Expected: FAIL — `ImportError: cannot import name 'select_extractor'`

- [ ] **Step 3: Implement `select_extractor` in `lede_extraction.py`**

Append to `src/pg_raggraph/lede_extraction.py`:

```python
def select_extractor(config):
    """Decide which extractor the ingest gate should use.

    Returns (extractor_fn_or_None, needs_llm).
    - fact_extractor == "lede_spacy": (extract_from_chunks_lede, False)
      — runs the deterministic path; no llm_base_url required.
    - anything else: (None, True) — caller keeps the existing
      LLM/skip_extraction behavior unchanged.
    """
    if getattr(config, "fact_extractor", "none") == "lede_spacy":
        return extract_from_chunks_lede, False
    return None, True
```

- [ ] **Step 4: Wire the file-ingest gate**

In `src/pg_raggraph/__init__.py`, the block at lines 362-376 currently reads:

```python
        llm = None
        if not self.config.skip_extraction and self.config.llm_base_url:
            if self._llm is None:
                try:
                    self._llm = get_llm_provider(self.config)
                except Exception as e:
                    logger.warning(f"LLM provider unavailable, skipping extraction: {e}")
            llm = self._llm
        if llm is None:
            _progress("Extraction disabled — ingesting as pure vector RAG.")
```

Replace with:

```python
        from pg_raggraph.lede_extraction import select_extractor

        llm = None
        lede_fn, needs_llm = select_extractor(self.config)
        if lede_fn is not None:
            from pg_raggraph.lede_extraction import ensure_lede_available

            ensure_lede_available()
            extract_from_chunks = lede_fn
            _progress("Extraction via lede_spacy (deterministic, no LLM).")
        elif not self.config.skip_extraction and self.config.llm_base_url:
            if self._llm is None:
                try:
                    self._llm = get_llm_provider(self.config)
                except Exception as e:
                    logger.warning(f"LLM provider unavailable, skipping extraction: {e}")
            llm = self._llm
        if lede_fn is None and llm is None:
            _progress("Extraction disabled — ingesting as pure vector RAG.")
```

(Note: `extract_from_chunks` is the local name imported at `__init__.py:295` and threaded through as `extract_from_chunks_fn`; rebinding it here is what flows into `_ingest_one_file`.)

- [ ] **Step 5: Wire the records-ingest gate**

In `src/pg_raggraph/__init__.py`, the block at lines 594-604 currently reads:

```python
        doc_sem = asyncio.Semaphore(self.config.doc_concurrency)
        llm = None
        if not self.config.skip_extraction and self.config.llm_base_url:
            if self._llm is None:
                try:
                    self._llm = get_llm_provider(self.config)
                except Exception as e:
                    logger.warning(f"LLM provider unavailable, skipping extraction: {e}")
            llm = self._llm
        if llm is None:
            _progress("Extraction disabled — ingesting as pure vector RAG.")
```

Replace with:

```python
        from pg_raggraph.lede_extraction import select_extractor

        doc_sem = asyncio.Semaphore(self.config.doc_concurrency)
        llm = None
        lede_fn, needs_llm = select_extractor(self.config)
        if lede_fn is not None:
            from pg_raggraph.lede_extraction import ensure_lede_available

            ensure_lede_available()
            extract_from_chunks = lede_fn
            _progress("Extraction via lede_spacy (deterministic, no LLM).")
        elif not self.config.skip_extraction and self.config.llm_base_url:
            if self._llm is None:
                try:
                    self._llm = get_llm_provider(self.config)
                except Exception as e:
                    logger.warning(f"LLM provider unavailable, skipping extraction: {e}")
            llm = self._llm
        if lede_fn is None and llm is None:
            _progress("Extraction disabled — ingesting as pure vector RAG.")
```

- [ ] **Step 6: Fix the `_extract_and_store` short-circuit**

In `src/pg_raggraph/__init__.py`, the block at lines 864-868 currently reads:

```python
        extraction_degraded = False
        if llm is None or skip_llm_for_this_doc:
            from pg_raggraph.models import ExtractionResult

            extraction_results = [ExtractionResult() for _ in chunks]
```

Replace with:

```python
        extraction_degraded = False
        _lede_path = getattr(self.config, "fact_extractor", "none") == "lede_spacy"
        if (llm is None and not _lede_path) or skip_llm_for_this_doc:
            from pg_raggraph.models import ExtractionResult

            extraction_results = [ExtractionResult() for _ in chunks]
```

(The lede extractor ignores `llm`, so `llm is None` must not short-circuit it. `skip_llm_for_this_doc` still wins — a per-doc opt-out.)

- [ ] **Step 7: Run unit tests**

Run: `uv run pytest tests/unit/test_lede_extraction.py -v`
Expected: PASS (7 passed)

- [ ] **Step 8: Run the full unit suite for regressions**

Run: `uv run pytest tests/unit/ -q`
Expected: all pass (no regression vs. the 73-test baseline + new tests)

- [ ] **Step 9: Commit**

```bash
git add src/pg_raggraph/__init__.py src/pg_raggraph/lede_extraction.py tests/unit/test_lede_extraction.py
git commit -m "feat(ingest): wire fact_extractor=lede_spacy into both ingest gates"
```

---

## Task 7: Integration test — real PG ingest, no LLM URL

**Files:**
- Create: `tests/integration/test_lede_extraction_ingest.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_lede_extraction_ingest.py`:

```python
import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.config import PGRGConfig

pytestmark = pytest.mark.asyncio

_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"

_DOC = (
    "# Apollo Program\n\n"
    "NASA launched the Saturn V rocket from Kennedy Space Center. "
    "Neil Armstrong and Buzz Aldrin walked on the Moon while Michael "
    "Collins orbited. Congress funded NASA throughout the decade."
)


@pytest.fixture
def _model_available():
    try:
        import lede, lede_spacy  # noqa: F401
        import spacy

        spacy.load("en_core_web_sm")
    except Exception:
        pytest.skip("lede/lede-spacy/en_core_web_sm not available")


async def test_lede_spacy_ingest_builds_graph_without_llm(tmp_path, _model_available):
    ns = "lede_it"
    cfg = PGRGConfig(
        dsn=_DSN,
        namespace=ns,
        fact_extractor="lede_spacy",
        llm_base_url="",  # explicitly no LLM
    )
    rag = await GraphRAG.connect(cfg)
    try:
        await rag.ingest_records(
            [{"text": _DOC, "source_id": "apollo:1"}], namespace=ns
        )
        ent = await rag.db.fetch_one(
            "SELECT COUNT(*) AS n FROM entities WHERE namespace=%s", (ns,)
        )
        rel = await rag.db.fetch_one(
            "SELECT COUNT(*) AS n FROM relationships WHERE namespace=%s", (ns,)
        )
        assert ent["n"] > 0, "lede_spacy must populate entities without an LLM"
        assert rel["n"] > 0, "co-occurrence must populate relationships"
    finally:
        await rag.delete(namespace=ns)
        await rag.close()
```

(If `PGRGConfig`/`GraphRAG.connect`/`delete` signatures differ from the above, match the patterns already used in `tests/integration/` — read one existing integration test first and mirror its fixture/teardown style. The assertions on `entities`/`relationships` counts are the contract that must hold.)

- [ ] **Step 2: Ensure PG is up, run the test to verify it fails first if wiring were absent, then passes**

Run:
```bash
docker compose up -d postgres
uv run pytest tests/integration/test_lede_extraction_ingest.py -v
```
Expected: PASS — entity and relationship counts both > 0.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_lede_extraction_ingest.py
git commit -m "test(integration): lede_spacy ingest builds graph with no LLM"
```

---

## Task 8: Extend cumulative E2E for the no-LLM path

**Files:**
- Modify: `tests/test_e2e.py`

- [ ] **Step 1: Read the existing E2E to find the insertion point**

Run: `uv run pytest tests/test_e2e.py -v` and read `tests/test_e2e.py` to locate the cumulative schema→ingest→query flow and its namespace/config conventions.

- [ ] **Step 2: Add a no-LLM lede_spacy stage**

Add a test stage (mirroring the file's existing style) that, after schema bootstrap, ingests a small fixture doc with `fact_extractor="lede_spacy"` and `llm_base_url=""`, then asserts:
- `entities` count > 0 for the test namespace,
- a `query()` for a term in the doc returns at least one chunk,
- no exception / no "Extraction disabled" degraded path.

Use the same DSN and skip-if-model-missing fixture pattern as Task 7. Do not duplicate the helper — import the `_model_available` skip logic or replicate the 4-line try/skip inline (the file may run independently).

- [ ] **Step 3: Run E2E**

Run: `uv run pytest tests/test_e2e.py -v`
Expected: PASS including the new lede_spacy stage.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test(e2e): cover no-LLM lede_spacy ingest→query in cumulative path"
```

---

## Task 9: Documentation corrections

**Files:**
- Modify: `src/pg_raggraph/config.py:230-238`
- Modify: `docs/Config-Reference.md` (the `fact_extractor` section ~line 503)
- Modify: `docs/cookbook/evolution-tracking.md` (~line 133)
- Modify: `docs/user-guide.md` (~line 429)

- [ ] **Step 1: Correct the config comment**

In `src/pg_raggraph/config.py`, replace the comment block at lines 231-234 (currently claiming "spaCy dep-parses them into SPO triples") with:

```python
    # Fact extraction (Tier 2+)
    # `lede_spacy` is the supported non-LLM extractor: lede + lede-spacy
    # NER produce (untyped) entities; edges are deterministic
    # sentence-level co-occurrence (RELATED_TO). No LLM, no network.
    # Requires the [lede_spacy] extra + `python -m spacy download
    # en_core_web_sm`. Selecting it builds a graph WITHOUT llm_base_url.
    # NOTE: it does NOT emit SPO triples and does NOT populate the Tier 2
    # `facts` table — that is a tracked follow-up. `llm` = full LLM
    # extraction; `none` = disabled.
```

- [ ] **Step 2: Correct `docs/Config-Reference.md`**

In the `fact_extractor` section, replace any text describing `lede_spacy` as "regex-y" / SPO / fact-table-populating with: deterministic non-LLM NER entities (untyped in v1) + sentence co-occurrence edges; needs the `[lede_spacy]` extra and `python -m spacy download en_core_web_sm`; no `llm_base_url` required; does not populate the `facts` table (follow-up).

- [ ] **Step 3: Correct `docs/cookbook/evolution-tracking.md` and `docs/user-guide.md`**

Replace the `fact_extractor="lede_spacy"` mentions that imply fact-level/SPO extraction or `facts`-table population with the accurate description from Step 2 (entity + co-occurrence graph, no LLM, install requirements, facts-table deferred).

- [ ] **Step 4: Verify no remaining "SPO triple" claims for lede_spacy**

Run: `grep -rn "SPO\|dep-parse\|skimr_spacy" src/ docs/Config-Reference.md docs/cookbook/evolution-tracking.md docs/user-guide.md`
Expected: no results tying `lede_spacy` to SPO/dep-parse in the live (non-archive) docs/code.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/config.py docs/Config-Reference.md docs/cookbook/evolution-tracking.md docs/user-guide.md
git commit -m "docs: lede_spacy is non-LLM NER + co-occurrence (not SPO triples)"
```

---

## Task 10: Final verification

- [ ] **Step 1: Full suite**

Run: `uv run pytest -q`
Expected: all unit + integration + e2e pass (lede tests skip cleanly only if the spaCy model is genuinely absent).

- [ ] **Step 2: Lint/format**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean (fix and re-commit if not).

- [ ] **Step 3: Manual smoke (test-as-user)**

Run:
```bash
uv run python -c "
import asyncio
from pg_raggraph import GraphRAG
from pg_raggraph.config import PGRGConfig
async def m():
    cfg=PGRGConfig(dsn='postgresql://postgres:postgres@localhost:5434/pg_raggraph',namespace='lede_smoke',fact_extractor='lede_spacy',llm_base_url='')
    rag=await GraphRAG.connect(cfg)
    await rag.ingest_records([{'text':'NASA launched the Saturn V rocket. Congress funded NASA.','source_id':'s:1'}],namespace='lede_smoke')
    print(await rag.query('NASA', namespace='lede_smoke'))
    await rag.delete(namespace='lede_smoke'); await rag.close()
asyncio.run(m())
"
```
Expected: a non-empty query result, no "Extraction disabled" line, no traceback.

- [ ] **Step 4: Confirm fail-loud manually**

Run (simulates missing model by an env with no model — optional if model installed):
```bash
uv run python -c "from pg_raggraph.lede_extraction import ensure_lede_available; ensure_lede_available(); print('deps OK')"
```
Expected: `deps OK` (or, if a dep were missing, a RuntimeError naming the exact pip/spacy command).

---

## Self-Review (completed by plan author)

**Spec coverage:** Component 1 (extractor module) → Tasks 2-5. Component 2 (gate wiring) → Task 6. Component 3 (fail-loud) → Task 2 + Task 6 Step 4/5. Component 4 (packaging) → Task 1. Component 5 (docs) → Task 9. Testing section → Tasks 2-8, 10. Non-goal (facts table) explicitly stated in Task 9 doc text. No spec requirement left without a task.

**Placeholder scan:** Task 7 and Task 8 intentionally instruct the engineer to mirror existing integration/e2e conventions rather than hard-coding possibly-wrong fixture signatures — the binding contract (entity/rel counts > 0, no degrade) is explicit, which is the testable assertion, not a placeholder. All code steps contain complete code.

**Type consistency:** `extract_from_chunks_lede(chunks, llm, db, config)` matches the `extract_from_chunks` seam used at `__init__.py:871`. `select_extractor` returns `(fn|None, bool)` consistently across Task 6 definition and call sites. `ExtractedEntity`/`ExtractedRelationship`/`ExtractionResult` field names match `models.py:141-163`. `_mentions`/`_cooccurrence_edges`/`_entities_from_text`/`_extract_one` names consistent across Tasks 3-5 and tests.
