import os

import pytest

from pg_raggraph import GraphRAG

# NOTE: `from pg_raggraph import code_graph as cg` and
# `from pg_raggraph.backfill import backfill_code_graph` are added in Task 3,
# when they are first used. Keeping them out now keeps each commit lint-clean.

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
