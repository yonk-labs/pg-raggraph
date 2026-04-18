"""Quality research diagnostics -- used for SC-001 QUALITY-ANALYSIS.md."""
from __future__ import annotations

import json
from typing import Any


async def sample_gold_alternative_phrasings(
    client: Any,
    question: str,
    gold_answer: str,
    n: int,
    model: str,
    tracker: Any | None = None,
) -> list[str]:
    """Ask the judge model for N alternative phrasings of the gold answer that
    should still be judged fully_correct. Used to audit strictness."""
    prompt = (
        f"Question: {question}\nCanonical answer: {gold_answer}\n\n"
        f"Produce {n} alternative answers that are factually equivalent but "
        f"worded differently. Return JSON: {{\"alternatives\": [str, ...]}}."
    )
    resp = await client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker is not None and resp.usage is not None:
        tracker.record(
            model, resp.usage.prompt_tokens, resp.usage.completion_tokens
        )
    data = json.loads(
        resp.choices[0].message.content or '{"alternatives": []}'
    )
    return data.get("alternatives", [])[:n]
