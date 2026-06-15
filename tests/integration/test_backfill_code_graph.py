import os

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph import code_graph as cg
from pg_raggraph.backfill import backfill_code_graph

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
        assert rows[0]["language"] == "python"  # chunkshop tagged the .py doc
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
