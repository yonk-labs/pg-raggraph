# Code docs: safe vector-reuse staging + code concept prompt — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pg-raggraph able to (1) build the deferred code graph for a code doc whose chunks+vectors were reused via `pre_chunked` (today it silently skips), and (2) offer a code-tuned LLM concept prompt so a code KB can be dual-level (structural + conceptual).

**Architecture:** Capability 1 adds an optional `code_source_content` param: when a code doc is ingested with `pre_chunked` (so the doc-level `content` is joined-chunk text, not a faithful file), the caller passes the faithful original source, which is what gets staged into `code_backfill_stage` for `backfill_code_graph` to re-parse. Loud-fails if a reused code doc omits it (prevents silent graph loss). Capability 2 adds a `"code"` extraction prompt; enabling concept extraction itself is the consumer's existing config (`skip_extraction=False`), no routing change.

**Tech Stack:** Python 3.12+, asyncpg/psycopg, pgvector, pytest + pytest-asyncio, ruff, uv. Integration tests require PostgreSQL on `localhost:5434` (`postgresql://postgres:postgres@localhost:5434/pg_raggraph`).

## Global Constraints

- **Fast ingest is sacrosanct.** No synchronous LLM call or synchronous graph resolution may be added to the ingest path. All graph/concept work stays in the deferred workers (`backfill.py`).
- **Default behavior unchanged.** Both capabilities are opt-in. With no new args / existing config, ingest behaves byte-identically to today.
- **Library is consumer-agnostic.** pg-raggraph reasons about *code language + defer_extraction + config*, never the string `"code-aware"` (that's a bento concept).
- **Atomicity preserved.** Staging stays inside the per-doc ingest transaction (`tx`), exactly as today.

---

### Task 0: Branch

- [ ] **Step 1: Create a feature branch off main**

Run:
```bash
cd /home/yonk/yonk-tools/pg-raggraph
git checkout -b feat/code-docs-reuse-staging
```
Expected: `Switched to a new branch 'feat/code-docs-reuse-staging'`

---

### Task 1: Capability 1 — stage faithful source for reused code docs

**Files:**
- Modify: `src/pg_raggraph/__init__.py` — `ingest_doc` signature (~line 1119) and the staging block (`1508-1518`)
- Modify: `src/pg_raggraph/__init__.py` — `ingest_records` record handling (~line 918 read, ~line 975 call)
- Test: `tests/integration/test_code_reuse_staging.py` (new)

**Interfaces:**
- Produces: `ingest_doc(..., code_source_content: str | None = None)` — new keyword-only param threaded after `defer_extraction`. `ingest_records` reads it from each record dict via key `"code_source_content"`.
- Behavior: for a code-language doc with `defer_extraction=True`, `code_backfill_stage` is populated. When `pre_chunked is None`, staged content is `content` (today's behavior). When `pre_chunked` is set, staged content is `code_source_content`; if that is falsy, raise `ValueError`.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_code_reuse_staging.py`:

```python
import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.asyncio

# A tiny faithful python "file" and one symbol chunk carrying language metadata.
FAITHFUL_SRC = "import os\n\n\ndef greet(name):\n    return f'hi {name}'\n"
SYMBOL_CHUNK_CONTENT = "def greet(name):\n    return f'hi {name}'\n"


def _pre_chunked(dim: int):
    return [{
        "content": SYMBOL_CHUNK_CONTENT,
        "embedding": [0.0] * dim,
        "metadata": {"language": "python", "fqn": "mod.greet"},
    }]


async def _fetch_stage(rag, doc_path):
    return await rag.db.fetch_all(
        "SELECT content, language, source_path FROM code_backfill_stage "
        "WHERE source_path = %s",
        (doc_path,),
    )


async def test_reused_code_doc_stages_faithful_source(graphrag: GraphRAG):
    dim = graphrag.config.embedding_dim
    rec = {
        "id": "f1.py",
        "content": SYMBOL_CHUNK_CONTENT,            # joined-chunk text (NOT faithful)
        "source_path": "f1.py",
        "pre_chunked": _pre_chunked(dim),
        "code_source_content": FAITHFUL_SRC,        # the faithful file
        "defer_extraction": True,
    }
    await graphrag.ingest_records([rec])

    rows = await _fetch_stage(graphrag, "f1.py")
    assert len(rows) == 1
    assert rows[0]["language"] == "python"
    assert rows[0]["content"] == FAITHFUL_SRC       # faithful, not the joined chunk


async def test_reused_code_doc_without_faithful_source_raises(graphrag: GraphRAG):
    dim = graphrag.config.embedding_dim
    rec = {
        "id": "f2.py",
        "content": SYMBOL_CHUNK_CONTENT,
        "source_path": "f2.py",
        "pre_chunked": _pre_chunked(dim),
        # no code_source_content
        "defer_extraction": True,
    }
    with pytest.raises(ValueError, match="code_source_content"):
        await graphrag.ingest_records([rec])
```

> Note: reuse the existing integration `graphrag` fixture. If none exists under
> `tests/integration/conftest.py`, mirror the setup in
> `tests/integration/test_chunkshop_bridge.py` (it constructs a `GraphRAG` against
> the 5434 DB and bootstraps schema). The `language` key on the chunk metadata is
> what sets `_code_lang` (`__init__.py:1246`).

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_code_reuse_staging.py -v`
Expected: both FAIL — first because no `code_backfill_stage` row is written on the `pre_chunked` path (gate excludes it today), second because no `ValueError` is raised.

- [ ] **Step 3: Add the `code_source_content` param to `ingest_doc`**

In `src/pg_raggraph/__init__.py`, add to the `ingest_doc` signature (after `defer_extraction: bool = False`, ~line 1119):

```python
        defer_extraction: bool = False,
        code_source_content: str | None = None,
```

- [ ] **Step 4: Replace the staging gate to use faithful content + loud-fail**

In `src/pg_raggraph/__init__.py`, replace the block at `1508-1518`:

```python
            if defer_extraction and _code_lang:
                # pre_chunked `content` is joined-chunk text, not a faithful file;
                # backfill_code_graph re-parses with tree-sitter, which needs the
                # real source. Callers reusing chunks must pass code_source_content.
                stage_content = content if pre_chunked is None else code_source_content
                if pre_chunked is not None and not stage_content:
                    raise ValueError(
                        "code doc ingested with pre_chunked must also pass "
                        "code_source_content (the faithful original file) so the "
                        "deferred code graph can be rebuilt"
                    )
                await tx.execute(
                    "INSERT INTO code_backfill_stage "
                    "(document_id, namespace, content, language, source_path) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (document_id) DO UPDATE SET "
                    "  content = EXCLUDED.content, "
                    "  language = EXCLUDED.language, "
                    "  source_path = EXCLUDED.source_path",
                    (doc_id, ns, stage_content, _code_lang, file_path),
                )
```

- [ ] **Step 5: Thread `code_source_content` through `ingest_records`**

In `src/pg_raggraph/__init__.py`, near the per-record reads (~line 918, beside `rec_pre_chunked = rec.get("pre_chunked")`):

```python
                        rec_code_source_content = rec.get("code_source_content")
```

and at the `ingest_doc(...)` call (~line 975, beside `pre_chunked=rec_pre_chunked,`):

```python
                            code_source_content=rec_code_source_content,
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/integration/test_code_reuse_staging.py -v`
Expected: both PASS.

- [ ] **Step 7: Run the existing ingest/backfill tests to confirm no regression**

Run: `uv run pytest tests/integration/test_chunkshop_bridge.py tests/ -k "backfill or ingest or code" -q`
Expected: PASS (default `pre_chunked is None` path unchanged; new param defaults to None).

- [ ] **Step 8: Lint + commit**

Run:
```bash
uv run ruff check src/pg_raggraph/__init__.py tests/integration/test_code_reuse_staging.py
git add src/pg_raggraph/__init__.py tests/integration/test_code_reuse_staging.py
git commit -m "feat(ingest): stage faithful source for reused code docs (code_source_content)"
```

---

### Task 2: Capability 2 — code-tuned concept extraction prompt

**Files:**
- Modify: `src/pg_raggraph/extraction.py` — add `CODE_EXTRACTION_PROMPT`, extend `get_prompt` (`208-212`)
- Modify: `src/pg_raggraph/config.py` — widen the `extraction_prompt` Literal (`103`)
- Test: `tests/unit/test_extraction_prompts.py` (new or extend if present)

**Interfaces:**
- Produces: `get_prompt("code")` returns the code prompt; `PGRGConfig.extraction_prompt` accepts `"code"`. Enabling concept extraction on a code KB remains the consumer's existing config choice (`skip_extraction=False`, `extraction_prompt="code"`); no routing change in `backfill._extract_one`.

- [ ] **Step 1: Write the failing unit test**

Create/extend `tests/unit/test_extraction_prompts.py`:

```python
from pg_raggraph.extraction import get_prompt


def test_code_prompt_is_distinct_and_code_focused():
    code = get_prompt("code")
    assert code != get_prompt("default")
    assert code != get_prompt("dev")
    # code-structure vocabulary, not incident/ticket vocabulary
    assert "module" in code.lower()
    assert "depends_on" in code.lower()


def test_unknown_prompt_falls_back_to_default():
    assert get_prompt("nope") == get_prompt("default")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_extraction_prompts.py -v`
Expected: FAIL — `get_prompt("code")` currently returns the default prompt (equal to it).

- [ ] **Step 3: Add the code prompt and wire `get_prompt`**

In `src/pg_raggraph/extraction.py`, add after `DEV_EXTRACTION_PROMPT` (after line 205):

```python
CODE_EXTRACTION_PROMPT = """\
You are an expert at extracting a CONCEPTUAL knowledge graph from source code.
A separate deterministic pass already captures call/inherit/implement structure,
so DO NOT restate call edges. Extract the intent and architecture the code implies.

Return JSON with this structure:
{"entities": [...], "relationships": [...]}

Entity fields: name, entity_type, description
Relationship fields: source, target, rel_type, description, weight

Preferred entity types:
- module      (a file or package and its responsibility)
- component   (a cohesive unit: a service, client, store, parser)
- concept     (a domain idea the code implements: authentication, caching, retry)
- library     (external dependency imported/used)
- config      (settings, env vars, feature flags)

Preferred relationship types:
- IMPLEMENTS   (module/component -> concept)
- DEPENDS_ON   (module/component -> library/component)
- CONFIGURES   (module -> config)
- PART_OF      (module -> component; component -> system)
- RELATED_TO   (fallback for weaker links)

Rules:
- Extract meaning, not mechanics — concepts/responsibilities, not who-calls-whom.
- Entity names stable across files (normalize "auth" vs "Auth").
- Only what the code makes explicit (names, docstrings, imports, comments).
- Keep descriptions to one sentence."""
```

Then replace `get_prompt` (`208-212`):

```python
def get_prompt(name: str) -> str:
    """Get an extraction prompt by name."""
    if name == "dev":
        return DEV_EXTRACTION_PROMPT
    if name == "code":
        return CODE_EXTRACTION_PROMPT
    return EXTRACTION_SYSTEM_PROMPT
```

- [ ] **Step 4: Widen the config Literal**

In `src/pg_raggraph/config.py`, change line 103:

```python
    extraction_prompt: Literal["default", "dev", "code"] = "default"
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_extraction_prompts.py -v`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

Run:
```bash
uv run ruff check src/pg_raggraph/extraction.py src/pg_raggraph/config.py tests/unit/test_extraction_prompts.py
git add src/pg_raggraph/extraction.py src/pg_raggraph/config.py tests/unit/test_extraction_prompts.py
git commit -m "feat(extraction): add code-tuned concept prompt (extraction_prompt='code')"
```

---

## Validation & handoff (not code tasks)

- **Capability 1 parity (do before bento enables reuse):** ingest the same code repo twice — once self-chunked, once via `pre_chunked` + `code_source_content` — and assert `backfill_code_graph` resolves the **same CALLS/INHERITS/IMPLEMENTS edge set**. This is the proof that reuse loses no graph. Library-level; can use a fixture repo here.
- **Capability 2 is a hypothesis — eval, don't assume.** Run a code-KB eval (concept questions: "how does auth work", "what depends on the cache") comparing structural-only vs structural+concept (`skip_extraction=False`, `extraction_prompt="code"`). The eval data/harness likely lives bento-side — coordinate. Keep concept extraction off by default until it shows a lift.
- **Coexistence/dedup check:** when both layers run, confirm a concept entity and a `CODE_SYMBOL` of the same name stay distinct (resolution keys on name+type). Verify in the eval run; if `resolve_entity` merges across `entity_type`, open a follow-up.

## Downstream contract (for the bento agent — not pg-raggraph work)

- **Reuse code vectors:** send `pre_chunked` (chunks+vectors+`metadata.language`+`fqn`) **and** `code_source_content` = the faithful original file. Keep `defer_extraction=True`. Activation still gated by bento's reuse flag + C1 + the #872 int8 decision.
- **Concept layer:** set `skip_extraction=False` + `extraction_prompt="code"` for the KB (off by default). Surface the extra deferred backlog in `backfill-status`.

## Open question carried from spec

- **Vendoring:** how do these library changes reach `bento/backend/tools/pg-raggraph` (subtree / version bump / copy)? Confirm before the bento agent depends on them.
