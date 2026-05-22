"""Unit tests for the lede-hint summary pipeline and QueryResult.summary."""

from __future__ import annotations

from pg_raggraph import summary as summary_mod
from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import ChunkResult, QueryResult


def test_query_result_has_summary_field_default_empty():
    qr = QueryResult(chunks=[ChunkResult(content="x", score=0.9)])
    assert qr.summary == ""


def test_query_result_summary_roundtrips():
    qr = QueryResult(summary="a deterministic summary")
    assert qr.summary == "a deterministic summary"
    assert qr.model_dump()["summary"] == "a deterministic summary"


def test_seed_weights_are_deterministic_and_descending():
    q = "What county does John Smith live in and what taxes apply?"
    w1 = summary_mod._seed_weights(q, n=4)
    w2 = summary_mod._seed_weights(q, n=4)
    assert w1 == w2  # SC-002: deterministic
    weights = list(w1.values())
    assert weights == sorted(weights, reverse=True)  # rank 0 heaviest
    assert all(0.0 < v <= 1.0 for v in weights)


def test_build_hints_deterministic():
    cfg = PGRGConfig(query_expansion="moderate")
    q = "How does pgvector cosine similarity rank chunks?"
    assert summary_mod.build_hints(q, cfg) == summary_mod.build_hints(q, cfg)  # SC-002


def test_build_hints_respects_max_hints_cap():
    cfg = PGRGConfig(query_expansion="moderate", max_hints=2)
    q = "networking tcp packet routing latency throughput congestion window"
    hints = summary_mod.build_hints(q, cfg)
    assert len(hints) <= 2  # SC-003


def test_build_hints_empty_query_returns_empty():
    cfg = PGRGConfig(query_expansion="moderate")
    assert summary_mod.build_hints("", cfg) == {}


def test_aggressive_degrades_to_moderate_without_vector_model(monkeypatch):
    monkeypatch.setattr(summary_mod, "_has_vector_model", lambda: False)
    import pytest

    with pytest.warns(UserWarning, match="falling back to 'moderate'"):
        resolved = summary_mod._resolve_expansion_tier("aggressive")
    assert resolved == "moderate"  # SC-005


def test_aggressive_kept_when_vector_model_present(monkeypatch):
    monkeypatch.setattr(summary_mod, "_has_vector_model", lambda: True)
    import warnings as _w

    with _w.catch_warnings():
        _w.simplefilter("error")  # any warning would raise
        assert summary_mod._resolve_expansion_tier("aggressive") == "aggressive"


def test_moderate_tier_never_warns(monkeypatch):
    monkeypatch.setattr(summary_mod, "_has_vector_model", lambda: False)
    import warnings as _w

    with _w.catch_warnings():
        _w.simplefilter("error")
        assert summary_mod._resolve_expansion_tier("moderate") == "moderate"


def test_summarize_chunks_keeps_headings_by_default():
    cfg = PGRGConfig()  # summary_keep_headings defaults True
    result = QueryResult(
        chunks=[
            ChunkResult(
                content=(
                    "# Revenue Report\n\n"
                    "The company posted record revenue of twelve million dollars in Q3. "
                    "Revenue grew eighteen percent year over year and margins expanded "
                    "across every business unit during the reporting period."
                ),
                score=0.9,
            )
        ]
    )
    summary = summary_mod.summarize_chunks("what revenue?", result, cfg)
    assert "# Revenue Report" in summary  # heading survives extractive compression


def test_summarize_chunks_headings_off_is_respected():
    cfg = PGRGConfig(summary_keep_headings=False)
    result = QueryResult(
        chunks=[
            ChunkResult(content="# Heading\n\nBody sentence one. Body sentence two.", score=0.9)
        ]
    )
    # Must not raise and stays deterministic with the flag off.
    s1 = summary_mod.summarize_chunks("body", result, cfg)
    s2 = summary_mod.summarize_chunks("body", result, cfg)
    assert s1 == s2
