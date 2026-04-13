"""Integration tests for the cleanup-sprint additions and their AAT fixes.

Covers:
- rag.ask() fallback path (no LLM configured)
- Incremental re-ingest (stale-doc delete atomic with new insert)
- delete_document
- merge_entities (self-loops, duplicate edges, keep_id validation,
  empty/missing/cross-namespace refusal)
- prune_orphans (returns integer counts, not cursor objects)
- Migration framework (runs on every connect, not just first install)
- MCP path sandbox
- ask/query CLI default mode
"""

from __future__ import annotations

import os
import tempfile

import pytest

from pg_raggraph import GraphRAG

TEST_DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)


async def _rag(namespace: str, skip_extraction: bool = True) -> GraphRAG:
    """GraphRAG pointed at the test DB, no LLM by default (pure vector)."""
    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace=namespace,
        llm_base_url="",
        skip_extraction=skip_extraction,
    )
    await rag.connect()
    return rag


# ---------------------------------------------------------------------------
# ask() and LLM-optional ingest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_without_llm_stores_chunks():
    rag = await _rag("ask_vector_only")
    try:
        await rag.delete("ask_vector_only")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "alpha.md")
            with open(p, "w") as f:
                f.write("# Alpha\n\nAlpha widgets are used in production systems.")
            await rag.ingest([p], namespace="ask_vector_only")

        status = await rag.status(namespace="ask_vector_only")
        assert status["documents"] == 1
        assert status["entities"] == 0, "skip_extraction should yield 0 entities"
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_ask_fallback_when_no_llm():
    rag = await _rag("ask_fallback")
    try:
        await rag.delete("ask_fallback")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "alpha.md")
            with open(p, "w") as f:
                f.write("Alpha widgets are 42 inches tall.")
            await rag.ingest([p], namespace="ask_fallback")

        result = await rag.ask("How tall are alpha widgets?", namespace="ask_fallback")
        # Fallback should name the file and quote its content
        assert "No LLM configured" in result.answer
        assert "42 inches" in result.answer or "Alpha" in result.answer
    finally:
        await rag.close()


# ---------------------------------------------------------------------------
# Incremental re-ingest (Fix #4: stale delete inside transaction)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incremental_reingest_replaces_stale_doc():
    rag = await _rag("incremental_replace")
    try:
        await rag.delete("incremental_replace")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "doc.md")

            with open(p, "w") as f:
                f.write("original content version one")
            await rag.ingest([p], namespace="incremental_replace")
            s1 = await rag.status(namespace="incremental_replace")
            assert s1["documents"] == 1

            with open(p, "w") as f:
                f.write("rewritten content version two with new material")
            await rag.ingest([p], namespace="incremental_replace")
            s2 = await rag.status(namespace="incremental_replace")
            assert s2["documents"] == 1, "stale doc should be replaced, not duplicated"

            row = await rag.db.fetch_one(
                "SELECT content FROM chunks WHERE document_id IN "
                "(SELECT id FROM documents WHERE namespace = %s AND source_path = %s) "
                "LIMIT 1",
                ("incremental_replace", p),
            )
            assert row is not None
            assert "version two" in row["content"]
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_incremental_reingest_skips_unchanged():
    rag = await _rag("incremental_skip")
    try:
        await rag.delete("incremental_skip")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "doc.md")
            with open(p, "w") as f:
                f.write("same content")

            await rag.ingest([p], namespace="incremental_skip")
            s1 = await rag.status(namespace="incremental_skip")

            # Re-ingest with identical content — should be a no-op
            await rag.ingest([p], namespace="incremental_skip")
            s2 = await rag.status(namespace="incremental_skip")
            assert s2["documents"] == s1["documents"]
    finally:
        await rag.close()


# ---------------------------------------------------------------------------
# delete_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_document_removes_chunks():
    rag = await _rag("crud_delete_doc")
    try:
        await rag.delete("crud_delete_doc")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "doc.md")
            with open(p, "w") as f:
                f.write("content to delete")
            await rag.ingest([p], namespace="crud_delete_doc")
            assert (await rag.status(namespace="crud_delete_doc"))["documents"] == 1

            deleted = await rag.delete_document(p, namespace="crud_delete_doc")
            assert deleted == 1
            assert (await rag.status(namespace="crud_delete_doc"))["documents"] == 0
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_delete_document_nonexistent_returns_zero():
    rag = await _rag("crud_delete_missing")
    try:
        await rag.delete("crud_delete_missing")
        deleted = await rag.delete_document(
            "/nonexistent/path.md", namespace="crud_delete_missing"
        )
        assert deleted == 0
    finally:
        await rag.close()


# ---------------------------------------------------------------------------
# merge_entities (Fix #3: all four correctness issues)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_entities_rejects_keep_id_in_merge_ids():
    rag = await _rag("merge_keep_in_merge")
    try:
        await rag.delete("merge_keep_in_merge")
        await rag.db.execute(
            "INSERT INTO entities (namespace, name, entity_type) VALUES (%s, 'A', 'x')",
            ("merge_keep_in_merge",),
        )
        row = await rag.db.fetch_one(
            "SELECT id FROM entities WHERE namespace = %s", ("merge_keep_in_merge",)
        )
        a = row["id"]

        with pytest.raises(ValueError, match="must not appear in merge_ids"):
            await rag.merge_entities(a, [a])
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_merge_entities_rejects_empty_merge_ids():
    rag = await _rag("merge_empty")
    try:
        with pytest.raises(ValueError, match="must not be empty"):
            await rag.merge_entities(1, [])
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_merge_entities_rejects_missing_entity():
    rag = await _rag("merge_missing")
    try:
        await rag.delete("merge_missing")
        await rag.db.execute(
            "INSERT INTO entities (namespace, name, entity_type) VALUES (%s, 'A', 'x')",
            ("merge_missing",),
        )
        row = await rag.db.fetch_one(
            "SELECT id FROM entities WHERE namespace = %s", ("merge_missing",)
        )
        a = row["id"]

        with pytest.raises(ValueError, match="entities not found"):
            await rag.merge_entities(a, [999_999_999])
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_merge_entities_rejects_cross_namespace():
    rag = await _rag("merge_cross_a")
    try:
        await rag.delete("merge_cross_a")
        await rag.delete("merge_cross_b")
        await rag.db.execute(
            "INSERT INTO entities (namespace, name, entity_type) VALUES "
            "(%s, 'A', 'x'), (%s, 'B', 'x')",
            ("merge_cross_a", "merge_cross_b"),
        )
        rows = await rag.db.fetch_all(
            "SELECT id, namespace FROM entities WHERE namespace LIKE 'merge_cross_%'"
        )
        a = next(r["id"] for r in rows if r["namespace"] == "merge_cross_a")
        b = next(r["id"] for r in rows if r["namespace"] == "merge_cross_b")

        with pytest.raises(ValueError, match="cross-namespace merge refused"):
            await rag.merge_entities(a, [b])
    finally:
        await rag.delete("merge_cross_b")
        await rag.close()


@pytest.mark.asyncio
async def test_merge_entities_drops_self_loops_and_duplicates():
    """Real merge scenario: A->B and B->A become A->A loops after merging B into A
    and must be deleted. A->C twice must collapse to one edge."""
    rag = await _rag("merge_selfloop")
    try:
        await rag.delete("merge_selfloop")
        await rag.db.execute(
            "INSERT INTO entities (namespace, name, entity_type) VALUES "
            "(%s, 'A', 'x'), (%s, 'B', 'x'), (%s, 'C', 'x')",
            ("merge_selfloop", "merge_selfloop", "merge_selfloop"),
        )
        ids = await rag.db.fetch_all(
            "SELECT id, name FROM entities WHERE namespace = %s ORDER BY name",
            ("merge_selfloop",),
        )
        a, b, c = ids[0]["id"], ids[1]["id"], ids[2]["id"]

        await rag.db.execute(
            "INSERT INTO relationships (namespace, src_id, dst_id, rel_type) VALUES "
            "(%s, %s, %s, 'REL'), (%s, %s, %s, 'REL'), "
            "(%s, %s, %s, 'REL'), (%s, %s, %s, 'REL')",
            (
                "merge_selfloop",
                a,
                b,
                "merge_selfloop",
                b,
                a,
                "merge_selfloop",
                a,
                c,
                "merge_selfloop",
                a,
                c,
            ),
        )

        result = await rag.merge_entities(a, [b])
        assert result == {"kept": a, "merged_count": 1}

        loops = await rag.db.fetch_all(
            "SELECT id FROM relationships WHERE namespace = %s AND src_id = dst_id",
            ("merge_selfloop",),
        )
        assert loops == [], f"self-loops survived merge: {loops}"

        ac_edges = await rag.db.fetch_all(
            "SELECT id FROM relationships WHERE namespace = %s "
            "AND src_id = %s AND dst_id = %s AND rel_type = 'REL'",
            ("merge_selfloop", a, c),
        )
        assert len(ac_edges) == 1, f"expected 1 A->C edge after dedup, got {len(ac_edges)}"

        remaining = await rag.db.fetch_all(
            "SELECT id FROM entities WHERE namespace = %s", ("merge_selfloop",)
        )
        assert len(remaining) == 2, "A and C should remain; B should be deleted"
    finally:
        await rag.close()


# ---------------------------------------------------------------------------
# prune_orphans (Fix: returns integers, not cursors)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prune_orphans_returns_integer_counts():
    rag = await _rag("crud_prune")
    try:
        await rag.delete("crud_prune")
        await rag.db.execute(
            "INSERT INTO entities (namespace, name, entity_type) VALUES "
            "(%s, 'OrphanOne', 'x'), (%s, 'OrphanTwo', 'x')",
            ("crud_prune", "crud_prune"),
        )

        result = await rag.prune_orphans(namespace="crud_prune")
        assert isinstance(result["entities_pruned"], int)
        assert isinstance(result["relationships_pruned"], int)
        assert result["entities_pruned"] == 2
        assert result["relationships_pruned"] == 0

        status = await rag.status(namespace="crud_prune")
        assert status["entities"] == 0
    finally:
        await rag.close()


# ---------------------------------------------------------------------------
# Migration framework (Fix #1: _apply_migrations runs on every connect)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_migrations_runs_on_every_connect():
    """Multiple connects to an already-initialized DB must not error and
    must always exercise the _apply_migrations path (verified by not
    raising, since there are no real migrations yet)."""
    rag1 = await _rag("crud_migration_one")
    await rag1.close()

    rag2 = await _rag("crud_migration_two")
    version = await rag2.db.get_meta("schema_version")
    await rag2.close()
    assert version == "1"


@pytest.mark.asyncio
async def test_apply_migrations_runs_pending_files(monkeypatch):
    """Drop a real migration file into the migrations dir, reset the
    recorded schema_version, reconnect, and verify the runner applied it
    and bumped schema_version. This is the regression test for AAT SCOUT-010
    — that the framework actually runs migrations on existing installs.
    """
    import shutil
    from importlib.resources import files as pkg_files

    mig_dir = pkg_files("pg_raggraph.sql").joinpath("migrations")
    test_mig_path = str(mig_dir.joinpath("999_aat_runner_probe.sql"))
    marker_table = "pgrg_aat_runner_probe"

    try:
        # Write a dummy migration that creates a marker table
        with open(test_mig_path, "w") as f:
            f.write(f"CREATE TABLE IF NOT EXISTS {marker_table} (id int);\n")

        rag = await _rag("crud_migration_probe")
        try:
            # Roll schema_version back to 1 to force the migration to apply
            await rag.db.execute("UPDATE pgrg_meta SET value = '1' WHERE key = 'schema_version'")
            # Drop the marker table if a previous test left it behind
            await rag.db.execute(f"DROP TABLE IF EXISTS {marker_table}")
        finally:
            await rag.close()

        # Reconnect — should apply the migration
        rag2 = await _rag("crud_migration_probe")
        try:
            version = await rag2.db.get_meta("schema_version")
            assert version == "999", f"expected schema_version=999, got {version}"

            row = await rag2.db.fetch_one(
                "SELECT EXISTS (SELECT FROM pg_tables WHERE tablename = %s) AS e",
                (marker_table,),
            )
            assert row["e"] is True, "migration did not create marker table"
        finally:
            # Clean up: drop the marker table and reset schema_version
            await rag2.db.execute(f"DROP TABLE IF EXISTS {marker_table}")
            await rag2.db.execute("UPDATE pgrg_meta SET value = '1' WHERE key = 'schema_version'")
            await rag2.close()
    finally:
        # Always remove the dummy migration file even if the test failed
        try:
            os.remove(test_mig_path)
        except FileNotFoundError:
            pass
        # Clear any bytecode cache for the migrations package
        cache_dir = os.path.join(os.path.dirname(test_mig_path), "__pycache__")
        if os.path.isdir(cache_dir):
            shutil.rmtree(cache_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# MCP path sandbox (Fix #2)
# ---------------------------------------------------------------------------


def test_mcp_sandbox_empty_by_default(monkeypatch):
    from pg_raggraph.mcp_server import _resolve_allowed_roots

    monkeypatch.delenv("PGRG_MCP_INGEST_ROOTS", raising=False)
    assert _resolve_allowed_roots() == []


def test_mcp_sandbox_parses_env_var(monkeypatch):
    from pg_raggraph.mcp_server import _resolve_allowed_roots

    monkeypatch.setenv("PGRG_MCP_INGEST_ROOTS", "/tmp/kb:/var/data")
    roots = _resolve_allowed_roots()
    assert len(roots) == 2
    assert all(os.path.isabs(r) for r in roots)


def test_mcp_sandbox_allows_path_inside_root():
    from pg_raggraph.mcp_server import _check_path_allowed

    result = _check_path_allowed("/tmp/kb/doc.md", ["/tmp/kb"])
    assert result == "/tmp/kb/doc.md"


def test_mcp_sandbox_refuses_path_outside_root():
    from pg_raggraph.mcp_server import _check_path_allowed

    with pytest.raises(PermissionError, match="not inside an allowed"):
        _check_path_allowed("/etc/passwd", ["/tmp/kb"])


def test_mcp_sandbox_refuses_prefix_confusion():
    """'/tmp/kb2/evil.md' must not match allowed root '/tmp/kb'."""
    from pg_raggraph.mcp_server import _check_path_allowed

    with pytest.raises(PermissionError):
        _check_path_allowed("/tmp/kb2/evil.md", ["/tmp/kb"])
