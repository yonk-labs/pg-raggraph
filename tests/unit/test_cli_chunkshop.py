from __future__ import annotations

from click.testing import CliRunner

import pg_raggraph.chunkshop_bridge as chunkshop_bridge
import pg_raggraph.cli as cli
from pg_raggraph.cli import main


class FakeGraphRAG:
    instances: list["FakeGraphRAG"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.records = None
        self.namespace = None
        FakeGraphRAG.instances.append(self)

    async def connect(self):
        return None

    async def ingest_records(self, records, namespace=None):
        self.records = records
        self.namespace = namespace

    async def status(self, namespace=None):
        return {
            "namespace": namespace or "default",
            "documents": 2,
            "chunks": 3,
            "entities": 4,
            "relationships": 5,
        }

    async def close(self):
        return None


def test_ingest_chunkshop_table_imports_records(monkeypatch):
    FakeGraphRAG.instances = []

    def fake_fetch(dsn, **kwargs):
        assert dsn == "postgresql://pgrg"
        assert kwargs["schema"] == "kb"
        assert kwargs["table"] == "chunks"
        assert kwargs["source_prefix"] == "chunkshop"
        assert kwargs["skip_llm"] is True
        return [{"text": "doc", "source_id": "chunkshop:doc", "pre_chunked": []}]

    monkeypatch.setattr(cli, "GraphRAG", FakeGraphRAG)
    monkeypatch.setattr(chunkshop_bridge, "fetch_records_from_table", fake_fetch)

    result = CliRunner().invoke(
        main,
        [
            "--db",
            "postgresql://pgrg",
            "ingest-chunkshop-table",
            "--schema",
            "kb",
            "--table",
            "chunks",
            "--skip-llm",
            "-n",
            "imported",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Imported 1 Chunkshop docs" in result.output
    assert FakeGraphRAG.instances[0].namespace == "imported"


def test_ingest_chunkshop_table_imports_code_edges(monkeypatch):
    FakeGraphRAG.instances = []

    def fake_fetch_records(*args, **kwargs):
        return [{"text": "doc", "source_id": "chunkshop:doc", "pre_chunked": []}]

    def fake_fetch_edges(*args, **kwargs):
        assert kwargs["project_id"] == "kb_code"
        assert kwargs["min_confidence"] == 0.7
        return (
            [{"name": "pkg.alpha", "entity_type": "CODE_SYMBOL"}],
            [{"src": "pkg.alpha", "dst": "pkg.beta", "rel_type": "CALLS"}],
        )

    monkeypatch.setattr(cli, "GraphRAG", FakeGraphRAG)
    monkeypatch.setattr(chunkshop_bridge, "fetch_records_from_table", fake_fetch_records)
    monkeypatch.setattr(chunkshop_bridge, "fetch_code_edges_from_table", fake_fetch_edges)

    result = CliRunner().invoke(
        main,
        [
            "--db",
            "postgresql://pgrg",
            "ingest-chunkshop-table",
            "--schema",
            "kb",
            "--table",
            "chunks",
            "--with-code-edges",
            "--project-id",
            "kb_code",
            "--min-confidence",
            "0.7",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "imported code relationships: 1" in result.output
    record = FakeGraphRAG.instances[0].records[0]
    assert record["entities"][0]["name"] == "pkg.alpha"
    assert record["relationships"][0]["rel_type"] == "CALLS"


def test_ingest_chunkshop_table_requires_dsn_without_db():
    result = CliRunner().invoke(
        main,
        ["ingest-chunkshop-table", "--schema", "kb", "--table", "chunks"],
    )

    assert result.exit_code == 1
    assert "--chunkshop-dsn is required" in result.output
