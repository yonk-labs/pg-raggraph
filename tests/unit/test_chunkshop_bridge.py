from __future__ import annotations

import pytest

from pg_raggraph.chunkshop_bridge import (
    attach_code_edges,
    code_edges_to_known_graph,
    rows_to_records,
)


def _row(**overrides):
    base = {
        "doc_id": "docs/a.md",
        "seq_num": 0,
        "original_content": "Original text.",
        "embedded_content": "Heading\n\nOriginal text.",
        "embedding": "[0.1,0.2,0.3]",
        "metadata": {"path": "docs/a.md", "language": "en"},
        "tags": ["alpha", "beta"],
        "source": "docs",
    }
    base.update(overrides)
    return base


def test_rows_to_records_groups_chunks_by_doc_id():
    records = rows_to_records(
        [
            _row(seq_num=1, original_content="Second.", embedded_content="Second."),
            _row(seq_num=0, original_content="First.", embedded_content="First."),
            _row(doc_id="docs/b.md", seq_num=0, original_content="Other.", embedding=[0.4, 0.5]),
        ]
    )

    assert [r["source_id"] for r in records] == ["chunkshop:docs/a.md", "chunkshop:docs/b.md"]
    first = records[0]
    assert first["text"] == "First.\n\nSecond."
    assert first["metadata"] == {"source": "chunkshop", "chunkshop_doc_id": "docs/a.md"}
    assert [c["content"] for c in first["pre_chunked"]] == ["First.", "Second."]
    assert first["pre_chunked"][0]["embedding"] == [0.1, 0.2, 0.3]
    assert first["pre_chunked"][0]["metadata"]["tags"] == ["alpha", "beta"]
    assert first["pre_chunked"][0]["metadata"]["chunkshop_doc_id"] == "docs/a.md"
    assert first["pre_chunked"][0]["metadata"]["chunkshop_seq_num"] == 0


def test_rows_to_records_can_skip_llm_for_vector_only_import():
    records = rows_to_records([_row()], skip_llm=True)
    assert records[0]["skip_llm"] is True


def test_rows_to_records_rejects_missing_doc_id():
    with pytest.raises(ValueError, match="doc_id"):
        rows_to_records([_row(doc_id="")])


def test_rows_to_records_rejects_missing_embedding():
    with pytest.raises(ValueError, match="NULL embedding"):
        rows_to_records([_row(embedding=None)])


def _edge(**overrides):
    base = {
        "project_id": "kb_code",
        "edge_type": "CALLS",
        "src_fqn": "pkg.example.alpha",
        "dst_fqn": "pkg.example.beta",
        "src_node_id": "node-src",
        "dst_node_id": "node-dst",
        "confidence": 0.9,
        "evidence": {"line": 12, "snippet": "return beta()", "resolution": "unique_name"},
    }
    base.update(overrides)
    return base


def test_code_edges_to_known_graph_preserves_provenance():
    entities, relationships = code_edges_to_known_graph([_edge()])

    assert [e["name"] for e in entities] == ["pkg.example.alpha", "pkg.example.beta"]
    assert all(e["entity_type"] == "CODE_SYMBOL" for e in entities)
    rel = relationships[0]
    assert rel["src"] == "pkg.example.alpha"
    assert rel["dst"] == "pkg.example.beta"
    assert rel["rel_type"] == "CALLS"
    assert rel["description"] == "return beta()"
    assert rel["weight"] == 0.9
    assert rel["properties"]["project_id"] == "kb_code"
    assert rel["properties"]["src_node_id"] == "node-src"
    assert rel["properties"]["dst_node_id"] == "node-dst"
    assert rel["properties"]["evidence"]["line"] == 12


def test_code_edges_to_known_graph_filters_low_confidence():
    entities, relationships = code_edges_to_known_graph(
        [_edge(confidence=0.5)],
        min_confidence=0.7,
    )
    assert entities == []
    assert relationships == []


def test_attach_code_edges_adds_graph_payload_to_first_record_only():
    records = rows_to_records(
        [
            _row(doc_id="docs/a.py", seq_num=0),
            _row(doc_id="docs/b.py", seq_num=0),
        ],
        skip_llm=True,
    )

    attach_code_edges(records, [_edge()])

    assert len(records[0]["entities"]) == 2
    assert len(records[0]["relationships"]) == 1
    assert "entities" not in records[1]
    assert "relationships" not in records[1]


def test_attach_code_edges_rejects_empty_records_when_edges_exist():
    with pytest.raises(ValueError, match="without at least one"):
        attach_code_edges([], [_edge()])


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
