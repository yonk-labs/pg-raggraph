"""Unit tests for generate_answer summary/fallback behavior (no DB)."""

from __future__ import annotations

import pytest

from pg_raggraph.answer import generate_answer
from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import ChunkResult, QueryResult

pytestmark = pytest.mark.asyncio


class _ExplodingLLM:
    """Asserts it is never called."""

    async def complete_text(self, messages):
        raise AssertionError("LLM must not be called when summary is present")

    async def complete(self, messages):
        raise AssertionError("LLM must not be called when summary is present")


async def test_populated_summary_skips_llm():
    result = QueryResult(
        summary="John Smith lives in Cook County.",
        chunks=[ChunkResult(content="John Smith lives in Cook County.", score=0.9)],
    )
    answer = await generate_answer("where?", result, _ExplodingLLM(), PGRGConfig())
    assert answer == "John Smith lives in Cook County."  # SC-006: zero LLM calls


async def test_no_llm_falls_back_to_lede_summary():
    result = QueryResult(
        chunks=[
            ChunkResult(
                content="John Smith lives in Cook County and pays county taxes.",
                score=0.8,
                document_source="smith.txt",
            ),
            ChunkResult(
                content="The county council raised property taxes.",
                score=0.6,
                document_source="budget.txt",
            ),
        ]
    )
    answer = await generate_answer("what county?", result, None, PGRGConfig())
    assert answer  # non-empty
    assert "INSUFFICIENT" not in answer
    assert "smith.txt" in answer  # SC-007: source attribution preserved


async def test_no_chunks_returns_not_found():
    answer = await generate_answer("q", QueryResult(), None, PGRGConfig())
    assert answer == "No relevant content found in the knowledge base."


class _FactoidLLM:
    """Returns a canned short answer; records that it was called."""

    def __init__(self):
        self.called = False

    async def complete_text(self, messages):
        self.called = True
        return "Cook County"

    async def complete(self, messages):
        self.called = True
        return "Cook County"


async def test_short_answer_bypasses_precomputed_summary():
    result = QueryResult(
        summary="A long extractive summary about John Smith and Cook County and taxes.",
        chunks=[ChunkResult(content="John Smith lives in Cook County.", score=0.9)],
    )
    llm = _FactoidLLM()
    answer = await generate_answer("what county?", result, llm, PGRGConfig(), short_answer=True)
    assert llm.called  # short_answer must reach the LLM, not short-circuit on summary
    assert answer == "Cook County"
