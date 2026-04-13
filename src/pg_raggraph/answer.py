"""Answer synthesis from retrieved chunks.

Takes a QueryResult (chunks + entities + relationships) and asks an LLM
to produce a grounded answer with citations. Works gracefully when no
LLM is configured — returns chunk summary as fallback.
"""

from __future__ import annotations

import logging

from pg_raggraph.config import PGRGConfig
from pg_raggraph.extraction import LLMProvider
from pg_raggraph.models import QueryResult

logger = logging.getLogger("pg_raggraph.answer")

ANSWER_SYSTEM_PROMPT = """\
You are a helpful research assistant. You answer questions using only the
provided context chunks. If the context doesn't contain the answer, say so.

Rules:
- Ground every claim in the provided chunks. If you cite a claim, reference
  its source document in the format [source: filename].
- Prefer quoting specific details over making general claims.
- Keep answers concise. No preamble like "Based on the provided context...".
- If the context is insufficient, say exactly what's missing.
- Do not hallucinate facts not present in the chunks.
"""


def _format_context(result: QueryResult, max_chunks: int = 8) -> str:
    """Format retrieved chunks as LLM context."""
    lines = []
    for i, chunk in enumerate(result.chunks[:max_chunks], 1):
        source = chunk.document_source or "unknown"
        lines.append(f"[Chunk {i} — source: {source}]")
        lines.append(chunk.content)
        lines.append("")

    if result.entities:
        entity_list = ", ".join(
            f"{e.name} ({e.entity_type})" for e in result.entities[:20]
        )
        lines.append(f"Related entities: {entity_list}")
        lines.append("")

    if result.relationships:
        rel_lines = [
            f"  - {r.source} --[{r.rel_type}]--> {r.target}"
            for r in result.relationships[:10]
        ]
        lines.append("Related relationships:")
        lines.extend(rel_lines)

    return "\n".join(lines)


def _fallback_answer(result: QueryResult) -> str:
    """Assemble a readable summary from chunks when no LLM is available.

    Used when the caller doesn't have an LLM configured. Returns the top
    chunk's content as-is with source attribution — no synthesis, no
    paraphrasing, but still useful.
    """
    if not result.chunks:
        return "No relevant content found in the knowledge base."
    top = result.chunks[0]
    source = top.document_source or "unknown source"
    text = top.content.strip()
    if len(text) > 600:
        text = text[:600] + "..."
    return (
        f"No LLM configured for answer synthesis. Top match from {source}:\n\n"
        f"{text}\n\n"
        f"(pg-raggraph returned {len(result.chunks)} chunks. "
        f"Set PGRG_LLM_BASE_URL to enable answer generation.)"
    )


async def generate_answer(
    question: str,
    result: QueryResult,
    llm: LLMProvider | None,
    config: PGRGConfig,
) -> str:
    """Generate an answer from retrieved chunks using an LLM.

    Gracefully degrades when LLM is unavailable — returns a fallback
    summary of the top chunk so the library is still useful without
    any LLM configured.
    """
    if not result.chunks:
        return "No relevant content found in the knowledge base."

    if llm is None:
        return _fallback_answer(result)

    context = _format_context(result)

    messages = [
        {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Question: {question}\n\nContext:\n{context}\n\nAnswer:",
        },
    ]

    try:
        # answer generation uses a plain (non-JSON) response — we reuse the
        # httpx LLM client but skip the response_format constraint by calling
        # complete_text() if available, else falling back to complete()
        from pg_raggraph.extraction import HttpxLLMProvider

        if isinstance(llm, HttpxLLMProvider):
            return await llm.complete_text(messages)
        # Generic path: use complete() and hope the LLM ignores the JSON hint
        return await llm.complete(messages)
    except Exception as e:
        logger.warning(f"Answer generation failed: {e}")
        return _fallback_answer(result)
