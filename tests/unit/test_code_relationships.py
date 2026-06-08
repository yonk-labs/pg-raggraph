"""Unit tests for the in-process symbol-graph extraction seam (#74/#75)."""

from __future__ import annotations

import pytest

from pg_raggraph.chunkshop_bridge import (
    code_edges_to_known_graph,
    extract_symbol_graph,
)

chunkshop = pytest.importorskip("chunkshop")
chunkshop_config = pytest.importorskip("chunkshop.config")
pytest.importorskip("tree_sitter_python")  # regex fallback degrades parses

pytestmark = pytest.mark.skipif(
    not hasattr(chunkshop_config, "SymbolAwareChunker"),
    reason="chunkshop build does not expose SymbolAwareChunker",
)

_CODE_SRC = '''\
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


def _symbol_chunks(src: str, source_path: str = "sample.py"):
    from chunkshop.chunkers import load_chunker
    from chunkshop.config import SymbolAwareChunker as SymCfg
    from chunkshop.sources.base import Document

    doc = Document(
        id=source_path,
        content=src,
        title="sample",
        metadata={"source_path": source_path},
    )
    return load_chunker(SymCfg(type="symbol_aware", max_chars=4000)).chunk(doc)


def test_extract_symbol_graph_callees_and_edges():
    cs_chunks = _symbol_chunks(_CODE_SRC)
    sg = extract_symbol_graph(
        _CODE_SRC, cs_chunks, source_path="sample.py", project_id="sample.py"
    )
    assert sg is not None
    assert len(sg.callees_by_index) == len(cs_chunks)

    # The chunk that defines `runner` records a call to `helper`.
    runner_idx = next(
        i for i, c in enumerate(cs_chunks) if (c.metadata or {}).get("fqn") == "sample.runner"
    )
    runner_callees = {d["name"] for d in sg.callees_by_index[runner_idx]}
    assert "helper" in runner_callees

    edge_set = {(e["edge_type"], e["src_fqn"], e["dst_fqn"]) for e in sg.edges}
    assert ("CALLS", "sample.runner", "sample.helper") in edge_set
    assert ("INHERITS", "sample.Child", "sample.Base") in edge_set


def test_extract_symbol_graph_none_when_extractor_unavailable(monkeypatch):
    import pg_raggraph.chunkshop_bridge as bridge

    real_import = __import__

    def _block(name, *args, **kwargs):
        if name == "chunkshop.extractors":
            raise ImportError("simulated: no extractor in this chunkshop build")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _block)
    assert (
        bridge.extract_symbol_graph(_CODE_SRC, _symbol_chunks(_CODE_SRC), source_path="x.py")
        is None
    )


def test_finalize_edges_feed_code_edges_to_known_graph():
    # The linchpin: finalize()-shaped edge dicts map cleanly via the EXISTING
    # Pattern C mapper. Hand-crafted so this is pure (no chunkshop needed at run).
    edges = [
        {
            "edge_type": "CALLS",
            "src_fqn": "m.runner",
            "dst_fqn": "m.helper",
            "src_node_id": "node-aaa",
            "dst_node_id": "node-bbb",
            "confidence": 0.9,
            "evidence": {"line": 6, "snippet": "return helper(y)", "resolution": "intra_file"},
        },
        {
            "edge_type": "INHERITS",
            "src_fqn": "m.Child",
            "dst_fqn": "m.Base",
            "src_node_id": "node-ccc",
            "dst_node_id": "node-ddd",
            "confidence": 0.9,
            "evidence": {"resolution": "unique_name"},
        },
    ]
    entities, rels = code_edges_to_known_graph(edges)
    names = {e["name"] for e in entities}
    assert names == {"m.runner", "m.helper", "m.Child", "m.Base"}
    assert all(e["entity_type"] == "CODE_SYMBOL" for e in entities)
    rel_set = {(r["src"], r["dst"], r["rel_type"]) for r in rels}
    assert ("m.runner", "m.helper", "CALLS") in rel_set
    assert ("m.Child", "m.Base", "INHERITS") in rel_set
