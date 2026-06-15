# Code-Graph Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an out-of-band primitive + CLI (`pgrg backfill-code-graph`) that rebuilds the chunkshop `CALLS`/`INHERITS`/`IMPLEMENTS` code graph for documents ingested with `defer_extraction=True`, so fast code-KB ingest no longer loses the call graph (#81).

**Architecture:** When a code doc (`chunk_strategy="chunkshop:symbol_aware"`) is ingested deferred, persist its raw file content to a new durable `code_backfill_stage` table inside the same per-doc transaction. A new `backfill.backfill_code_graph()` primitive runs a per-namespace corpus pass — rebuild a `CorpusCodeGraph` from the staged content (re-parse → `accumulate` → spill), call the existing `_write_corpus_code_graph` resolver (reusing all #76 spill machinery), then delete the staged rows. The stage table doubles as the code-graph work queue, keyed independently of `documents.graph_status` (which `pgrg extract` owns), so entity backfill and code-graph backfill never contend.

**Tech Stack:** Python 3.12 (async), PostgreSQL 16 + pgvector/pg_trgm, psycopg3 async, chunkshop (`symbol_aware` + `code_relationships` extractor), Click CLI, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-06-15-code-graph-backfill-design.md`

---

## File Structure

- **Create** `src/pg_raggraph/sql/migrations/015_code_backfill_stage.sql` — the durable stage table (auto-applied by the migration runner on connect).
- **Modify** `src/pg_raggraph/sql/schema.sql` — mirror the table for fresh installs (as `code_calls_stage` is mirrored).
- **Modify** `src/pg_raggraph/__init__.py` — ingest-time persistence hook in `_ingest_one_content` (inside the existing per-doc transaction, right after the `documents` INSERT).
- **Modify** `src/pg_raggraph/backfill.py` — add `CodeGraphStats` dataclass + `backfill_code_graph()` primitive.
- **Modify** `src/pg_raggraph/cli.py` — add the `backfill-code-graph` command.
- **Create** `tests/integration/test_backfill_code_graph.py` — all behavioral tests.
- **Modify** `docs/cookbook/background-extraction.md` — document the code-KB flow.

---

## Task 1: Durable stage table (migration + schema)

**Files:**
- Create: `src/pg_raggraph/sql/migrations/015_code_backfill_stage.sql`
- Modify: `src/pg_raggraph/sql/schema.sql` (append after the `code_calls_stage` block, ~line 296)
- Test: `tests/integration/test_backfill_code_graph.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_backfill_code_graph.py` with the shared header and the table-existence test:

```python
import os

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph import code_graph as cg

# NOTE: `from pg_raggraph.backfill import backfill_code_graph` is added in Task 3,
# when the primitive exists. Keeping it out now lets Task 1's test run green.

DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
pytestmark = pytest.mark.integration

NS = "test_backfill_code_graph"

_PKG_A = "def helper(x):\n    return x + 1\n"
_PKG_B = "from a import helper\n\n\ndef run(y):\n    return helper(y) * 2\n"
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


async def _fresh(rag):
    await rag.connect()
    await rag.delete(NS)  # clear any prior run's data (cascades to stage table)


@pytest.mark.asyncio
async def test_code_backfill_stage_table_exists():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    try:
        reg = await rag._db.fetch_one("SELECT to_regclass('code_backfill_stage') AS t")
        assert reg["t"] is not None
        cols = await rag._db.fetch_all(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'code_backfill_stage'"
        )
        names = {c["column_name"] for c in cols}
        assert {"document_id", "namespace", "content", "language", "source_path"} <= names
    finally:
        await rag.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_backfill_code_graph.py::test_code_backfill_stage_table_exists -v`
Expected: FAIL — `assert None is not None` (the table does not exist yet).

- [ ] **Step 3: Write the migration**

Create `src/pg_raggraph/sql/migrations/015_code_backfill_stage.sql`:

```sql
-- Durable staging for out-of-band code-graph backfill (#81).
--
-- When ingest_records(..., defer_extraction=True) runs over code docs
-- (chunk_strategy="chunkshop:symbol_aware"), the corpus code-graph resolver is
-- skipped so the call returns fast. The raw file content is persisted here so a
-- later `pgrg backfill-code-graph` run can re-parse it, rebuild the cross-file
-- symbol index, and write the CALLS/INHERITS/IMPLEMENTS edges.
--
-- LOGGED (a normal table), UNLIKE code_calls_stage: this content must survive
-- BETWEEN the deferred ingest and a later backfill run — possibly across a
-- crash/restart. An UNLOGGED table is truncated on crash recovery, which would
-- silently lose the content. The table doubles as the code-graph work queue,
-- keyed independently of documents.graph_status (which `pgrg extract` owns), so
-- entity backfill and code-graph backfill never contend.
CREATE TABLE IF NOT EXISTS code_backfill_stage (
    document_id BIGINT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    namespace   TEXT NOT NULL,
    content     TEXT NOT NULL,
    language    TEXT,
    source_path TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_code_backfill_stage_ns
    ON code_backfill_stage (namespace);
```

- [ ] **Step 4: Mirror the table into schema.sql**

In `src/pg_raggraph/sql/schema.sql`, immediately after the `code_calls_stage` index (the `CREATE INDEX ... idx_code_calls_stage_run` statement, ~line 296), add:

```sql

-- Durable staging for out-of-band code-graph backfill (#81). Holds the raw file
-- content of code docs ingested with defer_extraction=True so a later
-- `pgrg backfill-code-graph` run can re-parse it and rebuild the code graph.
-- LOGGED (not UNLOGGED like code_calls_stage): the content must survive between
-- the deferred ingest and the backfill run. See migrations/015_code_backfill_stage.sql.
CREATE TABLE IF NOT EXISTS code_backfill_stage (
    document_id BIGINT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    namespace   TEXT NOT NULL,
    content     TEXT NOT NULL,
    language    TEXT,
    source_path TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_code_backfill_stage_ns
    ON code_backfill_stage (namespace);
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_backfill_code_graph.py::test_code_backfill_stage_table_exists -v`
Expected: PASS (the migration auto-applies on `connect()`).

- [ ] **Step 6: Commit**

```bash
git add src/pg_raggraph/sql/migrations/015_code_backfill_stage.sql src/pg_raggraph/sql/schema.sql tests/integration/test_backfill_code_graph.py
git commit -m "feat(#81): add durable code_backfill_stage table"
```

---

## Task 2: Persist raw content at deferred ingest

**Files:**
- Modify: `src/pg_raggraph/__init__.py` (`_ingest_one_content`, right after the `documents` INSERT that sets `doc_id`, ~line 1499)
- Test: `tests/integration/test_backfill_code_graph.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_backfill_code_graph.py`:

```python
@pytest.mark.asyncio
async def test_deferred_code_doc_persists_raw_content():
    pytest.importorskip("chunkshop")
    pytest.importorskip("tree_sitter_python")
    rag = GraphRAG(dsn=DSN, namespace=NS, chunk_strategy="chunkshop:symbol_aware")
    await _fresh(rag)
    try:
        await rag.ingest_records(
            [{"text": _PKG_A, "source_id": "a.py", "skip_llm": True}],
            namespace=NS,
            defer_extraction=True,
        )
        rows = await rag._db.fetch_all(
            "SELECT content, language FROM code_backfill_stage WHERE namespace = %s",
            (NS,),
        )
        assert len(rows) == 1
        assert rows[0]["content"] == _PKG_A  # byte-faithful raw file content
        assert rows[0]["language"]  # chunkshop tagged the .py doc with a language
        # deferred → no code edges written inline
        n = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM relationships "
            "WHERE namespace = %s AND rel_type = 'CALLS'",
            (NS,),
        )
        assert n["n"] == 0
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_deferred_prose_doc_does_not_persist():
    rag = GraphRAG(dsn=DSN, namespace=NS)  # default chunker, not symbol_aware
    await _fresh(rag)
    try:
        await rag.ingest_records(
            [{"text": "The quick brown fox. Plain prose, no code here.",
              "source_id": "doc.txt", "skip_llm": True}],
            namespace=NS,
            defer_extraction=True,
        )
        n = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM code_backfill_stage WHERE namespace = %s", (NS,)
        )
        assert n["n"] == 0  # no `language` metadata → not a code doc → not staged
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_non_deferred_code_doc_does_not_stage():
    pytest.importorskip("chunkshop")
    pytest.importorskip("tree_sitter_python")
    rag = GraphRAG(dsn=DSN, namespace=NS, chunk_strategy="chunkshop:symbol_aware")
    await _fresh(rag)
    try:
        await rag.ingest_records(
            [{"text": _PKG_A, "source_id": "a.py", "skip_llm": True}],
            namespace=NS,  # NOT deferred → edges materialize inline, nothing staged
        )
        n = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM code_backfill_stage WHERE namespace = %s", (NS,)
        )
        assert n["n"] == 0
    finally:
        await rag.delete(NS)
        await rag.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_backfill_code_graph.py -k "persists_raw_content or does_not_persist or does_not_stage" -v`
Expected: `test_deferred_code_doc_persists_raw_content` FAILS with `assert 0 == 1` (no row staged). The two negative tests PASS already (nothing writes the table yet) — that is fine; they guard against over-staging once the hook exists.

- [ ] **Step 3: Add the persistence hook**

In `src/pg_raggraph/__init__.py`, locate the end of the `documents` INSERT in `_ingest_one_content` — the call `doc_id = await tx.insert_returning_id(... RETURNING id ...)` (ends ~line 1499). Immediately after that statement (still inside the `async with self.db.transaction() as tx:` block, before the `if version_label or supersedes_doc ...` block), insert:

```python
            # #81: persist raw file content for deferred CODE docs so the code
            # graph (CALLS/INHERITS/IMPLEMENTS) can be rebuilt out-of-band by
            # `pgrg backfill-code-graph`. Gate: deferred + a symbol_aware code
            # doc (those chunks carry `language`) + not pre_chunked (Pattern C's
            # `content` is joined-chunk text, not a faithful file — out of scope).
            # Atomic with the doc — staged content lands iff the doc does. The
            # table is LOGGED so it survives until a later backfill run.
            if defer_extraction and _code_lang and pre_chunked is None:
                await tx.execute(
                    "INSERT INTO code_backfill_stage "
                    "(document_id, namespace, content, language, source_path) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (document_id) DO UPDATE SET "
                    "  content = EXCLUDED.content, "
                    "  language = EXCLUDED.language, "
                    "  source_path = EXCLUDED.source_path",
                    (doc_id, ns, content, _code_lang, file_path),
                )
```

Note: `_code_lang`, `content`, `ns`, `file_path`, `defer_extraction`, `pre_chunked`, and `tx` are all already in scope at this point (`_code_lang` is computed ~line 1246; the rest are function params / the transaction handle).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_backfill_code_graph.py -k "persists_raw_content or does_not_persist or does_not_stage" -v`
Expected: all three PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/__init__.py tests/integration/test_backfill_code_graph.py
git commit -m "feat(#81): stage raw content for deferred code docs at ingest"
```

---

## Task 3: `backfill_code_graph` primitive

**Files:**
- Modify: `src/pg_raggraph/backfill.py` (add `CodeGraphStats` after `ExtractStats` ~line 38; add `backfill_code_graph` after `extract_documents` ~line 200)
- Test: `tests/integration/test_backfill_code_graph.py`

- [ ] **Step 1: Write the failing tests**

First, add the imports near the top of `tests/integration/test_backfill_code_graph.py` (replace the Task-1 NOTE comment about deferred imports):

```python
from pg_raggraph import code_graph as cg
from pg_raggraph.backfill import backfill_code_graph
```

Then append the tests:

```python
@pytest.mark.asyncio
async def test_backfill_rebuilds_cross_file_code_graph():
    pytest.importorskip("chunkshop")
    pytest.importorskip("tree_sitter_python")
    rag = GraphRAG(dsn=DSN, namespace=NS, chunk_strategy="chunkshop:symbol_aware")
    await _fresh(rag)
    try:
        records = [
            {"text": _PKG_A, "source_id": "a.py", "skip_llm": True},
            {"text": _PKG_B, "source_id": "b.py", "skip_llm": True},
        ]
        await rag.ingest_records(
            records, namespace=NS, cross_file_code_graph=True, defer_extraction=True
        )
        # deferred → no edges yet; both files staged
        pre = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM relationships WHERE namespace = %s", (NS,)
        )
        assert pre["n"] == 0
        staged = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM code_backfill_stage WHERE namespace = %s", (NS,)
        )
        assert staged["n"] == 2

        stats = await backfill_code_graph(rag, NS)
        assert stats.docs == 2
        assert stats.edges >= 1

        # cross-file edge resolved: b.run CALLS a.helper
        impact = await cg.code_impact(rag._db, "a.helper", namespace=NS, depth=1)
        assert impact.found
        assert "b.run" in [e.fqn for e in impact.callers]

        row = await rag._db.fetch_one(
            "SELECT r.properties->>'resolved_intra_file' AS rif FROM relationships r "
            "JOIN entities s ON s.id = r.src_id JOIN entities d ON d.id = r.dst_id "
            "WHERE r.namespace = %s AND s.name = 'b.run' AND d.name = 'a.helper'",
            (NS,),
        )
        assert row is not None and row["rif"] == "false"

        # staging + spill both cleared
        staged2 = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM code_backfill_stage WHERE namespace = %s", (NS,)
        )
        assert staged2["n"] == 0
        spill = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM code_calls_stage WHERE namespace = %s", (NS,)
        )
        assert spill["n"] == 0
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_backfill_rebuilds_intra_file_code_graph():
    pytest.importorskip("chunkshop")
    pytest.importorskip("tree_sitter_python")
    rag = GraphRAG(dsn=DSN, namespace=NS, chunk_strategy="chunkshop:symbol_aware")
    await _fresh(rag)
    try:
        await rag.ingest_records(
            [{"text": _INGEST_SRC, "source_id": "sample.py", "skip_llm": True}],
            namespace=NS,
            defer_extraction=True,  # no cross_file flag → single-doc corpus = intra-file
        )
        stats = await backfill_code_graph(rag, NS)
        assert stats.docs == 1

        runner_impact = await cg.code_impact(rag._db, "sample.runner", namespace=NS, depth=1)
        assert "sample.helper" in [e.fqn for e in runner_impact.callees]
        base_impact = await cg.code_impact(rag._db, "sample.Base", namespace=NS, depth=1)
        assert "sample.Child" in [e.fqn for e in base_impact.callers]
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_backfill_rerun_is_noop():
    pytest.importorskip("chunkshop")
    pytest.importorskip("tree_sitter_python")
    rag = GraphRAG(dsn=DSN, namespace=NS, chunk_strategy="chunkshop:symbol_aware")
    await _fresh(rag)
    try:
        await rag.ingest_records(
            [
                {"text": _PKG_A, "source_id": "a.py", "skip_llm": True},
                {"text": _PKG_B, "source_id": "b.py", "skip_llm": True},
            ],
            namespace=NS, cross_file_code_graph=True, defer_extraction=True,
        )
        await backfill_code_graph(rag, NS)
        first = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM relationships WHERE namespace = %s", (NS,)
        )
        # staging cleared after success → second run claims nothing, edges unchanged
        stats2 = await backfill_code_graph(rag, NS)
        assert stats2.docs == 0
        second = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM relationships WHERE namespace = %s", (NS,)
        )
        assert second["n"] == first["n"]
    finally:
        await rag.delete(NS)
        await rag.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_backfill_code_graph.py -k "rebuilds or rerun_is_noop" -v`
Expected: FAIL — `AttributeError`/`ImportError` for `backfill_code_graph`, or `stats` unusable (function not defined yet).

- [ ] **Step 3: Add `CodeGraphStats`**

In `src/pg_raggraph/backfill.py`, after the `ExtractStats` dataclass (ends ~line 38), add:

```python
@dataclass
class CodeGraphStats:
    """Per-call code-graph backfill outcome.

    ``docs`` is staged docs resolved, ``edges`` the relationships written,
    ``namespaces`` how many namespaces had staged work, ``skipped`` docs left
    in place because chunkshop's extractor was unavailable.
    """

    namespaces: int = 0
    docs: int = 0
    edges: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
```

- [ ] **Step 4: Add the `backfill_code_graph` primitive**

In `src/pg_raggraph/backfill.py`, after `extract_documents` (ends ~line 200, before `_extract_one`), add:

```python
async def backfill_code_graph(
    rag: GraphRAG,
    namespace: str | None,
    *,
    batch_size: int = 5000,
) -> CodeGraphStats:
    """Rebuild the chunkshop code graph for docs staged by deferred ingest (#81).

    A per-namespace corpus pass: re-parse each staged code doc into a shared
    ``CorpusCodeGraph`` (spilling call sites the #76 way), then call the existing
    ``rag._write_corpus_code_graph`` resolver to write the CALLS/INHERITS/
    IMPLEMENTS edges, then delete the staged rows.

    Cross-file resolution is namespace-scoped (symbols never cross namespaces),
    so ``namespace=None`` runs one independent pass per namespace found in
    ``code_backfill_stage``.

    Resumable: staged rows are deleted only after the resolve succeeds, so a
    crash mid-pass leaves them for a re-run (edge upserts are idempotent). This
    is a single-worker corpus *finalize* — concurrent runs over one namespace are
    correct but duplicate work. It never touches ``documents.graph_status``;
    generic entity backfill (``extract_documents``) owns that independently.
    """
    import uuid

    from pg_raggraph.chunkshop_bridge import CorpusCodeGraph

    stats = CodeGraphStats()

    if namespace is None:
        ns_rows = await rag.db.fetch_all(
            "SELECT DISTINCT namespace FROM code_backfill_stage ORDER BY namespace"
        )
        target_namespaces = [r["namespace"] for r in ns_rows]
    else:
        target_namespaces = [namespace]

    for ns in target_namespaces:
        id_rows = await rag.db.fetch_all(
            "SELECT document_id FROM code_backfill_stage WHERE namespace = %s "
            "ORDER BY document_id",
            (ns,),
        )
        doc_ids = [r["document_id"] for r in id_rows]
        if not doc_ids:
            continue
        stats.namespaces += 1

        ccg = CorpusCodeGraph()
        if not ccg.available:
            logger.warning(
                "chunkshop code extractor unavailable; leaving %d staged code "
                "doc(s) in namespace %r for a later run",
                len(doc_ids),
                ns,
            )
            stats.skipped += len(doc_ids)
            continue

        run_id = uuid.uuid4().hex
        t0 = time.perf_counter()
        # Stream content one doc at a time so peak memory is O(one doc + symbol
        # index + spill batch), never O(corpus text) — the #76 memory ethos.
        for doc_id in doc_ids:
            row = await rag.db.fetch_one(
                "SELECT content, language, source_path FROM code_backfill_stage "
                "WHERE document_id = %s",
                (doc_id,),
            )
            if row is None:  # raced with a concurrent delete — skip
                continue
            calls = await ccg.accumulate(
                row["content"], source_path=row["source_path"], language=row["language"]
            )
            if calls:
                await rag._spill_code_calls(ns, run_id, calls)

        n_rels = 0
        if ccg.count:
            n_rels = await rag._write_corpus_code_graph(
                ns, ccg, run_id, batch_size=batch_size
            )

        await rag.db.execute(
            "DELETE FROM code_backfill_stage WHERE document_id = ANY(%s)",
            (doc_ids,),
        )
        stats.docs += len(doc_ids)
        stats.edges += n_rels

        emit = getattr(rag, "_emit_metric", None)
        if emit is not None:
            emit(
                "pgrg.backfill.code_graph",
                namespace=ns,
                docs=len(doc_ids),
                edges=n_rels,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

    return stats
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_backfill_code_graph.py -k "rebuilds or rerun_is_noop" -v`
Expected: all three PASS. (`test_backfill_rebuilds_cross_file_code_graph` is the #81 acceptance test — it proves the deferred path reaches byte-identical edges to the synchronous `test_cross_file_code_graph_resolves_callers`.)

- [ ] **Step 6: Commit**

```bash
git add src/pg_raggraph/backfill.py tests/integration/test_backfill_code_graph.py
git commit -m "feat(#81): add backfill_code_graph corpus primitive"
```

---

## Task 4: `pgrg backfill-code-graph` CLI command

**Files:**
- Modify: `src/pg_raggraph/cli.py` (add a new `@main.command` after the `extract` command, ~line 460)
- Test: `tests/integration/test_backfill_code_graph.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_backfill_code_graph.py`:

```python
def test_cli_backfill_code_graph():
    import asyncio

    from click.testing import CliRunner

    from pg_raggraph.cli import main

    pytest.importorskip("chunkshop")
    pytest.importorskip("tree_sitter_python")

    async def _setup():
        rag = GraphRAG(dsn=DSN, namespace=NS, chunk_strategy="chunkshop:symbol_aware")
        await rag.connect()
        await rag.delete(NS)
        await rag.ingest_records(
            [
                {"text": _PKG_A, "source_id": "a.py", "skip_llm": True},
                {"text": _PKG_B, "source_id": "b.py", "skip_llm": True},
            ],
            namespace=NS, cross_file_code_graph=True, defer_extraction=True,
        )
        await rag.close()

    asyncio.run(_setup())
    runner = CliRunner()
    try:
        res = runner.invoke(main, ["--db", DSN, "backfill-code-graph", "-n", NS])
        assert res.exit_code == 0, res.output
        assert "edges" in res.output.lower()
    finally:

        async def _teardown():
            rag = GraphRAG(dsn=DSN, namespace=NS)
            await rag.connect()
            await rag.delete(NS)
            await rag.close()

        asyncio.run(_teardown())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_backfill_code_graph.py::test_cli_backfill_code_graph -v`
Expected: FAIL — `res.exit_code != 0` (Click reports "No such command 'backfill-code-graph'").

- [ ] **Step 3: Add the CLI command**

In `src/pg_raggraph/cli.py`, after the `extract` command function (after its `run_async(_extract())` try/except, ~line 460), add:

```python
@main.command("backfill-code-graph")
@click.option(
    "-n", "--namespace", default=None,
    help="Namespace to resolve (default: every namespace with staged code docs)",
)
@click.option(
    "--batch-size", default=5000, type=int, show_default=True,
    help="Call sites drained per resolve batch (#76 spill drain)",
)
@click.pass_context
def backfill_code_graph_cmd(ctx, namespace, batch_size):
    """Rebuild the chunkshop code graph for docs ingested with defer_extraction.

    Corpus-level finalize: claims staged code docs per namespace, rebuilds the
    cross-file symbol index, and writes CALLS/INHERITS/IMPLEMENTS edges. Run one
    worker per namespace; re-run to resume after a crash. Orthogonal to
    `pgrg extract` (which backfills generic entities and owns graph_status).
    """
    if batch_size < 1:
        raise click.BadParameter("--batch-size must be >= 1")

    from pg_raggraph.backfill import backfill_code_graph

    async def _run():
        kwargs = dict(ctx.obj["kwargs"])
        if namespace:
            kwargs["namespace"] = namespace
        rag = GraphRAG(**kwargs)
        await rag.connect()
        try:
            stats = await backfill_code_graph(rag, namespace, batch_size=batch_size)
            msg = (
                f"Code graph: {stats.edges} edges across {stats.docs} doc(s) "
                f"in {stats.namespaces} namespace(s)"
            )
            if stats.skipped:
                msg += f", {stats.skipped} skipped (chunkshop extractor unavailable)"
            click.echo(msg)
        finally:
            await rag.close()

    try:
        run_async(_run())
    except Exception as e:
        _handle_error(e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_backfill_code_graph.py::test_cli_backfill_code_graph -v`
Expected: PASS (exit 0, output contains "edges").

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/cli.py tests/integration/test_backfill_code_graph.py
git commit -m "feat(#81): add pgrg backfill-code-graph CLI command"
```

---

## Task 5: Document the code-KB flow

**Files:**
- Modify: `docs/cookbook/background-extraction.md`

- [ ] **Step 1: Read the current cookbook to find the right insertion point**

Run: `sed -n '1,60p' docs/cookbook/background-extraction.md`
Identify where deferred ingest + `pgrg extract` is described (the entity-backfill flow).

- [ ] **Step 2: Add a code-KB section**

Append a new section to `docs/cookbook/background-extraction.md`:

````markdown
## Code KBs: backfilling the call graph

`pgrg extract` backfills **generic entities** (the GraphRAG prose graph). It does
**not** rebuild the chunkshop **code graph** (`CALLS`/`INHERITS`/`IMPLEMENTS`),
which is a corpus-level resolve. For code KBs ingested with
`chunk_strategy="chunkshop:symbol_aware"` and `defer_extraction=True`, run a
second, orthogonal pass:

```bash
# 1. fast deferred ingest (chunks + embeddings land; graph deferred)
#    -> docs are graph_status='pending' AND their raw content is staged
# 2. generic entity backfill (owns graph_status)
pgrg extract --namespace myrepo
# 3. code-graph backfill (rebuilds CALLS/INHERITS/IMPLEMENTS from staged content)
pgrg backfill-code-graph --namespace myrepo
```

`backfill-code-graph` is a **corpus finalize**: it re-parses the staged file
content per namespace, rebuilds the cross-file symbol index, and writes the
resolved edges. Run **one worker per namespace**; it is crash-resumable (re-run
to finish an interrupted pass) and idempotent. It never changes `graph_status`,
so it composes freely with `pgrg extract` in either order.

The raw content is held in a durable `code_backfill_stage` table only until the
backfill completes, then deleted. Programmatic equivalent:

```python
from pg_raggraph.backfill import backfill_code_graph

stats = await backfill_code_graph(rag, "myrepo")
print(stats.edges, "edges across", stats.docs, "docs")
```
````

- [ ] **Step 3: Commit**

```bash
git add docs/cookbook/background-extraction.md
git commit -m "docs(#81): document code-graph backfill flow"
```

---

## Task 6: Full verification + lint

**Files:** none (verification only)

- [ ] **Step 1: Lint**

Run: `uv run ruff check src/pg_raggraph/backfill.py src/pg_raggraph/cli.py src/pg_raggraph/__init__.py tests/integration/test_backfill_code_graph.py`
Expected: no errors. If ruff flags formatting, run `uv run ruff format` on those files and re-check.

- [ ] **Step 2: Run the full new test file**

Run: `uv run pytest tests/integration/test_backfill_code_graph.py -v`
Expected: all tests PASS (chunkshop-gated ones run if chunkshop + tree_sitter_python are installed; otherwise skip — that is acceptable).

- [ ] **Step 3: Run the existing code-graph + backfill suites for regressions**

Run: `uv run pytest tests/integration/test_code_graph.py tests/integration/test_backfill.py tests/unit/ -q`
Expected: all pass (no regression from the ingest hook or the new primitive). `tests/unit/test_instructions_sync.py` must stay green — this change adds a CLI command, not an MCP tool, so the MCP House Rule three-file sync is not triggered.

- [ ] **Step 4: Final commit (if ruff format changed anything)**

```bash
git add -A
git commit -m "chore(#81): ruff format" || echo "nothing to format"
```

---

## Notes for the executor

- **Do not** edit released migrations; `015_code_backfill_stage.sql` is new and auto-applies on the next `connect()`.
- The chunkshop-gated tests need `chunkshop` + `tree_sitter_python` installed (the repo's dev env has them — the existing `test_code_graph.py` cross-file tests rely on the same). If they skip in your env, run the non-gated `test_code_backfill_stage_table_exists` and `test_deferred_prose_doc_does_not_persist` at minimum, and flag the gated skips in your summary.
- A release version bump (e.g. the next `0.5.0aN`) is **out of scope** for this plan — leave it to the maintainer's release step.
