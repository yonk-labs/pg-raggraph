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

SHORT_ANSWER_SYSTEM_PROMPT = """\
You answer factoid questions. Output ONLY the answer as a short noun phrase,
named entity, number, or date. No explanation, no reasoning, no citations,
no preamble, no quotation marks around the answer.

Examples:
- Q: "What is the capital of France?" → Paris
- Q: "Who wrote Hamlet?" → William Shakespeare
- Q: "When was Stanford founded?" → 1885

Constraints:
- ≤10 tokens. Single phrase. No sentences.
- If the context is insufficient to answer, output exactly: INSUFFICIENT
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
        entity_list = ", ".join(f"{e.name} ({e.entity_type})" for e in result.entities[:20])
        lines.append(f"Related entities: {entity_list}")
        lines.append("")

    if result.relationships:
        rel_lines = [
            f"  - {r.source} --[{r.rel_type}]--> {r.target}" for r in result.relationships[:10]
        ]
        lines.append("Related relationships:")
        lines.extend(rel_lines)

    return "\n".join(lines)


def _fallback_answer(question: str, result: QueryResult, config: PGRGConfig) -> str:
    """Deterministic lede summary across all retrieved chunks (no LLM).

    Used when no LLM is configured or LLM synthesis fails. Returns a
    hint-biased summary plus source attribution. Falls back to a plain
    not-found message only when summarization yields nothing.
    """
    from pg_raggraph.summary import summarize_chunks

    summary = summarize_chunks(question, result, config)
    if not summary:
        return "No relevant content found in the knowledge base."
    sources = ", ".join(sorted({c.document_source or "unknown" for c in result.chunks}))
    return f"{summary}\n\n(Sources: {sources})"


async def generate_answer(
    question: str,
    result: QueryResult,
    llm: LLMProvider | None,
    config: PGRGConfig,
    short_answer: bool = False,
) -> str:
    """Generate an answer from retrieved chunks using an LLM.

    Gracefully degrades when LLM is unavailable — returns a fallback
    summary of the top chunk so the library is still useful without
    any LLM configured.

    When ``short_answer=True``, switches to a factoid prompt that returns
    a short noun phrase / named entity / number — useful for SQuAD-style
    benchmarks (MuSiQue, HotpotQA) where gold answers are short strings.
    """
    if not result.chunks:
        return "No relevant content found in the knowledge base."

    # mode="summary" / smart tier-0 already produced a deterministic summary —
    # ship it without an LLM round-trip. In short_answer mode the caller wants
    # a factoid phrase, not an extractive summary, so fall through to the LLM.
    if result.summary and not short_answer:
        return result.summary

    if llm is None:
        return _fallback_answer(question, result, config)

    context = _format_context(result)
    system_prompt = SHORT_ANSWER_SYSTEM_PROMPT if short_answer else ANSWER_SYSTEM_PROMPT

    messages = [
        {"role": "system", "content": system_prompt},
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
        return _fallback_answer(question, result, config)
