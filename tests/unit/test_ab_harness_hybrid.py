"""Hybrid mode — vector-seeds + graph-rerank (verdict-completing).

Per the chunkshop emission contract §4.2, `hybrid` is the production-shaped
mode: the vector leg seeds the candidate set and the graph reranks those
candidates by entity overlap — it never entity-resolves the *question*, so it
sidesteps `graph_leg`'s weak-NER failure. These tests lock the deterministic
blend (`_blend_hybrid_candidates`); the DB walk is covered by the live run.
"""

from __future__ import annotations

from pg_raggraph.ab_gate.harness import _blend_hybrid_candidates


def _cand(doc_id, source, vscore):
    return {
        "id": doc_id,
        "document_id": doc_id,
        "source": source,
        "content": f"snip {source}",
        "vector_score": vscore,
    }


def test_shared_entities_boost_central_candidates():
    """Equal vector scores: docs sharing a node with others outrank an isolated doc."""
    cands = [_cand(1, "a", 0.80), _cand(2, "b", 0.80), _cand(3, "c", 0.80)]
    # d1 & d2 share "Apple"; d3 shares nothing → d1,d2 are graph-central.
    doc_nodes = {1: {"Apple", "X"}, 2: {"Apple", "Y"}, 3: {"Z"}}
    out = _blend_hybrid_candidates(cands, doc_nodes, top_k=3, graph_weight=0.5)
    sources = [it.source for it in out]
    assert sources.index("c") == 2  # isolated doc sinks to last
    assert set(sources[:2]) == {"a", "b"}
    assert [it.rank for it in out] == [1, 2, 3]


def test_graph_weight_zero_preserves_vector_order():
    cands = [_cand(1, "a", 0.9), _cand(2, "b", 0.7), _cand(3, "c", 0.5)]
    doc_nodes = {1: {"X"}, 2: {"X"}, 3: {"X"}}  # all shared, but weight 0 ignores it
    out = _blend_hybrid_candidates(cands, doc_nodes, top_k=3, graph_weight=0.0)
    assert [it.source for it in out] == ["a", "b", "c"]


def test_empty_doc_nodes_degrades_to_vector_order():
    """No facts/cooccur → centrality all zero → pure vector ranking (== naive)."""
    cands = [_cand(1, "a", 0.9), _cand(2, "b", 0.7)]
    out = _blend_hybrid_candidates(cands, {}, top_k=10, graph_weight=0.5)
    assert [it.source for it in out] == ["a", "b"]


def test_top_k_truncation():
    cands = [_cand(i, f"s{i}", 1.0 - i * 0.1) for i in range(5)]
    out = _blend_hybrid_candidates(cands, {}, top_k=3, graph_weight=0.5)
    assert len(out) == 3


def test_empty_candidates_empty_output():
    assert _blend_hybrid_candidates([], {}, top_k=10, graph_weight=0.5) == []
