"""Quality research diagnostics -- used for SC-001 QUALITY-ANALYSIS.md."""
from __future__ import annotations

import json
from typing import Any


async def top_k_sweep(
    engine: Any, questions: list[str], k_values: list[int]
) -> dict[int, list[dict[str, Any]]]:
    """Re-run the same questions at multiple ``top_k`` values and capture what
    the retriever returned at each setting.

    This is LLM-free: no judge call, no answer generation, no cost to track.
    The downstream research question -- does raising ``top_k`` recover missing
    facts? -- is answered later by running fact-recall over the captured chunks.

    Both ``PgrgEngine`` and ``AgeEngine`` expose ``_top_k`` as a mutable
    attribute; we set it before each batch of retrieves so the engine's
    retriever sees the new value. Engines without that attribute still run;
    they just can't be driven (the sweep degenerates to N copies of the same
    retrieval response, which is itself a useful diagnostic signal).

    Returned dict uses Python ``int`` keys. When written to JSON they become
    strings -- consumers should expect ``{"5": [...], "10": [...], ...}``.
    """
    out: dict[int, list[dict[str, Any]]] = {}
    for k in k_values:
        # Both PgrgEngine and AgeEngine expose _top_k; we set it to drive the retriever.
        if hasattr(engine, "_top_k"):
            engine._top_k = k
        runs: list[dict[str, Any]] = []
        for q in questions:
            resp = await engine.retrieve(q)
            runs.append(
                {
                    "question": q,
                    "chunk_ids": resp.retrieved_chunk_ids,
                    "contents": resp.retrieved_chunk_contents,
                    "retrieval_ms": resp.retrieval_ms,
                }
            )
        out[k] = runs
    return out


async def sample_gold_alternative_phrasings(
    client: Any,
    question: str,
    gold_answer: str,
    n: int,
    model: str,
    tracker: Any | None = None,
) -> list[str]:
    """Ask the judge model for N alternative phrasings of the gold answer that
    should still be judged fully_correct. Used to audit strictness.

    Caveat: generator and grader are typically the same judge model.
    ``strict_count > 0`` means either the gold is narrow OR the judge is
    internally inconsistent (generates X, then grades X as wrong) --
    QUALITY-ANALYSIS.md should distinguish these when citing these numbers.
    """
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
