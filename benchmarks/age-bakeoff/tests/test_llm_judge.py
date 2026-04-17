from unittest.mock import AsyncMock, MagicMock

import pytest

from age_bakeoff.scorers.llm_judge import (
    JudgeVerdict,
    judge_answer,
    majority_verdict,
)


def _mock_client(verdicts):
    client = MagicMock()
    responses = []
    for v in verdicts:
        msg = MagicMock()
        msg.message = MagicMock()
        msg.message.content = f'{{"verdict": "{v}", "rationale": "test"}}'
        completion = MagicMock()
        completion.choices = [msg]
        completion.usage = MagicMock(
            prompt_tokens=100, completion_tokens=20
        )
        responses.append(completion)
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=responses)
    return client


async def test_judge_parses():
    client = _mock_client(["fully_correct"])
    v = await judge_answer(
        client=client,
        question="?",
        gold_answer="a",
        generated_answer="a",
        model="test",
    )
    assert v == JudgeVerdict.fully_correct


async def test_judge_wrong():
    client = _mock_client(["wrong"])
    v = await judge_answer(
        client=client,
        question="?",
        gold_answer="a",
        generated_answer="b",
        model="test",
    )
    assert v == JudgeVerdict.wrong


def test_majority_clear():
    assert (
        majority_verdict(
            [
                JudgeVerdict.fully_correct,
                JudgeVerdict.fully_correct,
                JudgeVerdict.wrong,
            ]
        )
        == JudgeVerdict.fully_correct
    )


def test_majority_tie():
    result = majority_verdict(
        [JudgeVerdict.fully_correct, JudgeVerdict.wrong]
    )
    assert result == JudgeVerdict.partially_correct


def test_majority_empty():
    assert majority_verdict([]) == JudgeVerdict.wrong


def test_majority_unanimous():
    assert (
        majority_verdict(
            [
                JudgeVerdict.hallucinated,
                JudgeVerdict.hallucinated,
                JudgeVerdict.hallucinated,
            ]
        )
        == JudgeVerdict.hallucinated
    )
