"""Shared OpenAI-compatible answer generation — identical path for all engines.

The endpoint is configurable via BAKEOFF_ANSWER_BASE_URL (default: OpenAI's
api.openai.com). Set it to a local vLLM / Ollama endpoint to run answer
generation on your own hardware for $0 cost. Model is selected via
BAKEOFF_ANSWER_MODEL. Any OpenAI-compatible API works.
"""
from __future__ import annotations

import logging
import os

from openai import AsyncOpenAI

from age_bakeoff.cost import CostTracker

logger = logging.getLogger(__name__)


from age_bakeoff.llm_clients import client_for


def _client() -> AsyncOpenAI:
    return client_for("answer")

_ANSWER_SYSTEM = """You answer questions using only the provided context chunks. If the context does not contain the answer, say so. Be concise — 1-3 sentences unless the question demands more."""

_ANSWER_USER_TEMPLATE = """Question: {question}

Context:
{context}

Answer:"""


def _truncate_chunks(contents: list[str], per_chunk_chars: int) -> list[str]:
    """Cap each chunk to ``per_chunk_chars`` so bulk context stays small.

    The hierarchy chunker can produce 50KB+ chunks on corpora with long
    topic sections (e.g. GraphRAG-Bench medical's 'bladder cancer' doc is
    134KB uncut). 10 such chunks = 500KB = ~130k tokens of context, which
    puts answer generation at 45-60s per call on the local LLM.
    Truncating each chunk to its first ~2000 chars keeps the signal
    (lead passages are usually most relevant) while dropping input tokens
    ~6x.
    """
    if per_chunk_chars <= 0:
        return contents
    out = []
    for c in contents:
        if len(c) <= per_chunk_chars:
            out.append(c)
        else:
            out.append(c[:per_chunk_chars] + "\n…[truncated]")
    return out


async def generate_answer(
    question: str,
    retrieved_contents: list[str],
    model: str,
    tracker: CostTracker | None = None,
) -> str:
    # BAKEOFF_ANSWER_CHUNK_CHARS (default 2000): cap per-chunk context size
    # sent to the LLM. Applied uniformly across engines so the fairness
    # constraint ("all engines see the same context budget") holds.
    per_chunk_chars = int(os.environ.get("BAKEOFF_ANSWER_CHUNK_CHARS", "2000"))
    retrieved_contents = _truncate_chunks(retrieved_contents, per_chunk_chars)

    client = _client()
    context = "\n\n---\n\n".join(retrieved_contents)
    # GPT-5 family (gpt-5, gpt-5-mini, gpt-5-nano) only accepts the default
    # temperature=1 — older gpt-4.1 / gpt-4o accepted 0 for determinism.
    # Detect + branch rather than hardcode either.
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": _ANSWER_SYSTEM},
            {"role": "user", "content": _ANSWER_USER_TEMPLATE.format(question=question, context=context)},
        ],
    }
    if not model.startswith(("gpt-5", "o1", "o3")):
        kwargs["temperature"] = 0
    resp = await client.chat.completions.create(**kwargs)
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
