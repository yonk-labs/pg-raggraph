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
_INGEST_SRC = """\
def helper(x):
    return x + 1


def runner(y):
    return helper(y) * 2


class Base:
    pass


class Child(Base):
    def go(self):
        return runner(3)
"""


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
            "SELECT COUNT(*) AS n FROM relationships WHERE namespace = %s AND rel_type = 'CALLS'",
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
            [
                {
                    "text": "The quick brown fox. Plain prose, no code here.",
                    "source_id": "doc.txt",
                    "skip_llm": True,
                }
            ],
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
            namespace=NS,
            cross_file_code_graph=True,
            defer_extraction=True,
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
            namespace=NS,
            cross_file_code_graph=True,
            defer_extraction=True,
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


@pytest.mark.asyncio
async def test_backfill_skips_when_chunkshop_unavailable(monkeypatch):
    """Data-safety branch: if chunkshop's code extractor is unavailable at
    backfill time, staged rows are LEFT IN PLACE (counted as skipped) for a
    later run — never deleted, never silently lost."""
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
        # Ingest used the real chunkshop; now simulate it being unavailable when
        # the out-of-band backfill runs (e.g. a worker without chunkshop installed).
        import pg_raggraph.chunkshop_bridge as bridge

        monkeypatch.setattr(bridge.CorpusCodeGraph, "available", property(lambda self: False))

        stats = await backfill_code_graph(rag, NS)
        assert stats.skipped == 1
        assert stats.edges == 0
        # staged row survives for a later run — no data loss
        staged = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM code_backfill_stage WHERE namespace = %s", (NS,)
        )
        assert staged["n"] == 1
        # and no code edges were written
        n = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM relationships WHERE namespace = %s AND rel_type = 'CALLS'",
            (NS,),
        )
        assert n["n"] == 0
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_backfill_drains_all_namespaces_when_none():
    """`namespace=None` resolves every namespace with staged code docs as an
    independent corpus — symbols do not bleed across tenants."""
    pytest.importorskip("chunkshop")
    pytest.importorskip("tree_sitter_python")
    ns_a = NS + "_a"
    ns_b = NS + "_b"
    rag = GraphRAG(dsn=DSN, namespace=NS, chunk_strategy="chunkshop:symbol_aware")
    await rag.connect()
    await rag.delete(ns_a)
    await rag.delete(ns_b)
    try:
        # ns_a: a multi-symbol file with an intra-file call (runner -> helper).
        await rag.ingest_records(
            [{"text": _INGEST_SRC, "source_id": "sample.py", "skip_llm": True}],
            namespace=ns_a,
            defer_extraction=True,
        )
        # ns_b: a different file entirely (no `sample.runner`).
        await rag.ingest_records(
            [{"text": _PKG_A, "source_id": "a.py", "skip_llm": True}],
            namespace=ns_b,
            defer_extraction=True,
        )

        stats = await backfill_code_graph(rag, None)  # drain ALL namespaces
        # at least these two namespaces resolved (>= guards against other
        # tests' leftover staged rows if teardown order ever varies)
        assert stats.namespaces >= 2
        assert stats.docs >= 2

        # ns_a's intra-file edge resolved
        ra = await cg.code_impact(rag._db, "sample.runner", namespace=ns_a, depth=1)
        assert "sample.helper" in [e.fqn for e in ra.callees]
        # symbols do not bleed: ns_b has no `sample.runner`
        rb = await cg.code_impact(rag._db, "sample.runner", namespace=ns_b, depth=1)
        assert rb.found is False
        # staging cleared for both
        cleared = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM code_backfill_stage WHERE namespace = ANY(%s)",
            ([ns_a, ns_b],),
        )
        assert cleared["n"] == 0
    finally:
        await rag.delete(ns_a)
        await rag.delete(ns_b)
        await rag.close()


async def _code_edges(rag, ns):
    """Full set of CODE_SYMBOL->CODE_SYMBOL edges in a namespace, as
    (src_fqn, dst_fqn, rel_type, resolved_intra_file) tuples — fqns are
    namespace-independent, so two namespaces are directly comparable."""
    rows = await rag._db.fetch_all(
        "SELECT s.name AS src, d.name AS dst, r.rel_type, "
        "  r.properties->>'resolved_intra_file' AS rif "
        "FROM relationships r "
        "JOIN entities s ON s.id = r.src_id "
        "JOIN entities d ON d.id = r.dst_id "
        "WHERE r.namespace = %s AND s.entity_type = 'CODE_SYMBOL' "
        "  AND d.entity_type = 'CODE_SYMBOL'",
        (ns,),
    )
    return {(r["src"], r["dst"], r["rel_type"], r["rif"]) for r in rows}


@pytest.mark.asyncio
async def test_backfill_edge_set_is_identical_to_synchronous_path():
    """Exact parity: deferred+backfill produces the IDENTICAL code-edge set as
    the synchronous inline path for the same multi-file corpus — not just a
    representative edge, the whole set. This is the #81 correctness contract."""
    pytest.importorskip("chunkshop")
    pytest.importorskip("tree_sitter_python")
    ns_sync = NS + "_psync"
    ns_defer = NS + "_pdefer"
    rag = GraphRAG(dsn=DSN, namespace=NS, chunk_strategy="chunkshop:symbol_aware")
    await rag.connect()
    await rag.delete(ns_sync)
    await rag.delete(ns_defer)
    try:
        recs = [
            {"text": _PKG_A, "source_id": "a.py", "skip_llm": True},
            {"text": _PKG_B, "source_id": "b.py", "skip_llm": True},
            {"text": _INGEST_SRC, "source_id": "sample.py", "skip_llm": True},
        ]
        # Path A — synchronous, graph built inline.
        await rag.ingest_records(recs, namespace=ns_sync, cross_file_code_graph=True)
        # Path B — deferred ingest, then out-of-band backfill.
        await rag.ingest_records(
            recs, namespace=ns_defer, cross_file_code_graph=True, defer_extraction=True
        )
        await backfill_code_graph(rag, ns_defer)

        sync_edges = await _code_edges(rag, ns_sync)
        defer_edges = await _code_edges(rag, ns_defer)
        assert sync_edges, "synchronous path built a non-trivial code graph"
        # includes at least one resolved cross-file edge (b.run -> a.helper)
        assert any(rif == "false" for (_, _, _, rif) in sync_edges)
        assert defer_edges == sync_edges
    finally:
        await rag.delete(ns_sync)
        await rag.delete(ns_defer)
        await rag.close()
