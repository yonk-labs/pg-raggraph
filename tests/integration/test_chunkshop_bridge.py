"""End-to-end checks for the chunkshop Pattern C bridge."""

from __future__ import annotations

import os

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
