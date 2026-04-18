"""Shared OpenAI answer generation — identical path for both engines."""
from __future__ import annotations

import logging

from openai import AsyncOpenAI

from age_bakeoff.cost import CostTracker

logger = logging.getLogger(__name__)

_ANSWER_SYSTEM = """You answer questions using only the provided context chunks. If the context does not contain the answer, say so. Be concise — 1-3 sentences unless the question demands more."""

_ANSWER_USER_TEMPLATE = """Question: {question}

Context:
{context}

Answer:"""


async def generate_answer(
    question: str,
    retrieved_contents: list[str],
    model: str,
    tracker: CostTracker | None = None,
) -> str:
    client = AsyncOpenAI()
    context = "\n\n---\n\n".join(retrieved_contents)
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _ANSWER_SYSTEM},
            {"role": "user", "content": _ANSWER_USER_TEMPLATE.format(question=question, context=context)},
        ],
        temperature=0,
    )
    if tracker is not None and resp.usage is not None:
        tracker.record(
            model,
            resp.usage.prompt_tokens,
            resp.usage.completion_tokens,
        )
    elif tracker is not None and resp.usage is None:
        logger.warning(
            "OpenAI response missing usage; cost not tracked for this call"
        )
    return resp.choices[0].message.content or ""
