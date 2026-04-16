"""Shared OpenAI answer generation — identical path for both engines."""
from __future__ import annotations

from openai import AsyncOpenAI

_ANSWER_SYSTEM = """You answer questions using only the provided context chunks. If the context does not contain the answer, say so. Be concise — 1-3 sentences unless the question demands more."""

_ANSWER_USER_TEMPLATE = """Question: {question}

Context:
{context}

Answer:"""


async def generate_answer(question: str, retrieved_contents: list[str], model: str) -> str:
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
    return resp.choices[0].message.content or ""
