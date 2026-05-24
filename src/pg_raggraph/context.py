"""Context packing strategies used by retrieval profiles and benchmarks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from pg_raggraph.chunking import token_count
from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import QueryResult
from pg_raggraph.profiles import ProfileSpec, resolve_profile

_COVERAGE_RE = re.compile(r"@(\d+)$")
_PLUS_TOP_N = 5
_DENSITY_MULTIPLIERS = {
    "doc_summary_facts_x1_5": 1.5,
    "doc_summary_facts_x2": 2.0,
    "doc_summary_facts_x3": 3.0,
}


@dataclass(frozen=True)
class SelectedDocument:
    """Full reconstructed document selected from retrieved chunks."""

    source_id: str
    text: str
    document_id: int | None = None


@dataclass(frozen=True)
class PackedContext:
    """Packed answer context plus accounting metadata."""

    chunks: tuple[str, ...]
    text: str
    context_strategy: str
    top_k: int
    source_tokens: int
    context_tokens: int
    selected_documents: tuple[str, ...]
    skipped: bool = False
    error: str | None = None


def _coverage(strategy: str) -> tuple[str, int | None]:
    match = _COVERAGE_RE.search(strategy)
    if match:
        return strategy[: match.start()], int(match.group(1))
    return strategy, None


def _chunks_text(chunks: Iterable[str]) -> str:
    return "\n\n".join(chunks)


def _context_tokens(chunks: Iterable[str]) -> int:
    return token_count(_chunks_text(chunks))


def _budget_for_tokens(source_tokens: int) -> int:
    return min(64_000, max(8_000, int(source_tokens * 4 * 0.12)))


def _summarize_facts(
    text: str,
    question: str,
    *,
    max_length: int,
    max_facts: int,
    include_toc: bool,
    use_hints: bool,
    config: PGRGConfig,
) -> str:
    """Summarize text with lede, appending key facts when available."""

    if not text.strip():
        return ""

    import lede
    from lede.extract import key_facts, toc, top_terms

    hints = None
    if use_hints:
        hints = [term for term in top_terms(question, n=8) if term and term.strip()] or None

    parts: list[str] = []
    if include_toc:
        outline = toc(text)
        if outline:
            parts.append("Table of contents:\n" + "\n".join(str(item) for item in outline))

    summary = lede.summarize(
        text,
        max_length=max_length,
        hints=hints,
        hint_focus=0.5,
        hint_mode="soft",
        keep_headings=True,
    ).summary
    if summary:
        parts.append(summary)
    facts = key_facts(text, max_facts=max_facts, hints=hints)
    if facts:
        parts.append("Key facts:\n" + "\n".join(f"- {fact}" for fact in facts))
    return "\n\n".join(parts)


def _pack(
    *,
    chunks: list[str],
    source_tokens: int,
    selected_documents: list[str],
    strategy: str,
    top_k: int,
    skipped: bool = False,
    error: str | None = None,
) -> PackedContext:
    return PackedContext(
        chunks=tuple(chunks),
        text=_chunks_text(chunks),
        context_strategy=strategy,
        top_k=top_k,
        source_tokens=source_tokens,
        context_tokens=_context_tokens(chunks),
        selected_documents=tuple(selected_documents),
        skipped=skipped,
        error=error,
    )


def assemble_context(
    *,
    question: str,
    result: QueryResult,
    documents: list[SelectedDocument],
    profile: ProfileSpec | str | int | float | None = None,
    config: PGRGConfig | None = None,
    max_context_tokens: int = 120_000,
) -> PackedContext:
    """Assemble answer context for a resolved profile or strategy.

    This mirrors the benchmark matrix packers for the calibrated ladder. It
    leaves retrieval ranking untouched: callers pass the retrieved chunks and
    the parent documents selected from those chunks.
    """

    cfg = config or PGRGConfig()
    spec = profile if isinstance(profile, ProfileSpec) else resolve_profile(profile)
    strategy = spec.context_strategy
    retrieved_chunks = result.chunks[: spec.top_k]
    retrieved_text = "\n\n".join(chunk.content for chunk in retrieved_chunks)
    retrieved_tokens = token_count(retrieved_text)
    selected_ids = [doc.source_id for doc in documents]

    base_name, coverage_n = _coverage(strategy)
    if base_name in {"full_selected_docs", "doc_summary_facts", "per_doc_summary_facts"} and (
        coverage_n is not None or base_name == "per_doc_summary_facts"
    ):
        selected = documents[:coverage_n] if coverage_n else documents
        selected_ids = [doc.source_id for doc in selected]
        selected_text = "\n\n".join(doc.text for doc in selected)
        selected_tokens = token_count(selected_text)
        if not selected:
            return _pack(
                chunks=[],
                source_tokens=0,
                selected_documents=selected_ids,
                strategy=strategy,
                top_k=spec.top_k,
                skipped=True,
                error="no selected documents for coverage strategy",
            )
        if base_name == "full_selected_docs":
            chunks = [doc.text for doc in selected]
            context_tokens = _context_tokens(chunks)
            error = (
                f"context_tokens {context_tokens} exceeds max_context_tokens {max_context_tokens}"
                if context_tokens > max_context_tokens
                else None
            )
            return _pack(
                chunks=chunks,
                source_tokens=selected_tokens,
                selected_documents=selected_ids,
                strategy=strategy,
                top_k=spec.top_k,
                skipped=error is not None,
                error=error,
            )
        if base_name == "doc_summary_facts":
            return _pack(
                chunks=[
                    _summarize_facts(
                        selected_text,
                        question,
                        max_length=_budget_for_tokens(selected_tokens),
                        max_facts=30,
                        include_toc=False,
                        use_hints=False,
                        config=cfg,
                    )
                ],
                source_tokens=selected_tokens,
                selected_documents=selected_ids,
                strategy=strategy,
                top_k=spec.top_k,
            )
        chunks = [
            f"[{doc.source_id}]\n"
            + _summarize_facts(
                doc.text,
                question,
                max_length=_budget_for_tokens(token_count(doc.text)),
                max_facts=12,
                include_toc=False,
                use_hints=False,
                config=cfg,
            )
            for doc in selected
        ]
        return _pack(
            chunks=chunks,
            source_tokens=selected_tokens,
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
        )

    if strategy == "per_doc5_chunksum_top5":
        selected = documents[:5]
        selected_ids = [doc.source_id for doc in selected]
        if not selected:
            return _pack(
                chunks=[],
                source_tokens=0,
                selected_documents=selected_ids,
                strategy=strategy,
                top_k=spec.top_k,
                skipped=True,
                error="no selected documents for per_doc5_chunksum_top5",
            )
        selected_text = "\n\n".join(doc.text for doc in selected)
        top5 = [chunk.content for chunk in retrieved_chunks[:_PLUS_TOP_N]]
        top5_text = "\n\n".join(top5)
        chunks = [
            f"[{doc.source_id}]\n"
            + _summarize_facts(
                doc.text,
                question,
                max_length=_budget_for_tokens(token_count(doc.text)),
                max_facts=12,
                include_toc=True,
                use_hints=True,
                config=cfg,
            )
            for doc in selected
        ]
        chunks.append(
            "Retrieved-chunk summary:\n"
            + _summarize_facts(
                retrieved_text,
                question,
                max_length=_budget_for_tokens(retrieved_tokens),
                max_facts=20,
                include_toc=False,
                use_hints=True,
                config=cfg,
            )
        )
        chunks.append(f"Top {_PLUS_TOP_N} chunks:\n{top5_text}")
        return _pack(
            chunks=chunks,
            source_tokens=token_count(selected_text) + retrieved_tokens + token_count(top5_text),
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
        )

    if strategy == "classic_chunks":
        chunks = [chunk.content for chunk in retrieved_chunks]
        return _pack(
            chunks=chunks,
            source_tokens=retrieved_tokens,
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
        )

    if strategy == "full_selected_docs":
        chunks = [doc.text for doc in documents]
        context_tokens = _context_tokens(chunks)
        error = (
            f"context_tokens {context_tokens} exceeds max_context_tokens {max_context_tokens}"
            if context_tokens > max_context_tokens
            else None
        )
        return _pack(
            chunks=chunks,
            source_tokens=token_count("\n\n".join(chunks)),
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
            skipped=error is not None,
            error=error,
        )

    doc_text = "\n\n".join(doc.text for doc in documents)
    doc_tokens = token_count(doc_text)
    if not doc_text.strip():
        return _pack(
            chunks=[],
            source_tokens=0,
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
            skipped=True,
            error="no selected documents for summary strategy",
        )

    if strategy == "doc_summary_facts":
        return _pack(
            chunks=[
                _summarize_facts(
                    doc_text,
                    question,
                    max_length=_budget_for_tokens(doc_tokens),
                    max_facts=30,
                    include_toc=False,
                    use_hints=False,
                    config=cfg,
                )
            ],
            source_tokens=doc_tokens,
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
        )

    if strategy == "hint_doc_summary_facts":
        return _pack(
            chunks=[
                _summarize_facts(
                    doc_text,
                    question,
                    max_length=_budget_for_tokens(doc_tokens),
                    max_facts=30,
                    include_toc=False,
                    use_hints=True,
                    config=cfg,
                )
            ],
            source_tokens=doc_tokens,
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
        )

    if strategy == "doc_summary_toc_facts":
        return _pack(
            chunks=[
                _summarize_facts(
                    doc_text,
                    question,
                    max_length=_budget_for_tokens(doc_tokens),
                    max_facts=30,
                    include_toc=True,
                    use_hints=True,
                    config=cfg,
                )
            ],
            source_tokens=doc_tokens,
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
        )

    if strategy in {"doc_summary_facts_plus_chunks", "hint_doc_summary_facts_plus_chunks"}:
        use_hints = strategy.startswith("hint_")
        summary = _summarize_facts(
            doc_text,
            question,
            max_length=_budget_for_tokens(doc_tokens),
            max_facts=30,
            include_toc=False,
            use_hints=use_hints,
            config=cfg,
        )
        return _pack(
            chunks=[summary, f"Retrieved chunks:\n{retrieved_text}"],
            source_tokens=doc_tokens + retrieved_tokens,
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
        )

    if strategy == "toc_doc_summary_plus_chunk_summary":
        doc_summary = _summarize_facts(
            doc_text,
            question,
            max_length=_budget_for_tokens(doc_tokens),
            max_facts=30,
            include_toc=True,
            use_hints=True,
            config=cfg,
        )
        chunk_summary = _summarize_facts(
            retrieved_text,
            question,
            max_length=max(2000, min(16_000, retrieved_tokens * 2)),
            max_facts=12,
            include_toc=False,
            use_hints=True,
            config=cfg,
        )
        return _pack(
            chunks=[doc_summary, f"Retrieved summary:\n{chunk_summary}"],
            source_tokens=doc_tokens + retrieved_tokens,
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
        )

    if strategy in _DENSITY_MULTIPLIERS:
        budget = int(_budget_for_tokens(doc_tokens) * _DENSITY_MULTIPLIERS[strategy])
        return _pack(
            chunks=[
                _summarize_facts(
                    doc_text,
                    question,
                    max_length=budget,
                    max_facts=30,
                    include_toc=False,
                    use_hints=False,
                    config=cfg,
                )
            ],
            source_tokens=doc_tokens,
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
        )

    if strategy == "chunk_summary_facts":
        return _pack(
            chunks=[
                _summarize_facts(
                    retrieved_text,
                    question,
                    max_length=_budget_for_tokens(retrieved_tokens),
                    max_facts=30,
                    include_toc=False,
                    use_hints=False,
                    config=cfg,
                )
            ],
            source_tokens=retrieved_tokens,
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
        )

    if strategy == "doc_and_chunk_summary_facts":
        doc_summary = _summarize_facts(
            doc_text,
            question,
            max_length=_budget_for_tokens(doc_tokens),
            max_facts=30,
            include_toc=False,
            use_hints=False,
            config=cfg,
        )
        chunk_summary = _summarize_facts(
            retrieved_text,
            question,
            max_length=_budget_for_tokens(retrieved_tokens),
            max_facts=30,
            include_toc=False,
            use_hints=False,
            config=cfg,
        )
        return _pack(
            chunks=[
                f"Document summary:\n{doc_summary}",
                f"Retrieved-chunk summary:\n{chunk_summary}",
            ],
            source_tokens=doc_tokens + retrieved_tokens,
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
        )

    if strategy in {"chunk_summary_toc_facts_plus_top5", "doc_summary_toc_facts_plus_top5"}:
        top5 = [chunk.content for chunk in retrieved_chunks[:_PLUS_TOP_N]]
        top5_text = "\n\n".join(top5)
        chunks: list[str] = []
        summarized_tokens = 0
        if strategy != "chunk_summary_toc_facts_plus_top5":
            chunks.append(
                "Document summary:\n"
                + _summarize_facts(
                    doc_text,
                    question,
                    max_length=_budget_for_tokens(doc_tokens),
                    max_facts=30,
                    include_toc=True,
                    use_hints=True,
                    config=cfg,
                )
            )
            summarized_tokens += doc_tokens
        if strategy != "doc_summary_toc_facts_plus_top5":
            chunks.append(
                "Retrieved-chunk summary:\n"
                + _summarize_facts(
                    retrieved_text,
                    question,
                    max_length=_budget_for_tokens(retrieved_tokens),
                    max_facts=30,
                    include_toc=True,
                    use_hints=True,
                    config=cfg,
                )
            )
            summarized_tokens += retrieved_tokens
        chunks.append(f"Top {_PLUS_TOP_N} chunks:\n{top5_text}")
        return _pack(
            chunks=chunks,
            source_tokens=summarized_tokens + token_count(top5_text),
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
        )

    if strategy == "doc_and_chunk_summary_toc_facts_plus_top5":
        top5 = [chunk.content for chunk in retrieved_chunks[:_PLUS_TOP_N]]
        top5_text = "\n\n".join(top5)
        chunks = [
            "Document summary:\n"
            + _summarize_facts(
                doc_text,
                question,
                max_length=_budget_for_tokens(doc_tokens),
                max_facts=30,
                include_toc=True,
                use_hints=True,
                config=cfg,
            ),
            "Retrieved-chunk summary:\n"
            + _summarize_facts(
                retrieved_text,
                question,
                max_length=_budget_for_tokens(retrieved_tokens),
                max_facts=30,
                include_toc=True,
                use_hints=True,
                config=cfg,
            ),
            f"Top {_PLUS_TOP_N} chunks:\n{top5_text}",
        ]
        return _pack(
            chunks=chunks,
            source_tokens=doc_tokens + retrieved_tokens + token_count(top5_text),
            selected_documents=selected_ids,
            strategy=strategy,
            top_k=spec.top_k,
        )

    raise ValueError(f"unknown context strategy {strategy!r}")


async def fetch_selected_documents(
    *,
    db,
    result: QueryResult,
    namespace: str,
    max_docs: int,
) -> list[SelectedDocument]:
    """Fetch parent documents for retrieved chunks, preserving retrieval order."""

    chunk_ids = [chunk.chunk_id for chunk in result.chunks if chunk.chunk_id is not None]
    if not chunk_ids or max_docs <= 0:
        return []

    rows = await db.fetch_all(
        """
        SELECT c.id AS chunk_id, d.id AS document_id, d.source_path
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.id = ANY(%s) AND d.namespace = %s
        """,
        (chunk_ids, namespace),
    )
    by_chunk = {int(row["chunk_id"]): row for row in rows}
    document_ids: list[int] = []
    seen: set[int] = set()
    for chunk_id in chunk_ids:
        row = by_chunk.get(int(chunk_id))
        if not row:
            continue
        doc_id = int(row["document_id"])
        if doc_id in seen:
            continue
        seen.add(doc_id)
        document_ids.append(doc_id)
        if len(document_ids) >= max_docs:
            break
    if not document_ids:
        return []

    doc_rows = await db.fetch_all(
        """
        SELECT d.id AS document_id,
               d.source_path,
               string_agg(c.content, E'\n\n' ORDER BY c.id) AS text
        FROM documents d
        JOIN chunks c ON c.document_id = d.id
        WHERE d.id = ANY(%s) AND d.namespace = %s
        GROUP BY d.id, d.source_path
        """,
        (document_ids, namespace),
    )
    by_doc = {int(row["document_id"]): row for row in doc_rows}
    out: list[SelectedDocument] = []
    for doc_id in document_ids:
        row = by_doc.get(doc_id)
        if not row:
            continue
        source_path = row.get("source_path")
        out.append(
            SelectedDocument(
                document_id=doc_id,
                source_id=str(source_path or f"document:{doc_id}"),
                text=str(row.get("text") or ""),
            )
        )
    return out


async def pack_query_context(
    *,
    question: str,
    result: QueryResult,
    db,
    namespace: str,
    profile: ProfileSpec | str | int | float | None = None,
    config: PGRGConfig | None = None,
    max_context_tokens: int = 120_000,
) -> PackedContext:
    """Fetch selected documents and assemble packed context for a query."""

    spec = profile if isinstance(profile, ProfileSpec) else resolve_profile(profile)
    if spec.context_strategy == "classic_chunks":
        return assemble_context(
            question=question,
            result=result,
            documents=[],
            profile=spec,
            config=config,
            max_context_tokens=max_context_tokens,
        )

    _, coverage_n = _coverage(spec.context_strategy)
    max_docs = coverage_n or 10
    if spec.context_strategy == "per_doc5_chunksum_top5":
        max_docs = 5
    documents = await fetch_selected_documents(
        db=db,
        result=result,
        namespace=namespace,
        max_docs=max_docs,
    )
    return assemble_context(
        question=question,
        result=result,
        documents=documents,
        profile=spec,
        config=config,
        max_context_tokens=max_context_tokens,
    )
