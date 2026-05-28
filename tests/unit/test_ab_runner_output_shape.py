"""SC-009: run_harness_mode emits one ABCaseResult per GoldQuestion, in order."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pg_raggraph.ab_gate import GoldQuestion
from pg_raggraph.ab_gate.harness import run_harness_mode


@pytest.mark.asyncio
async def test_one_case_per_question_in_order():
    rag = MagicMock()
    rag._get_embedder.return_value.embed = AsyncMock(return_value=[[0.1] * 8])
    rag.db.fetch_all = AsyncMock(return_value=[])

    gold = [
        GoldQuestion(id="q1", question="first"),
        GoldQuestion(id="q2", question="second"),
        GoldQuestion(id="q3", question="third"),
    ]
    out = await run_harness_mode(
        rag, corpus_id="ns", mode="naive_vector", gold_questions=gold, top_k=10
    )
    assert out.corpus_id == "ns"
    assert out.mode == "naive_vector"
    assert [r.question_id for r in out.results] == ["q1", "q2", "q3"], (
        "ABCaseResults must be in the same order as input GoldQuestions"
    )
    assert all(r.latency_ms >= 0 for r in out.results)
