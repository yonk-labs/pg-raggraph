"""LLM-judged per-chunk relevance. Used for SC-001 context quality analysis."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def score_chunk_relevance(
    client: Any,
    question: str,
    chunks: list[str],
    model: str,
    tracker: Any | None = None,
) -> list[float]:
    """Return per-chunk relevance in [0,1]. Judge model decides.

    Empty ``chunks`` returns ``[]`` without making an API call -- important so
    diagnose-loops over corpora with legacy raw JSON (pre-``retrieved_chunk_contents``)
    don't burn budget on no-op calls.

    The response is padded with ``0.0`` (or truncated) to match ``len(chunks)``
    so downstream consumers never crash on a malformed judge response.
    """
    if not chunks:
        return []
    joined = "\n\n".join(f"[{i}] {c[:1200]}" for i, c in enumerate(chunks))
    prompt = (
        f"Question: {question}\n\nChunks:\n{joined}\n\n"
        "For each chunk, rate relevance to the question in [0,1] where 1 means "
        "fully answers or directly supports the answer. Return JSON: "
        '{"relevances": [float, ...]}. Length must match number of chunks.'
    )
    resp = await client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        **({"temperature": 0} if not model.startswith(("gpt-5","o1","o3")) else {}),
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker is not None and resp.usage is not None:
        tracker.record(
            model, resp.usage.prompt_tokens, resp.usage.completion_tokens
        )
    data = json.loads(resp.choices[0].message.content or '{"relevances": []}')
    scores = data.get("relevances", [])
    # Pad/truncate to match chunks length so downstream consumers don't crash
    if len(scores) < len(chunks):
        logger.warning(
            "chunk_relevance judge returned %d scores for %d chunks; "
            "padding with 0.0 (model=%s)", len(scores), len(chunks), model,
        )
        scores = list(scores) + [0.0] * (len(chunks) - len(scores))
    elif len(scores) > len(chunks):
        logger.warning(
            "chunk_relevance judge returned %d scores for %d chunks; "
            "truncating (model=%s)", len(scores), len(chunks), model,
        )
    return scores[: len(chunks)]
