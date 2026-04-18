"""LLM-judge scorer with 3x majority vote."""
from __future__ import annotations

import json
from enum import Enum
from typing import Any

from age_bakeoff.cost import CostTracker

_JUDGE_SYSTEM = """You are grading an AI-generated answer against a reference answer.

Return strict JSON: {"verdict": "fully_correct | partially_correct | wrong | hallucinated", "rationale": "one short sentence"}

Rubric:
- fully_correct: Contains every key fact from the reference. No contradictions.
- partially_correct: Contains some facts but misses important ones.
- wrong: Contradicts the reference or misses the main point.
- hallucinated: Invents facts not in the reference."""

_JUDGE_USER_TEMPLATE = """Question: {question}
Reference answer: {gold}
Generated answer: {generated}
Grade the generated answer."""


class JudgeVerdict(str, Enum):
    fully_correct = "fully_correct"
    partially_correct = "partially_correct"
    wrong = "wrong"
    hallucinated = "hallucinated"


_ORDINAL = {
    JudgeVerdict.fully_correct: 3,
    JudgeVerdict.partially_correct: 2,
    JudgeVerdict.wrong: 1,
    JudgeVerdict.hallucinated: 0,
}
_ORDINAL_REVERSE = {v: k for k, v in _ORDINAL.items()}


async def judge_answer(
    client: Any,
    question: str,
    gold_answer: str,
    generated_answer: str,
    model: str,
    tracker: CostTracker | None = None,
) -> JudgeVerdict:
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {
                "role": "user",
                "content": _JUDGE_USER_TEMPLATE.format(
                    question=question,
                    gold=gold_answer,
                    generated=generated_answer,
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    if tracker is not None and resp.usage is not None:
        tracker.record(
            model,
            resp.usage.prompt_tokens,
            resp.usage.completion_tokens,
        )
    content = resp.choices[0].message.content or "{}"
    data = json.loads(content)
    return JudgeVerdict(data["verdict"])


def majority_verdict(verdicts: list[JudgeVerdict]) -> JudgeVerdict:
    """3x majority vote with ordinal tiebreak."""
    if not verdicts:
        return JudgeVerdict.wrong
    counts: dict[JudgeVerdict, int] = {}
    for v in verdicts:
        counts[v] = counts.get(v, 0) + 1
    max_count = max(counts.values())
    winners = [v for v, c in counts.items() if c == max_count]
    if len(winners) == 1:
        return winners[0]
    # Tiebreak: average ordinal, round to nearest
    avg = sum(_ORDINAL[v] for v in verdicts) / len(verdicts)
    return _ORDINAL_REVERSE.get(
        round(avg), JudgeVerdict.partially_correct
    )
