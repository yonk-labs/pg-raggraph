# Code-Symbol Graph at Ingest (#74, #75) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `chunk_strategy="chunkshop:symbol_aware"` populate per-chunk
`metadata['callees']` (#74) and the `entities`/`relationships` code graph that
`code_impact()` reads (#75), always-on, reusing the existing Pattern C mapper.

**Architecture:** `_chunk_via_chunkshop` runs chunkshop's
`CodeRelationshipsExtractor` per chunk (attaching `callees`) and once via
`finalize()` (resolved edges), stashing the edges on a private `__code_edges__`
metadata key. `_ingest_one_content` pops that key and converts it through the
existing `chunkshop_bridge.code_edges_to_known_graph()` into the same
`known_entities`/`known_relationships` ingest seam Pattern C uses. Per-file
resolution scope. No schema changes, no new mapper, no new write code.

**Tech Stack:** Python 3.12+, asyncpg/psycopg, chunkshop ≥0.8.2 (optional dep),
tree-sitter + tree-sitter-python (test dep), pytest + pytest-asyncio, PostgreSQL
16 + pgvector on port 5434.

**Spec:** `docs/superpowers/specs/2026-06-08-code-symbol-graph-ingest-design.md`

---

## File Structure

- `pyproject.toml` — add `tree-sitter` + `tree-sitter-python` to the `dev` extra
  (test-only; the real parse path needs the grammar — regex fallback degrades).
- `src/pg_raggraph/chunkshop_bridge.py` — **new** `SymbolGraph` dataclass +
  `extract_symbol_graph()` (runs the extractor over symbol_aware chunks; returns
  `None` if chunkshop lacks the extractor). Reuses existing
  `code_edges_to_known_graph()`. Update module docstring + `__all__`.
- `src/pg_raggraph/chunking.py` — in `_chunk_via_chunkshop`, for `symbol_aware`
  call `extract_symbol_graph`, attach `callees` per chunk, stash edges on
  `chunks[0].metadata["__code_edges__"]`.
- `src/pg_raggraph/__init__.py` — in `_ingest_one_content`, pop `__code_edges__`,
  convert via `code_edges_to_known_graph`, merge into the known-graph args.
- `tests/unit/test_code_relationships.py` — **new**: `extract_symbol_graph`
  behavior + the finalize→`code_edges_to_known_graph` linchpin guard.
- `tests/unit/test_chunking.py` — add symbol_aware callees/edges-stash test.
- `tests/integration/test_code_graph.py` — add symbol_aware-ingest-populates-graph
  + distinctness + bare-name-collision xfail.
- `docs/cookbook/chunkshop-integration.md` — Pattern D auto-populates callees +
  code graph; requires the language's tree-sitter grammar.

---

## Task 1: Add tree-sitter as a test dependency

**Files:**
- Modify: `pyproject.toml` (the `dev` extra, lines 54-63)

- [ ] **Step 1: Add the grammar deps to the `dev` extra**

In `pyproject.toml`, change the `dev` list to add the two tree-sitter packages:

```toml
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.5",
    "coverage>=7.0",
    "beautifulsoup4>=4.14.3",
    "lede>=0.4.5",
    "lede-spacy[synonyms]>=0.4.5",
    "spacy>=3.7",
    # Code-graph tests need chunkshop's tree-sitter parse path; regex fallback
    # collapses symbol spans to one line and starves per-chunk call extraction.
    "tree-sitter>=0.25",
    "tree-sitter-python>=0.25",
]
```

- [ ] **Step 2: Install**

Run: `uv pip install 'tree-sitter>=0.25' 'tree-sitter-python>=0.25'`
Expected: `Installed ... tree-sitter ... tree-sitter-python ...` (or "already satisfied").

- [ ] **Step 3: Verify the grammar loads**

Run: `uv run python -c "import tree_sitter_python, tree_sitter; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "test: add tree-sitter + tree-sitter-python dev deps for code-graph tests"
```

---

## Task 2: `extract_symbol_graph()` in the chunkshop bridge

**Files:**
- Modify: `src/pg_raggraph/chunkshop_bridge.py`
- Test: `tests/unit/test_code_relationships.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_code_relationships.py`:

```python
"""Unit tests for the in-process symbol-graph extraction seam (#74/#75)."""

from __future__ import annotations

import pytest

from pg_raggraph.chunkshop_bridge import (
    code_edges_to_known_graph,
    extract_symbol_graph,
)

chunkshop = pytest.importorskip("chunkshop")
chunkshop_config = pytest.importorskip("chunkshop.config")
pytest.importorskip("tree_sitter_python")  # regex fallback degrades parses

pytestmark = pytest.mark.skipif(
    not hasattr(chunkshop_config, "SymbolAwareChunker"),
    reason="chunkshop build does not expose SymbolAwareChunker",
)

_CODE_SRC = '''\
def helper(x):
    return x + 1


def runner(y):
    return helper(y) * 2


class Base:
    pass


class Child(Base):
    def go(self):
        return runner(3)
'''


def _symbol_chunks(src: str, source_path: str = "sample.py"):
    from chunkshop.chunkers import load_chunker
    from chunkshop.config import SymbolAwareChunker as SymCfg
    from chunkshop.sources.base import Document

    doc = Document(
        id=source_path,
        content=src,
        title="sample",
        metadata={"source_path": source_path},
    )
    return load_chunker(SymCfg(type="symbol_aware", max_chars=4000)).chunk(doc)


def test_extract_symbol_graph_callees_and_edges():
    cs_chunks = _symbol_chunks(_CODE_SRC)
    sg = extract_symbol_graph(cs_chunks, source_path="sample.py", project_id="sample.py")
    assert sg is not None
    assert len(sg.callees_by_index) == len(cs_chunks)

    # The chunk that defines `runner` records a call to `helper`.
    runner_idx = next(
        i for i, c in enumerate(cs_chunks) if (c.metadata or {}).get("fqn") == "sample.runner"
    )
    runner_callees = {d["name"] for d in sg.callees_by_index[runner_idx]}
    assert "helper" in runner_callees

    edge_set = {(e["edge_type"], e["src_fqn"], e["dst_fqn"]) for e in sg.edges}
    assert ("CALLS", "sample.runner", "sample.helper") in edge_set
    assert ("INHERITS", "sample.Child", "sample.Base") in edge_set


def test_extract_symbol_graph_none_when_extractor_unavailable(monkeypatch):
    import pg_raggraph.chunkshop_bridge as bridge

    real_import = __import__

    def _block(name, *args, **kwargs):
        if name == "chunkshop.extractors":
            raise ImportError("simulated: no extractor in this chunkshop build")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _block)
    assert bridge.extract_symbol_graph(_symbol_chunks(_CODE_SRC), source_path="x.py") is None


def test_finalize_edges_feed_code_edges_to_known_graph():
    # The linchpin: finalize()-shaped edge dicts map cleanly via the EXISTING
    # Pattern C mapper. Hand-crafted so this is pure (no chunkshop needed at run).
    edges = [
        {
            "edge_type": "CALLS",
            "src_fqn": "m.runner",
            "dst_fqn": "m.helper",
            "src_node_id": "node-aaa",
            "dst_node_id": "node-bbb",
            "confidence": 0.9,
            "evidence": {"line": 6, "snippet": "return helper(y)", "resolution": "intra_file"},
        },
        {
            "edge_type": "INHERITS",
            "src_fqn": "m.Child",
            "dst_fqn": "m.Base",
            "src_node_id": "node-ccc",
            "dst_node_id": "node-ddd",
            "confidence": 0.9,
            "evidence": {"resolution": "unique_name"},
        },
    ]
    entities, rels = code_edges_to_known_graph(edges)
    names = {e["name"] for e in entities}
    assert names == {"m.runner", "m.helper", "m.Child", "m.Base"}
    assert all(e["entity_type"] == "CODE_SYMBOL" for e in entities)
    rel_set = {(r["src"], r["dst"], r["rel_type"]) for r in rels}
    assert ("m.runner", "m.helper", "CALLS") in rel_set
    assert ("m.Child", "m.Base", "INHERITS") in rel_set
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_code_relationships.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract_symbol_graph'` (the
`code_edges_to_known_graph` import already exists; `extract_symbol_graph` does not).

- [ ] **Step 3: Implement `SymbolGraph` + `extract_symbol_graph`**

In `src/pg_raggraph/chunkshop_bridge.py`, add the `dataclass` import at the top
(after `from __future__ import annotations`):

```python
from dataclasses import dataclass, field
```

Update the module docstring's first paragraph to mention both patterns:

```python
"""Bridge chunkshop into ``GraphRAG`` ingest.

Two shapes:

- **Pattern C** — chunkshop runs its own pipeline and writes a Postgres sink
  (chunks + a ``code_edges`` table); pg-raggraph consumes the stored rows
  through ``pre_chunked`` ingest and ``code_edges_to_known_graph``.
- **Pattern D** (in-process) — pg-raggraph drives chunkshop's ``symbol_aware``
  chunker itself; ``extract_symbol_graph`` runs chunkshop's
  ``CodeRelationshipsExtractor`` over the produced chunks to attach per-chunk
  ``callees`` and resolve ``CALLS``/``INHERITS``/``IMPLEMENTS`` edges, which then
  flow through the same ``code_edges_to_known_graph`` seam.
"""
```

Add the new symbols (place after `code_edges_to_known_graph`):

```python
@dataclass
class SymbolGraph:
    """Output of :func:`extract_symbol_graph`.

    ``callees_by_index`` is parallel to the input ``cs_chunks`` — entry ``i`` is
    the per-chunk callee list (``{name, line, snippet, resolved_intra_file}``) for
    chunk ``i`` (#74). ``edges`` is the raw ``finalize()`` edge list (#75),
    key-compatible with :func:`code_edges_to_known_graph`.
    """

    callees_by_index: list[list[dict[str, Any]]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)


def extract_symbol_graph(
    cs_chunks,
    *,
    source_path: str | None = None,
    project_id: str = "doc",
) -> "SymbolGraph | None":
    """Run chunkshop's CodeRelationshipsExtractor over symbol_aware chunks.

    Per-chunk ``extract()`` attaches callees and accumulates symbols + call
    sites; ``finalize()`` resolves them into edges. Per-file scope (one call per
    document). Returns ``None`` when the installed chunkshop lacks the extractor,
    so older builds degrade gracefully (callees absent, no code graph, no crash).

    Correct results require chunkshop's tree-sitter parse path; the regex
    fallback collapses symbol spans and starves per-chunk extraction.
    """
    try:
        from chunkshop.config import CodeRelationshipsExtractor as _CodeRelCfg
        from chunkshop.extractors import load_extractor

        extractor = load_extractor(_CodeRelCfg(type="code_relationships"))
    except (ImportError, AttributeError, TypeError, ValueError):
        return None
    if not callable(getattr(extractor, "extract", None)) or not callable(
        getattr(extractor, "finalize", None)
    ):
        return None

    callees_by_index: list[list[dict[str, Any]]] = []
    for cs in cs_chunks:
        meta = cs.metadata or {}
        result = extractor.extract(
            cs.original_content or "",
            source_path=meta.get("source_path") or source_path,
            language=meta.get("language"),
        )
        callees_by_index.append(list((result.metadata or {}).get("callees", [])))
    edges = list(extractor.finalize(project_id=project_id or "doc"))
    return SymbolGraph(callees_by_index=callees_by_index, edges=edges)
```

Add both names to `__all__`:

```python
__all__ = [
    "SymbolGraph",
    "attach_code_edges",
    "code_edges_to_known_graph",
    "extract_symbol_graph",
    "fetch_code_edges_from_table",
    "fetch_records_from_table",
    "rows_to_records",
    # ...keep any existing entries...
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_code_relationships.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/chunkshop_bridge.py tests/unit/test_code_relationships.py
git commit -m "feat: extract_symbol_graph runs chunkshop code-rel extractor (#74/#75)"
```

---

## Task 3: Attach callees + stash edges in `_chunk_via_chunkshop`

**Files:**
- Modify: `src/pg_raggraph/chunking.py` (`_chunk_via_chunkshop`, lines ~250-274)
- Test: `tests/unit/test_chunking.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_chunking.py` (the chunkshop section already imports
`pytest`, `chunkshop`, `chunkshop_config`, `chunk_document`, `PGRGConfig`):

```python
_CODE_GRAPH_SRC = '''\
def helper(x):
    return x + 1


def runner(y):
    return helper(y) * 2


class Base:
    pass


class Child(Base):
    def go(self):
        return runner(3)
'''


@pytest.mark.skipif(
    not hasattr(chunkshop_config, "SymbolAwareChunker"),
    reason="chunkshop build does not expose SymbolAwareChunker",
)
def test_symbol_aware_attaches_callees_and_stashes_edges():
    pytest.importorskip("tree_sitter_python")  # regex fallback degrades parses
    cfg = PGRGConfig(chunk_strategy="chunkshop:symbol_aware", chunk_max_tokens=512)
    chunks = chunk_document(_CODE_GRAPH_SRC, source_path="sample.py", config=cfg)
    assert chunks

    # #74: the chunk defining `runner` carries a callee for `helper`.
    runner_chunk = next(c for c in chunks if c["metadata"].get("fqn") == "sample.runner")
    assert any(d["name"] == "helper" for d in runner_chunk["metadata"].get("callees", []))

    # #75: resolved edges are stashed on the first chunk for the ingest path.
    edges = chunks[0]["metadata"].get("__code_edges__")
    assert isinstance(edges, list) and edges
    edge_set = {(e["edge_type"], e["src_fqn"], e["dst_fqn"]) for e in edges}
    assert ("CALLS", "sample.runner", "sample.helper") in edge_set
    assert ("INHERITS", "sample.Child", "sample.Base") in edge_set
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_chunking.py::test_symbol_aware_attaches_callees_and_stashes_edges -v`
Expected: FAIL — `KeyError`/`assert` on missing `callees` / `__code_edges__`.

- [ ] **Step 3: Implement the wiring**

In `src/pg_raggraph/chunking.py`, modify `_chunk_via_chunkshop`. Find:

```python
    chunker = load_chunker(chunker_cfg_map[name])
    cs_chunks = chunker.chunk(doc)

    result: list[dict] = []
    for cs in cs_chunks:
        body = (cs.original_content or "").strip()
        if not body:
            continue
        embedded = (cs.embedded_content or body).strip()
        meta = dict(cs.metadata or {})
        # Preserve our standard metadata keys alongside chunkshop's.
        meta.setdefault("source_path", source_path)
        meta.setdefault("chunk_index", len(result))
        meta.setdefault("chunkshop_strategy", name)
        meta.setdefault("chunkshop_seq_num", cs.seq_num)
        result.append(
            {
                "content": body,
                "embedded_content": embedded,
                "token_count": token_count(embedded),
                "content_hash": content_hash(body),
                "metadata": meta,
            }
        )
    return result
```

Replace it with:

```python
    chunker = load_chunker(chunker_cfg_map[name])
    cs_chunks = chunker.chunk(doc)

    # #74/#75: for symbol_aware, run chunkshop's CodeRelationshipsExtractor over
    # the produced chunks. Attaches per-chunk callees and resolves CALLS/
    # INHERITS/IMPLEMENTS edges. Feature-guarded + lazy inside the bridge; None
    # on older chunkshop builds (callees/edges simply absent).
    symbol_graph = None
    if name == "symbol_aware":
        from pg_raggraph import chunkshop_bridge

        symbol_graph = chunkshop_bridge.extract_symbol_graph(
            cs_chunks, source_path=source_path, project_id=source_path or "doc"
        )

    result: list[dict] = []
    for idx, cs in enumerate(cs_chunks):
        body = (cs.original_content or "").strip()
        if not body:
            continue
        embedded = (cs.embedded_content or body).strip()
        meta = dict(cs.metadata or {})
        # Preserve our standard metadata keys alongside chunkshop's.
        meta.setdefault("source_path", source_path)
        meta.setdefault("chunk_index", len(result))
        meta.setdefault("chunkshop_strategy", name)
        meta.setdefault("chunkshop_seq_num", cs.seq_num)
        if symbol_graph is not None:
            meta["callees"] = symbol_graph.callees_by_index[idx]
        result.append(
            {
                "content": body,
                "embedded_content": embedded,
                "token_count": token_count(embedded),
                "content_hash": content_hash(body),
                "metadata": meta,
            }
        )

    # Stash resolved code edges on the first chunk so _ingest_one_content can
    # materialize the code graph. Popped + stripped there before the chunk row
    # is written, so this private key never persists.
    if symbol_graph is not None and symbol_graph.edges and result:
        result[0]["metadata"]["__code_edges__"] = symbol_graph.edges
    return result
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_chunking.py::test_symbol_aware_attaches_callees_and_stashes_edges -v`
Expected: PASS

- [ ] **Step 5: Run the full chunking suite (no regressions)**

Run: `uv run pytest tests/unit/test_chunking.py -q`
Expected: PASS (all existing chunkshop delegation tests still green).

- [ ] **Step 6: Commit**

```bash
git add src/pg_raggraph/chunking.py tests/unit/test_chunking.py
git commit -m "feat: symbol_aware chunking attaches callees + stashes code edges (#74)"
```

---

## Task 4: Materialize the code graph in `_ingest_one_content`

**Files:**
- Modify: `src/pg_raggraph/__init__.py` (`_ingest_one_content`, just after the
  `pre_chunked`/`else` branch converges — right after `chunk_embeddings` is set,
  ~line 1198, before the "Extract entities/relationships via LLM" comment)
- Test: `tests/integration/test_code_graph.py`

- [ ] **Step 1: Write the failing integration test**

Append to `tests/integration/test_code_graph.py` (it already defines `DSN`, `NS`,
`cg`, `GraphRAG`, `_fresh`):

```python
_INGEST_SRC = '''\
def helper(x):
    return x + 1


def runner(y):
    return helper(y) * 2


class Base:
    pass


class Child(Base):
    def go(self):
        return runner(3)
'''


@pytest.mark.asyncio
async def test_symbol_aware_ingest_populates_code_graph():
    pytest.importorskip("chunkshop")
    pytest.importorskip("tree_sitter_python")
    rag = GraphRAG(dsn=DSN, namespace=NS, chunk_strategy="chunkshop:symbol_aware")
    await _fresh(rag)
    try:
        await rag.ingest_records(
            [{"text": _INGEST_SRC, "source_id": "sample.py", "skip_llm": True}],
            namespace=NS,
        )
        # runner CALLS helper → helper has caller runner; runner has callee helper.
        helper_impact = await cg.code_impact(rag._db, "sample.helper", namespace=NS, depth=1)
        assert helper_impact.found
        assert "sample.runner" in [e.fqn for e in helper_impact.callers]

        runner_impact = await cg.code_impact(rag._db, "sample.runner", namespace=NS, depth=1)
        assert "sample.helper" in [e.fqn for e in runner_impact.callees]

        # Child INHERITS Base → Base has incoming Child.
        base_impact = await cg.code_impact(rag._db, "sample.Base", namespace=NS, depth=1)
        assert "sample.Child" in [e.fqn for e in base_impact.callers]
    finally:
        await rag.delete(NS)
        await rag.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_code_graph.py::test_symbol_aware_ingest_populates_code_graph -v`
Expected: FAIL — `assert helper_impact.found` is False (the graph is empty; no
writer wires `__code_edges__` into entities/relationships yet).
(Requires PostgreSQL on 5434 — `docker compose up -d postgres` first.)

- [ ] **Step 3: Implement the ingest wiring**

In `src/pg_raggraph/__init__.py`, locate the convergence point in
`_ingest_one_content` — immediately after the `pre_chunked`/`else` block that sets
`chunks` and `chunk_embeddings`, and before the
`# Extract entities/relationships via LLM` comment (~line 1200). Insert:

```python
        # #75: symbol_aware chunking stashes resolved code edges on chunk[0].
        # Convert them to CODE_SYMBOL entities + CALLS/INHERITS/IMPLEMENTS edges
        # via the same bridge mapper Pattern C uses, and merge into the known
        # graph. Pop unconditionally so the bulky edge list never persists on the
        # chunk row; only materialize on the synchronous (non-deferred) path.
        code_edges = chunks[0]["metadata"].pop("__code_edges__", None) if chunks else None
        if code_edges and not defer_extraction:
            from pg_raggraph import chunkshop_bridge

            _code_entities, _code_rels = chunkshop_bridge.code_edges_to_known_graph(code_edges)
            known_entities = (known_entities or []) + _code_entities
            known_relationships = (known_relationships or []) + _code_rels
```

(`known_entities` and `known_relationships` are the method's own parameters;
reassigning them here feeds the existing merge blocks below unchanged.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/integration/test_code_graph.py::test_symbol_aware_ingest_populates_code_graph -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/__init__.py tests/integration/test_code_graph.py
git commit -m "feat: symbol_aware ingest populates CODE_SYMBOL graph for code_impact (#75)"
```

---

## Task 5: Distinctness + bare-name-collision guard tests

**Files:**
- Test: `tests/integration/test_code_graph.py`

- [ ] **Step 1: Write the tests**

Append to `tests/integration/test_code_graph.py`:

```python
_DISTINCT_SRC = '''\
def alpha():
    return omega()


def omega():
    return 1
'''

_COLLISION_SRC = '''\
def process():
    return process_batch()


def process_batch():
    return 2
'''


@pytest.mark.asyncio
async def test_distinct_code_symbols_stay_separate():
    pytest.importorskip("chunkshop")
    pytest.importorskip("tree_sitter_python")
    rag = GraphRAG(dsn=DSN, namespace=NS, chunk_strategy="chunkshop:symbol_aware")
    await _fresh(rag)
    try:
        await rag.ingest_records(
            [{"text": _DISTINCT_SRC, "source_id": "distinct.py", "skip_llm": True}],
            namespace=NS,
        )
        rows = await rag._db.fetch_all(
            "SELECT name FROM entities WHERE namespace = %s AND entity_type = 'CODE_SYMBOL' "
            "ORDER BY name",
            (NS,),
        )
        names = [r["name"] for r in rows]
        assert "distinct.alpha" in names
        assert "distinct.omega" in names
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.xfail(
    strict=False,
    reason="pre-existing resolve_entity pg_trgm+vector fuzzy-merge of code "
    "symbols sharing a bare name; tracked as a separate follow-up ticket",
)
@pytest.mark.asyncio
async def test_bare_name_collision_merge_risk():
    pytest.importorskip("chunkshop")
    pytest.importorskip("tree_sitter_python")
    rag = GraphRAG(dsn=DSN, namespace=NS, chunk_strategy="chunkshop:symbol_aware")
    await _fresh(rag)
    try:
        await rag.ingest_records(
            [{"text": _COLLISION_SRC, "source_id": "collide.py", "skip_llm": True}],
            namespace=NS,
        )
        rows = await rag._db.fetch_all(
            "SELECT name FROM entities WHERE namespace = %s AND entity_type = 'CODE_SYMBOL' "
            "AND name = ANY(%s)",
            (NS, ["collide.process", "collide.process_batch"]),
        )
        assert len(rows) == 2  # may fail today if fuzzy resolution merges them
    finally:
        await rag.delete(NS)
        await rag.close()
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/integration/test_code_graph.py -k "distinct or collision" -v`
Expected: `test_distinct_code_symbols_stay_separate` PASS;
`test_bare_name_collision_merge_risk` XPASS or XFAIL (either is acceptable — the
suite stays green; `strict=False` tolerates both).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_code_graph.py
git commit -m "test: code-symbol distinctness + bare-name-collision merge-risk probe"
```

---

## Task 6: Documentation

**Files:**
- Modify: `docs/cookbook/chunkshop-integration.md`

- [ ] **Step 1: Read the existing Pattern D section**

Run: `uv run grep -n "Pattern D\|symbol_aware\|callees\|code_impact" docs/cookbook/chunkshop-integration.md`
Read the surrounding Pattern D section so the addition matches the doc's voice.

- [ ] **Step 2: Add a "code intelligence" note to the Pattern D section**

Insert a short subsection under Pattern D stating:

```markdown
#### Code intelligence (`symbol_aware`)

`chunk_strategy="chunkshop:symbol_aware"` now runs chunkshop's
`CodeRelationshipsExtractor` automatically during ingest:

- Each chunk carries `metadata["callees"]` — `[{name, line, snippet,
  resolved_intra_file}]` tree-sitter call sites for that symbol.
- `CODE_SYMBOL` entities and `CALLS`/`INHERITS`/`IMPLEMENTS` relationships are
  written to the graph, so `rag.code_impact("<fqn>")` returns real callers and
  callees with no extra steps.

Resolution is **per file** (intra-file edges are precise; cross-file calls are
best-effort). Correct results require the source language's **tree-sitter
grammar** to be importable (e.g. `pip install tree-sitter tree-sitter-python`);
without it chunkshop silently falls back to a regex parser and the call graph
degrades.
```

- [ ] **Step 3: Commit**

```bash
git add docs/cookbook/chunkshop-integration.md
git commit -m "docs: Pattern D symbol_aware auto-populates callees + code graph"
```

---

## Task 7: Full-suite verification

- [ ] **Step 1: Lint**

Run: `uv run ruff check src/pg_raggraph/chunkshop_bridge.py src/pg_raggraph/chunking.py src/pg_raggraph/__init__.py tests/unit/test_code_relationships.py`
Expected: `All checks passed!` (fix any findings, re-run).

- [ ] **Step 2: Unit suite**

Run: `uv run pytest tests/unit/test_code_relationships.py tests/unit/test_chunking.py -q`
Expected: PASS.

- [ ] **Step 3: Integration suite (DB on 5434)**

Run: `uv run pytest tests/integration/test_code_graph.py -q`
Expected: PASS (collision probe XFAIL/XPASS).

- [ ] **Step 4: Regression sweep (no collateral breakage)**

Run: `uv run pytest tests/unit -q`
Expected: PASS.

- [ ] **Step 5: Final commit if any lint fixes were made**

```bash
git add -A
git commit -m "chore: lint + verification for code-symbol graph ingest (#74, #75)"
```

---

## Self-Review Notes (for the implementer)

- **Spec coverage:** #74 callees → Task 3; #75 graph rows → Task 4 (reusing
  `code_edges_to_known_graph` from Task 2); always-on for `symbol_aware` → Tasks
  3+4 gate on `name == "symbol_aware"` / the stashed key; per-file scope → one
  extractor per document in `extract_symbol_graph`; tree-sitter requirement →
  Task 1 + importorskip guards; fuzzy-merge concern → Task 5 xfail; docs → Task 6.
- **Naming consistency:** `extract_symbol_graph`, `SymbolGraph`,
  `callees_by_index`, `edges`, and the private key `__code_edges__` are used
  identically across Tasks 2-4.
- **No new write code (#75):** Task 4 only converts + merges into the existing
  `known_entities`/`known_relationships` path; the transaction writer is unchanged.
- **defer_extraction:** the key is always popped (strip) but only converted when
  `not defer_extraction` — deferred ingests keep callees in chunk metadata but
  skip graph rows (documented non-goal).
