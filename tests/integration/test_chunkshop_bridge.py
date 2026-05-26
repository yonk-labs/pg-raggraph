"""End-to-end checks for the chunkshop Pattern C bridge."""

from __future__ import annotations

import os
import uuid

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.chunkshop_bridge import (
    attach_code_edges,
    fetch_code_edges_from_table,
    rows_to_records,
)

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
NS = "test_chunkshop_bridge_e2e"

# DSN for the noedges test — respects PGRG_TEST_DSN override (task uses port 5437)
_NOEDGES_DSN = os.environ.get("PGRG_TEST_DSN", DSN)


def _embedding(seed: float) -> list[float]:
    return [seed] * 384


async def test_chunkshop_records_and_code_edges_persist_end_to_end():
    rag = GraphRAG(
        dsn=DSN,
        namespace=NS,
        llm_base_url="http://localhost:99999/v1",
    )
    await rag.connect()
    await rag.delete(NS)
    try:
        records = rows_to_records(
            [
                {
                    "doc_id": "pkg/example.py",
                    "seq_num": 1,
                    "original_content": "def beta():\n    return 2",
                    "embedded_content": "pkg/example.py\n\ndef beta():\n    return 2",
                    "embedding": _embedding(0.02),
                    "metadata": {"language": "python", "symbol_name": "beta"},
                    "tags": ["code"],
                    "source": "repo",
                },
                {
                    "doc_id": "pkg/example.py",
                    "seq_num": 0,
                    "original_content": "def alpha():\n    return beta()",
                    "embedded_content": "pkg/example.py\n\ndef alpha():\n    return beta()",
                    "embedding": _embedding(0.01),
                    "metadata": {"language": "python", "symbol_name": "alpha"},
                    "tags": ["code"],
                    "source": "repo",
                },
            ],
            skip_llm=True,
        )
        attach_code_edges(
            records,
            [
                {
                    "project_id": "kb_code",
                    "edge_type": "CALLS",
                    "src_fqn": "pkg.example.alpha",
                    "dst_fqn": "pkg.example.beta",
                    "src_node_id": "node-alpha",
                    "dst_node_id": "node-beta",
                    "confidence": 0.88,
                    "evidence": {"line": 2, "snippet": "return beta()"},
                }
            ],
        )

        await rag.ingest_records(records, namespace=NS)

        chunks = await rag.db.fetch_all(
            "SELECT c.content, c.embedded_content, c.metadata "
            "FROM chunks c JOIN documents d ON c.document_id = d.id "
            "WHERE d.namespace = %s ORDER BY c.id",
            (NS,),
        )
        assert [row["metadata"]["chunkshop_seq_num"] for row in chunks] == [0, 1]
        assert chunks[0]["content"].startswith("def alpha")
        assert chunks[0]["embedded_content"].startswith("pkg/example.py")
        assert chunks[0]["metadata"]["symbol_name"] == "alpha"
        assert chunks[0]["metadata"]["tags"] == ["code"]

        relationships = await rag.db.fetch_all(
            "SELECT r.rel_type, r.weight, r.properties "
            "FROM relationships r WHERE r.namespace = %s",
            (NS,),
        )
        assert len(relationships) == 1
        assert relationships[0]["rel_type"] == "CALLS"
        assert relationships[0]["weight"] == 0.88
        assert relationships[0]["properties"]["project_id"] == "kb_code"
        assert relationships[0]["properties"]["src_node_id"] == "node-alpha"
        assert relationships[0]["properties"]["evidence"]["line"] == 2

        entities = await rag.db.fetch_all(
            "SELECT name, entity_type, properties FROM entities "
            "WHERE namespace = %s ORDER BY name",
            (NS,),
        )
        assert [row["name"] for row in entities] == [
            "pkg.example.alpha",
            "pkg.example.beta",
        ]
        assert all(row["entity_type"] == "CODE_SYMBOL" for row in entities)
        assert entities[0]["properties"]["chunkshop_node_id"] == "node-alpha"
    finally:
        await rag.delete(NS)
        await rag.close()


def test_fetch_code_edges_raises_when_table_absent_noedges():
    """fetch_code_edges_from_table must raise a clear ValueError when code_edges is missing.

    This test ensures an older (pre-0.6.0) chunkshop sink (which never materializes
    code_edges) produces a helpful error instead of an opaque psycopg UndefinedTable.
    """
    import psycopg

    schema = "emig_noedges"
    try:
        with psycopg.connect(_NOEDGES_DSN) as conn:
            conn.autocommit = True
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            conn.execute(f"DROP TABLE IF EXISTS {schema}.code_edges")

        with pytest.raises(ValueError, match="code_edges"):
            fetch_code_edges_from_table(_NOEDGES_DSN, schema=schema)
    finally:
        with psycopg.connect(_NOEDGES_DSN) as conn:
            conn.autocommit = True
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


# ---------------------------------------------------------------------------
# CLI end-to-end: ingest-chunkshop-table against a real Postgres sink table
# ---------------------------------------------------------------------------

_CLI_DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5437/pg_raggraph")
_CLI_NS = "test_chunkshop_cli_e2e"


def _vec384(seed: float) -> str:
    """Return a pgvector bracket literal with 384 identical floats."""
    vals = ",".join(str(seed) for _ in range(384))
    return f"[{vals}]"


def test_ingest_chunkshop_table_cli_end_to_end():
    """CLI `pgrg ingest-chunkshop-table` against a real Postgres sink table.

    Creates a temporary schema with a chunkshop-shaped sink table and a
    code_edges table, invokes the CLI command through click's CliRunner, then
    asserts that documents/chunks/entities/relationships landed in the DB
    under the test namespace.
    """
    import psycopg
    from click.testing import CliRunner

    from pg_raggraph.cli import main

    schema = f"cs_sink_{uuid.uuid4().hex[:8]}"
    sink = "chunks"

    # ------------------------------------------------------------------
    # 1. Create schema, sink table, code_edges table and insert rows
    # ------------------------------------------------------------------
    with psycopg.connect(_CLI_DSN, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute(
            f"""
            CREATE TABLE {schema}.{sink} (
                doc_id          TEXT NOT NULL,
                seq_num         INTEGER NOT NULL,
                original_content TEXT NOT NULL,
                embedded_content TEXT NOT NULL,
                embedding       vector(384) NOT NULL,
                metadata        JSONB DEFAULT '{{}}',
                tags            TEXT[],
                source          TEXT
            )
            """
        )
        cols = (
            "doc_id, seq_num, original_content, embedded_content,"
            " embedding, metadata, tags, source"
        )
        conn.execute(
            f"""
            INSERT INTO {schema}.{sink} ({cols})
            VALUES
                ('docA', 0, 'def foo(): pass', 'docA\n\ndef foo(): pass',
                 '{_vec384(0.11)}'::vector, '{{}}'::jsonb, ARRAY[]::text[], 'test'),
                ('docA', 1, 'def bar(): return 1', 'docA\n\ndef bar(): return 1',
                 '{_vec384(0.22)}'::vector, '{{}}'::jsonb, ARRAY[]::text[], 'test')
            """
        )

        conn.execute(
            f"""
            CREATE TABLE {schema}.code_edges (
                project_id  TEXT,
                edge_type   TEXT NOT NULL,
                src_fqn     TEXT NOT NULL,
                dst_fqn     TEXT NOT NULL,
                src_node_id TEXT,
                dst_node_id TEXT,
                confidence  FLOAT DEFAULT 1.0,
                evidence    JSONB DEFAULT '{{}}'
            )
            """
        )
        edge_cols = (
            "project_id, edge_type, src_fqn, dst_fqn,"
            " src_node_id, dst_node_id, confidence, evidence"
        )
        conn.execute(
            f"""
            INSERT INTO {schema}.code_edges ({edge_cols})
            VALUES
                ('projA', 'CALLS', 'pkg.a', 'pkg.b', 'n1', 'n2', 0.9,
                 '{{"snippet":"a() calls b()"}}'::jsonb)
            """
        )

    # ------------------------------------------------------------------
    # 2. Invoke the CLI
    # ------------------------------------------------------------------
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--db", _CLI_DSN,
            "ingest-chunkshop-table",
            "--schema", schema,
            "--table", sink,
            "--chunkshop-dsn", _CLI_DSN,
            "--namespace", _CLI_NS,
            "--with-code-edges",
            "--project-id", "projA",
            "--skip-llm",
        ],
    )

    if result.exit_code != 0:
        import traceback
        exc_text = ""
        if result.exception:
            exc_text = "".join(
                traceback.format_exception(
                    type(result.exception),
                    result.exception,
                    result.exception.__traceback__,
                )
            )
        raise AssertionError(
            f"CLI exited with code {result.exit_code}\n"
            f"Output:\n{result.output}\n"
            f"Exception:\n{exc_text}"
        )

    # ------------------------------------------------------------------
    # 3. Verify rows landed in the DB (async GraphRAG queries)
    # ------------------------------------------------------------------
    import asyncio

    async def _verify():
        rag = GraphRAG(dsn=_CLI_DSN, namespace=_CLI_NS)
        await rag.connect()
        try:
            doc_row = await rag.db.fetch_one(
                "SELECT COUNT(*) AS n FROM documents WHERE namespace = %s",
                (_CLI_NS,),
            )
            assert doc_row["n"] >= 1, f"expected >=1 document, got {doc_row['n']}"

            chunk_row = await rag.db.fetch_one(
                "SELECT COUNT(*) AS n FROM chunks c "
                "JOIN documents d ON c.document_id = d.id "
                "WHERE d.namespace = %s",
                (_CLI_NS,),
            )
            assert chunk_row["n"] >= 2, f"expected >=2 chunks, got {chunk_row['n']}"

            ent_row = await rag.db.fetch_one(
                "SELECT COUNT(*) AS n FROM entities WHERE namespace = %s",
                (_CLI_NS,),
            )
            assert ent_row["n"] >= 2, f"expected >=2 entities (pkg.a, pkg.b), got {ent_row['n']}"

            rel_row = await rag.db.fetch_one(
                "SELECT COUNT(*) AS n FROM relationships WHERE namespace = %s",
                (_CLI_NS,),
            )
            assert rel_row["n"] >= 1, f"expected >=1 relationship (CALLS), got {rel_row['n']}"
        finally:
            await rag.delete(_CLI_NS)
            await rag.close()

    try:
        asyncio.run(_verify())
    finally:
        # Drop the temporary sink schema regardless of assertion outcome
        with psycopg.connect(_CLI_DSN, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
