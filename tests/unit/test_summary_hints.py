"""Unit tests for the lede-hint summary pipeline and QueryResult.summary."""

from __future__ import annotations

from pg_raggraph.models import ChunkResult, QueryResult


def test_query_result_has_summary_field_default_empty():
    qr = QueryResult(chunks=[ChunkResult(content="x", score=0.9)])
    assert qr.summary == ""


def test_query_result_summary_roundtrips():
    qr = QueryResult(summary="a deterministic summary")
    assert qr.summary == "a deterministic summary"
    assert qr.model_dump()["summary"] == "a deterministic summary"
