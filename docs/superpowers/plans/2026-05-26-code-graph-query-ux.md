# Code-Graph Query UX (`code-impact`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `code-impact <fqn>` operation (direct + transitive callers/callees with evidence) over the existing `CODE_SYMBOL` graph, exposed as a `code_graph.py` module, a `GraphRAG.code_impact()` API, and a CLI command; plus FQN-matched enrichment of `CODE_SYMBOL` entity descriptions from chunkshop summaries.

**Architecture:** Pure read-side traversal over the existing `entities`/`relationships` tables using two recursive CTEs (outgoing = callees, incoming = callers), cycle-safe via a visited-id path array, namespace-scoped. No schema changes. Rendering is a pure function for no-DB unit testing. The summary enrichment threads an `fqn->summary` map (built from imported chunk metadata) into the existing code-edge import functions.

**Tech Stack:** Python 3.12+, psycopg3 async, Click CLI, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-26-code-graph-query-ux-design.md`

---

## Key facts from the codebase

- `relationships` columns: `id, namespace, src_id, dst_id, rel_type, weight, description, properties (jsonb), retracted, ...`. Indexes `idx_rel_src_type (src_id, rel_type)` and `idx_rel_dst_type (dst_id, rel_type)`.
- `entities` columns: `id, namespace, name, entity_type, description, embedding, properties`. `UNIQUE(namespace, name)`. `embedding` is nullable — tests can insert symbols without embeddings.
- `code_edges_to_known_graph` (`chunkshop_bridge.py:99`) already sets a relationship's `description` to the evidence snippet (`evidence.get("snippet") or evidence.get("resolution") or ""`), `weight` to the edge confidence, and `properties.evidence` to the full evidence object. Entity description defaults to `f"Code symbol {fqn}"`.
- `Database` (`db.py`): async `db.execute(sql, params)`, `db.fetch_all(sql, params)`, `db.fetch_one(sql, params)` returning **dict** rows.
- CLI root group is `main`; async bridge helper is `run_async(coro)`; commands build `GraphRAG(**ctx.obj["kwargs"])`. Namespace resolves as `namespace or self.config.namespace`.
- Integration tests use the shared DB (`PGRG_TEST_DSN`, port 5437) isolated by a unique **namespace** with teardown — `code-impact` is namespace-scoped and non-destructive, so no throwaway database is needed (unlike the embedding migration).

---

## File Structure

- **Create** `src/pg_raggraph/code_graph.py` — `CodeEdge`/`CodeImpact` dataclasses, `CODE_REL_TYPES`, `code_impact()` traversal, `render_impact_tree()` pure renderer.
- **Modify** `src/pg_raggraph/__init__.py` — `GraphRAG.code_impact(...)` wrapper.
- **Modify** `src/pg_raggraph/cli.py` — `code-impact` command; thread `summaries` into the `ingest-chunkshop-table --with-code-edges` branch (Task 6).
- **Modify** `src/pg_raggraph/chunkshop_bridge.py` — `summaries_by_fqn()`; `summaries=` param on `code_edges_to_known_graph`, `attach_code_edges`, `fetch_code_edges_from_table` (Task 6).
- **Create** `tests/integration/test_code_graph.py`, `tests/unit/test_code_graph.py`, `tests/unit/test_code_graph_cli.py`.
- **Modify** `tests/integration/test_chunkshop_bridge.py` — enrichment test (Task 6).

---

## Task 1: `code_graph.py` — dataclasses + `code_impact` traversal

**Files:**
- Create: `src/pg_raggraph/code_graph.py`
- Test: `tests/integration/test_code_graph.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_code_graph.py`:

```python
import os
import pytest
from pg_raggraph import GraphRAG
from pg_raggraph import code_graph as cg

DSN = os.environ.get("PGRG_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="requires PGRG_TEST_DSN")

NS = "test_code_graph"


async def _seed(rag, edges):
    """edges: list of (src_fqn, dst_fqn, rel_type, weight, snippet). Inserts
    CODE_SYMBOL entities (idempotent) and CALLS-style relationships."""
    db = rag._db
    names = {n for e in edges for n in (e[0], e[1])}
    ids = {}
    for name in names:
        row = await db.fetch_one(
            "INSERT INTO entities (namespace, name, entity_type, description) "
            "VALUES (%s, %s, 'CODE_SYMBOL', %s) "
            "ON CONFLICT (namespace, name) DO UPDATE SET name = EXCLUDED.name "
            "RETURNING id",
            (NS, name, f"Code symbol {name}"),
        )
        ids[name] = row["id"]
    for src, dst, rel, weight, snippet in edges:
        await db.execute(
            "INSERT INTO relationships (namespace, src_id, dst_id, rel_type, weight, "
            "description, properties) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (NS, ids[src], ids[dst], rel, weight, snippet, "{}"),
        )
    return ids


async def _fresh(rag):
    await rag.connect()
    await rag.delete(NS)  # clear any prior run's data in this namespace


@pytest.mark.asyncio
async def test_code_impact_direct_callers_and_callees():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        # b is called by a; b calls c.
        await _seed(rag, [
            ("a", "b", "CALLS", 1.0, "a() calls b()"),
            ("b", "c", "CALLS", 1.0, "b() calls c()"),
        ])
        res = await cg.code_impact(rag._db, "b", namespace=NS, depth=1)
        assert res.found
        assert [(e.fqn, e.rel_type, e.evidence, e.depth) for e in res.callers] == [
            ("a", "CALLS", "a() calls b()", 1)
        ]
        assert [(e.fqn, e.rel_type, e.evidence, e.depth) for e in res.callees] == [
            ("c", "CALLS", "b() calls c()", 1)
        ]
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_code_impact_transitive_depth():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        # chain: a -> b -> c -> d  (callees of a at depth 3)
        await _seed(rag, [
            ("a", "b", "CALLS", 1.0, ""),
            ("b", "c", "CALLS", 1.0, ""),
            ("c", "d", "CALLS", 1.0, ""),
        ])
        res = await cg.code_impact(rag._db, "a", namespace=NS, depth=2)
        callee_fqns = {(e.fqn, e.depth) for e in res.callees}
        assert ("b", 1) in callee_fqns
        assert ("c", 2) in callee_fqns
        assert all(e.depth <= 2 for e in res.callees)  # d (depth 3) excluded
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_code_impact_cycle_terminates():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        await _seed(rag, [
            ("a", "b", "CALLS", 1.0, ""),
            ("b", "a", "CALLS", 1.0, ""),
        ])
        res = await cg.code_impact(rag._db, "a", namespace=NS, depth=10)
        assert res.found  # does not hang; cycle guard bounds the walk
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_code_impact_not_found():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        res = await cg.code_impact(rag._db, "nope.missing", namespace=NS, depth=1)
        assert res.found is False
        assert res.callers == [] and res.callees == []
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_code_impact_min_confidence_filters():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        await _seed(rag, [
            ("a", "b", "CALLS", 0.3, "weak"),
            ("a", "c", "CALLS", 0.9, "strong"),
        ])
        res = await cg.code_impact(rag._db, "a", namespace=NS, depth=1, min_confidence=0.5)
        assert {e.fqn for e in res.callees} == {"c"}
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_code_impact_depth_must_be_positive():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        with pytest.raises(ValueError):
            await cg.code_impact(rag._db, "a", namespace=NS, depth=0)
    finally:
        await rag.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_code_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pg_raggraph.code_graph'`.

- [ ] **Step 3: Create the module**

Create `src/pg_raggraph/code_graph.py`:

```python
"""Read-side code-intelligence queries over the CODE_SYMBOL graph.

code_impact answers "who calls this symbol" (callers, incoming edges) and "what
does it call" (callees, outgoing edges) by recursive traversal of the existing
``relationships`` table. Namespace-scoped; no schema changes. See
docs/superpowers/specs/2026-05-26-code-graph-query-ux-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass

CODE_REL_TYPES = ("CALLS", "INHERITS", "IMPLEMENTS")

# Outgoing walk (callees): start at edges where src_id = seed; the "other" node
# is dst_id; follow dst_id -> next src_id. Cycle guard on src_id path.
_CALLEES_SQL = """
WITH RECURSIVE walk AS (
    SELECT r.dst_id AS other_id, r.rel_type,
           COALESCE(NULLIF(r.description, ''),
                    r.properties->'evidence'->>'snippet', '') AS evidence,
           1 AS depth, ARRAY[r.src_id] AS path
    FROM relationships r
    WHERE r.namespace = %(ns)s AND r.src_id = %(seed)s
      AND r.rel_type = ANY(%(rel_types)s) AND r.weight >= %(min_conf)s
      AND NOT COALESCE(r.retracted, FALSE)
  UNION ALL
    SELECT r.dst_id, r.rel_type,
           COALESCE(NULLIF(r.description, ''),
                    r.properties->'evidence'->>'snippet', ''),
           w.depth + 1, w.path || r.src_id
    FROM relationships r
    JOIN walk w ON r.src_id = w.other_id
    WHERE r.namespace = %(ns)s AND w.depth < %(depth)s
      AND r.rel_type = ANY(%(rel_types)s) AND r.weight >= %(min_conf)s
      AND NOT COALESCE(r.retracted, FALSE)
      AND NOT (r.src_id = ANY(w.path))
)
SELECT e.name AS fqn, walk.rel_type, walk.evidence, walk.depth
FROM walk JOIN entities e ON e.id = walk.other_id
ORDER BY walk.depth, e.name
"""

# Incoming walk (callers): start at edges where dst_id = seed; the "other" node
# is src_id; follow src_id -> next dst_id. Cycle guard on dst_id path.
_CALLERS_SQL = """
WITH RECURSIVE walk AS (
    SELECT r.src_id AS other_id, r.rel_type,
           COALESCE(NULLIF(r.description, ''),
                    r.properties->'evidence'->>'snippet', '') AS evidence,
           1 AS depth, ARRAY[r.dst_id] AS path
    FROM relationships r
    WHERE r.namespace = %(ns)s AND r.dst_id = %(seed)s
      AND r.rel_type = ANY(%(rel_types)s) AND r.weight >= %(min_conf)s
      AND NOT COALESCE(r.retracted, FALSE)
  UNION ALL
    SELECT r.src_id, r.rel_type,
           COALESCE(NULLIF(r.description, ''),
                    r.properties->'evidence'->>'snippet', ''),
           w.depth + 1, w.path || r.dst_id
    FROM relationships r
    JOIN walk w ON r.dst_id = w.other_id
    WHERE r.namespace = %(ns)s AND w.depth < %(depth)s
      AND r.rel_type = ANY(%(rel_types)s) AND r.weight >= %(min_conf)s
      AND NOT COALESCE(r.retracted, FALSE)
      AND NOT (r.dst_id = ANY(w.path))
)
SELECT e.name AS fqn, walk.rel_type, walk.evidence, walk.depth
FROM walk JOIN entities e ON e.id = walk.other_id
ORDER BY walk.depth, e.name
"""


@dataclass
class CodeEdge:
    fqn: str
    rel_type: str
    evidence: str
    depth: int


@dataclass
class CodeImpact:
    fqn: str
    found: bool
    callers: list[CodeEdge]
    callees: list[CodeEdge]


def _dedupe(rows) -> list[CodeEdge]:
    """Keep the first (shallowest, name-sorted) edge per fqn."""
    seen: set[str] = set()
    out: list[CodeEdge] = []
    for r in rows:
        if r["fqn"] in seen:
            continue
        seen.add(r["fqn"])
        out.append(CodeEdge(fqn=r["fqn"], rel_type=r["rel_type"],
                            evidence=r["evidence"] or "", depth=r["depth"]))
    return out


async def code_impact(
    db, fqn: str, *, namespace: str, depth: int = 1, min_confidence: float = 0.0
) -> CodeImpact:
    if depth < 1:
        raise ValueError(f"depth must be >= 1, got {depth}")
    seed = await db.fetch_one(
        "SELECT id FROM entities "
        "WHERE namespace = %s AND name = %s AND entity_type = 'CODE_SYMBOL'",
        (namespace, fqn),
    )
    if not seed:
        return CodeImpact(fqn=fqn, found=False, callers=[], callees=[])
    params = {
        "ns": namespace,
        "seed": seed["id"],
        "rel_types": list(CODE_REL_TYPES),
        "min_conf": min_confidence,
        "depth": depth,
    }
    callees = _dedupe(await db.fetch_all(_CALLEES_SQL, params))
    callers = _dedupe(await db.fetch_all(_CALLERS_SQL, params))
    return CodeImpact(fqn=fqn, found=True, callers=callers, callees=callees)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_code_graph.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/pg_raggraph/code_graph.py tests/integration/test_code_graph.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/pg_raggraph/code_graph.py tests/integration/test_code_graph.py
git commit -m "feat: add code_impact graph traversal (code_graph module)"
```

---

## Task 2: `render_impact_tree` pure renderer

**Files:**
- Modify: `src/pg_raggraph/code_graph.py`
- Test: `tests/unit/test_code_graph.py`

- [ ] **Step 1: Write the failing unit test**

Create `tests/unit/test_code_graph.py`:

```python
from pg_raggraph.code_graph import CodeEdge, CodeImpact, render_impact_tree


def test_render_tree_with_callers_and_callees():
    res = CodeImpact(
        fqn="pkg.b",
        found=True,
        callers=[CodeEdge("pkg.a", "CALLS", "a() calls b()", 1)],
        callees=[CodeEdge("pkg.c", "CALLS", "", 1)],
    )
    out = render_impact_tree(res)
    assert "pkg.b" in out
    assert "callers:" in out
    assert "pkg.a" in out and "a() calls b()" in out
    assert "callees:" in out
    assert "pkg.c" in out


def test_render_tree_empty_sections_show_none():
    res = CodeImpact(fqn="pkg.x", found=True, callers=[], callees=[])
    out = render_impact_tree(res)
    assert out.count("(none)") == 2


def test_render_tree_marks_transitive_depth():
    res = CodeImpact(
        fqn="pkg.a", found=True, callers=[],
        callees=[CodeEdge("pkg.c", "CALLS", "", 2)],
    )
    out = render_impact_tree(res)
    assert "depth 2" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_code_graph.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_impact_tree'`.

- [ ] **Step 3: Add the renderer to `code_graph.py`**

Append to `src/pg_raggraph/code_graph.py`:

```python
def render_impact_tree(impact: CodeImpact) -> str:
    """Human-readable tree for ``code-impact``. Pure function (no DB)."""
    lines = [impact.fqn]
    for label, edges in (("callers", impact.callers), ("callees", impact.callees)):
        lines.append(f"  {label}:")
        if not edges:
            lines.append("    (none)")
            continue
        for e in edges:
            depth_note = f" (depth {e.depth})" if e.depth > 1 else ""
            ev = f'    "{e.evidence}"' if e.evidence else ""
            lines.append(f"    - {e.fqn}    {e.rel_type}{depth_note}{ev}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_code_graph.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/code_graph.py tests/unit/test_code_graph.py
git commit -m "feat: add render_impact_tree for code-impact output"
```

---

## Task 3: `GraphRAG.code_impact()` API

**Files:**
- Modify: `src/pg_raggraph/__init__.py`
- Test: `tests/integration/test_code_graph.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_code_graph.py`:

```python
@pytest.mark.asyncio
async def test_graphrag_code_impact_resolves_namespace_from_config():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        await _seed(rag, [("a", "b", "CALLS", 1.0, "a() calls b()")])
        res = await rag.code_impact("b")  # namespace from config
        assert res.found
        assert {e.fqn for e in res.callers} == {"a"}
    finally:
        await rag.delete(NS)
        await rag.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_code_graph.py::test_graphrag_code_impact_resolves_namespace_from_config -v`
Expected: FAIL — `AttributeError: 'GraphRAG' object has no attribute 'code_impact'`.

- [ ] **Step 3: Add the method to `GraphRAG`**

In `src/pg_raggraph/__init__.py`, add this method to the `GraphRAG` class (place it near `query`/`status`):

```python
    async def code_impact(
        self, fqn: str, *, namespace: str | None = None,
        depth: int = 1, min_confidence: float = 0.0,
    ):
        """Callers and callees of a CODE_SYMBOL by FQN. Returns a CodeImpact.

        See pg_raggraph.code_graph. Namespace defaults to the configured one.
        """
        from pg_raggraph.code_graph import code_impact as _code_impact

        ns = namespace or self.config.namespace
        return await _code_impact(
            self._db, fqn, namespace=ns, depth=depth, min_confidence=min_confidence
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_code_graph.py::test_graphrag_code_impact_resolves_namespace_from_config -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/__init__.py tests/integration/test_code_graph.py
git commit -m "feat: add GraphRAG.code_impact() API"
```

---

## Task 4: CLI `code-impact` command

**Files:**
- Modify: `src/pg_raggraph/cli.py`
- Test: `tests/unit/test_code_graph_cli.py`, `tests/integration/test_code_graph.py`

- [ ] **Step 1: Write the failing registration unit test**

Create `tests/unit/test_code_graph_cli.py`:

```python
from click.testing import CliRunner
from pg_raggraph.cli import main


def test_code_impact_command_registered():
    runner = CliRunner()
    result = runner.invoke(main, ["code-impact", "--help"])
    assert result.exit_code == 0
    assert "--depth" in result.output
    assert "--json" in result.output
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_code_graph_cli.py -v`
Expected: FAIL (no such command; non-zero exit).

- [ ] **Step 3: Add the command to `cli.py`**

In `src/pg_raggraph/cli.py`, add (following the existing `run_async` / `@click.pass_context` / `GraphRAG(**ctx.obj["kwargs"])` patterns):

```python
@main.command("code-impact")
@click.argument("fqn")
@click.option("-n", "--namespace", default=None, help="Namespace (default: configured)")
@click.option("--depth", type=int, default=1, help="Transitive hops (>=1)")
@click.option("--min-confidence", type=float, default=0.0, help="Min edge weight")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a tree")
@click.pass_context
def _code_impact(ctx, fqn, namespace, depth, min_confidence, as_json):
    """Show callers and callees of a code symbol (FQN) from the graph."""
    import json as _json
    from dataclasses import asdict

    from pg_raggraph.code_graph import render_impact_tree

    async def _go():
        rag = GraphRAG(**ctx.obj["kwargs"])
        await rag.connect()
        ns = namespace or rag.config.namespace
        try:
            res = await rag.code_impact(
                fqn, namespace=namespace, depth=depth, min_confidence=min_confidence
            )
        finally:
            await rag.close()
        if not res.found:
            click.echo(f"symbol '{fqn}' not found in namespace '{ns}'", err=True)
            raise SystemExit(1)
        if as_json:
            click.echo(_json.dumps(asdict(res), indent=2))
        else:
            click.echo(render_impact_tree(res))

    run_async(_go())
```

- [ ] **Step 4: Run the registration test**

Run: `uv run pytest tests/unit/test_code_graph_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Write an end-to-end CLI integration test**

Append to `tests/integration/test_code_graph.py`:

```python
def test_cli_code_impact_json_and_notfound():
    from click.testing import CliRunner
    from pg_raggraph.cli import main
    import asyncio
    import json as _json

    async def _setup():
        rag = GraphRAG(dsn=DSN, namespace=NS)
        await _fresh(rag)
        await _seed(rag, [("a", "b", "CALLS", 1.0, "a() calls b()")])
        await rag.close()

    asyncio.run(_setup())
    runner = CliRunner()
    try:
        ok = runner.invoke(main, ["--db", DSN, "code-impact", "b", "-n", NS, "--json"])
        assert ok.exit_code == 0, ok.output
        data = _json.loads(ok.output)
        assert data["fqn"] == "b" and data["found"] is True
        assert any(e["fqn"] == "a" for e in data["callers"])

        missing = runner.invoke(
            main, ["--db", DSN, "code-impact", "nope", "-n", NS]
        )
        assert missing.exit_code != 0
    finally:
        async def _teardown():
            rag = GraphRAG(dsn=DSN, namespace=NS)
            await rag.connect()
            await rag.delete(NS)
            await rag.close()
        asyncio.run(_teardown())
```

- [ ] **Step 6: Run the integration test**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_code_graph.py::test_cli_code_impact_json_and_notfound -v`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/pg_raggraph/cli.py tests/unit/test_code_graph_cli.py tests/integration/test_code_graph.py
git add src/pg_raggraph/cli.py tests/unit/test_code_graph_cli.py tests/integration/test_code_graph.py
git commit -m "feat: add code-impact CLI command (tree + --json)"
```

---

## Task 5: `summaries_by_fqn` helper

**Files:**
- Modify: `src/pg_raggraph/chunkshop_bridge.py`
- Test: `tests/unit/test_chunkshop_bridge.py`

- [ ] **Step 1: Write the failing unit test**

Append to `tests/unit/test_chunkshop_bridge.py`:

```python
def test_summaries_by_fqn_extracts_map():
    from pg_raggraph.chunkshop_bridge import summaries_by_fqn

    records = [
        {
            "pre_chunked": [
                {"content": "x", "metadata": {"fqn": "pkg.a", "summary": "Runs the job"}},
                {"content": "y", "metadata": {"fqn": "pkg.b"}},  # no summary -> skipped
                {"content": "z", "metadata": {"summary": "no fqn"}},  # no fqn -> skipped
            ]
        },
        {"pre_chunked": [{"content": "w", "metadata": {"fqn": "pkg.c", "summary": "C"}}]},
        {"text": "no prechunk"},  # records without pre_chunked are ignored
    ]
    assert summaries_by_fqn(records) == {"pkg.a": "Runs the job", "pkg.c": "C"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_chunkshop_bridge.py::test_summaries_by_fqn_extracts_map -v`
Expected: FAIL — `ImportError: cannot import name 'summaries_by_fqn'`.

- [ ] **Step 3: Add the helper to `chunkshop_bridge.py`**

Add to `src/pg_raggraph/chunkshop_bridge.py` (and add `"summaries_by_fqn"` to `__all__`):

```python
def summaries_by_fqn(records: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Map fqn -> summary from imported chunk metadata.

    Scans each record's ``pre_chunked`` chunks; includes only chunks whose
    metadata carries BOTH ``fqn`` and a non-empty ``summary`` (chunkshop's
    symbol_aware chunker + code_summary extractor).
    """
    out: dict[str, str] = {}
    for record in records:
        for chunk in record.get("pre_chunked") or []:
            meta = chunk.get("metadata") or {}
            fqn = meta.get("fqn")
            summary = meta.get("summary")
            if fqn and summary:
                out[str(fqn)] = str(summary)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_chunkshop_bridge.py::test_summaries_by_fqn_extracts_map -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/chunkshop_bridge.py tests/unit/test_chunkshop_bridge.py
git commit -m "feat: add summaries_by_fqn helper to chunkshop bridge"
```

---

## Task 6: Thread `summaries` into code-edge entity descriptions

**Files:**
- Modify: `src/pg_raggraph/chunkshop_bridge.py`, `src/pg_raggraph/cli.py`
- Test: `tests/integration/test_chunkshop_bridge.py`

- [ ] **Step 1: Write the failing integration test**

Append to `tests/integration/test_chunkshop_bridge.py` (match the file's existing fixture/DSN/skip style — it already imports `GraphRAG`, `attach_code_edges`, `rows_to_records`; add imports as needed):

```python
def test_code_edges_to_known_graph_uses_summary_description():
    from pg_raggraph.chunkshop_bridge import code_edges_to_known_graph

    edges = [{"src_fqn": "pkg.a", "dst_fqn": "pkg.b", "edge_type": "CALLS",
              "confidence": 1.0, "evidence": {"snippet": "a calls b"}}]
    entities, _ = code_edges_to_known_graph(
        edges, summaries={"pkg.a": "Runs the job"}
    )
    by_name = {e["name"]: e["description"] for e in entities}
    assert by_name["pkg.a"] == "Runs the job"          # enriched
    assert by_name["pkg.b"] == "Code symbol pkg.b"      # fallback (no summary)


def test_attach_code_edges_derives_summaries_from_records():
    from pg_raggraph.chunkshop_bridge import attach_code_edges

    records = [{
        "text": "x", "source_id": "s",
        "pre_chunked": [{"content": "x",
                         "metadata": {"fqn": "pkg.a", "summary": "Runs the job"}}],
    }]
    edges = [{"src_fqn": "pkg.a", "dst_fqn": "pkg.b", "edge_type": "CALLS",
              "confidence": 1.0, "evidence": {}}]
    out = attach_code_edges(records, edges)
    ents = {e["name"]: e["description"] for e in out[0]["entities"]}
    assert ents["pkg.a"] == "Runs the job"
```

- [ ] **Step 2: Run to verify they fail**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_chunkshop_bridge.py -k "summary or derives" -v`
Expected: FAIL — `code_edges_to_known_graph() got an unexpected keyword argument 'summaries'`.

- [ ] **Step 3: Thread `summaries` through the bridge functions**

In `src/pg_raggraph/chunkshop_bridge.py`:

3a. `code_edges_to_known_graph` — add the `summaries` param and use it for the entity description:

```python
def code_edges_to_known_graph(
    rows: Iterable[dict[str, Any]],
    *,
    min_confidence: float = 0.0,
    summaries: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
```

Inside the `entities_by_name.setdefault(...)` for each `fqn`, replace the
`"description": f"Code symbol {fqn}"` line with:

```python
                    "description": (summaries or {}).get(fqn) or f"Code symbol {fqn}",
```

3b. `attach_code_edges` — add `summaries=None`; derive from records when not given; pass through:

```python
def attach_code_edges(
    records: list[dict[str, Any]],
    edge_rows: Iterable[dict[str, Any]],
    *,
    min_confidence: float = 0.0,
    summaries: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
```

At the top of the body (before calling `code_edges_to_known_graph`):

```python
    if summaries is None:
        summaries = summaries_by_fqn(records)
```

And pass `summaries=summaries` into the `code_edges_to_known_graph(...)` call.

3c. `fetch_code_edges_from_table` — add `summaries=None` and pass it through to
`code_edges_to_known_graph`:

```python
def fetch_code_edges_from_table(
    dsn: str,
    *,
    schema: str,
    project_id: str | None = None,
    min_confidence: float = 0.0,
    summaries: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
```

In its final `return code_edges_to_known_graph(rows, min_confidence=min_confidence)`,
change to `return code_edges_to_known_graph(rows, min_confidence=min_confidence, summaries=summaries)`.

- [ ] **Step 4: Run the bridge tests to verify they pass**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_chunkshop_bridge.py -k "summary or derives" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Wire summaries into the CLI import path**

In `src/pg_raggraph/cli.py`, in the `ingest-chunkshop-table` command's
`_ingest_chunkshop_table` coroutine, inside the `if with_code_edges:` branch, build the
summaries map from the fetched records and pass it to `fetch_code_edges_from_table`:

```python
        if with_code_edges:
            summaries = chunkshop_bridge.summaries_by_fqn(records)
            entities, relationships = chunkshop_bridge.fetch_code_edges_from_table(
                dsn,
                schema=schema_name,
                project_id=project_id,
                min_confidence=min_confidence,
                summaries=summaries,
            )
```

(Leave the rest of that branch — the `records[0].setdefault(...)` merge — unchanged.)

- [ ] **Step 6: Run the full chunkshop bridge file + lint**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration/test_chunkshop_bridge.py -v`
Expected: all PASS (prior tests + 2 new).
Run: `uv run ruff check src/pg_raggraph/chunkshop_bridge.py src/pg_raggraph/cli.py tests/integration/test_chunkshop_bridge.py`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add src/pg_raggraph/chunkshop_bridge.py src/pg_raggraph/cli.py tests/integration/test_chunkshop_bridge.py
git commit -m "feat: enrich CODE_SYMBOL descriptions from chunkshop summaries"
```

---

## Task 7: Full-suite regression + docs pointer

**Files:**
- Modify: `docs/chunkshop-user-guide.md` (add a short `code-impact` section)

- [ ] **Step 1: Lint the whole feature**

Run: `uv run ruff check src/pg_raggraph/code_graph.py src/pg_raggraph/__init__.py src/pg_raggraph/cli.py src/pg_raggraph/chunkshop_bridge.py tests/unit/test_code_graph.py tests/unit/test_code_graph_cli.py tests/integration/test_code_graph.py tests/integration/test_chunkshop_bridge.py`
Expected: `All checks passed!`

- [ ] **Step 2: Run unit suite**

Run: `uv run pytest tests/unit -q`
Expected: all pass.

- [ ] **Step 3: Run integration suite**

Run: `env PGRG_TEST_DSN=postgresql://postgres:postgres@localhost:5437/pg_raggraph uv run pytest tests/integration -q`
Expected: all pass / skipped, no failures.

- [ ] **Step 4: Add a short docs section**

In `docs/chunkshop-user-guide.md`, add a `## Querying the code graph (`code-impact`)` section near the code-edge import content with a worked example:

```markdown
## Querying the code graph (`code-impact`)

Once code edges are imported (`--with-code-edges`), query the call graph:

    pgrg --db "$PGRG_DSN" code-impact pkg.module.func -n code_graph --depth 2

This prints the symbol's callers (who depends on it) and callees (what it calls),
with evidence snippets, walking up to `--depth` hops. Add `--json` for scripting.
From Python: `await rag.code_impact("pkg.module.func", depth=2)` returns a
`CodeImpact` dataclass. When chunks were imported with chunkshop's `code_summary`
extractor, each symbol's description carries that summary.
```

- [ ] **Step 5: Commit**

```bash
git add docs/chunkshop-user-guide.md
git commit -m "docs: document code-impact in the chunkshop user guide"
```

---

## Self-Review Notes

- **Spec coverage:** `code_impact` traversal (callers/callees + depth + cycle guard + min_confidence + not-found) → Task 1; `render_impact_tree` → Task 2; `GraphRAG.code_impact` API → Task 3; CLI `code-impact` (tree + --json + not-found exit) → Task 4; `summaries_by_fqn` → Task 5; `summaries` threading through `code_edges_to_known_graph`/`attach_code_edges`/`fetch_code_edges_from_table` + CLI → Task 6; regression + docs → Task 7.
- **Evidence resolution** (the spec's deferred detail) is pinned: `COALESCE(NULLIF(r.description,''), r.properties->'evidence'->>'snippet', '')` — `description` already holds the snippet from `code_edges_to_known_graph`.
- **Signatures consistent:** `code_impact(db, fqn, *, namespace, depth=1, min_confidence=0.0)`, `CodeEdge(fqn, rel_type, evidence, depth)`, `CodeImpact(fqn, found, callers, callees)`, `render_impact_tree(impact)`, `summaries_by_fqn(records)`, `summaries=` kwarg used identically in Tasks 5/6.
- **No schema changes**; all SQL identifiers fixed, all values parameterized (`ns`, `seed`, `rel_types`, `min_conf`, `depth`).
- **Namespace-scoped, non-destructive** → integration tests reuse the shared DB with a `test_code_graph` namespace + teardown (no throwaway DB needed).
