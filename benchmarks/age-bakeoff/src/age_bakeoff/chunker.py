"""Shared pre-chunker — both engines ingest the output of this module.

Responsibilities:
1. Prose: split on markdown headings, fall back to paragraph+sentence aggregation
2. Code (.py, .c, .h): split on top-level function/class/struct boundaries,
   fall back to hard 800-token split
3. Plain text: paragraph-aware hard split
4. Hierarchy: heading-aware with heading-as-prefix (ported from chunkshop,
   factorial-detour winner: C/nomic fp32 = 18/30 on scotus). Opt-in via
   ``strategy="hierarchy"`` on ``chunk_text()`` or the ``BAKEOFF_CHUNKER`` env
   flag in ``extraction.loaders``.

Determinism: given the same bytes on disk, produces byte-identical output.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from age_bakeoff.models import Chunk

_MAX_CHARS = 3000  # ~750 tokens for BAAI/bge-small-en-v1.5
_MIN_CHARS = 200
_HIER_MIN_SECTION_CHARS = 100  # match chunkshop HierarchyChunker default
# Default cap for hierarchy sub-splits (~500 tokens for bge-small-en-v1.5;
# comfortably inside the 512-token embedder ceiling). Mirrors the chunkshop
# HierarchyChunker max_chars default — tune up for embedders with larger
# context (e.g., text-embedding-3-small's 8191 tokens).
_HIER_DEFAULT_MAX_CHARS = 2000

_MD_HEADING = re.compile(r"^#{1,6}\s+.+$", re.MULTILINE)
_MD_HEADING_PARSE = re.compile(r"^(#{1,6})\s+(.+?)$", re.MULTILINE)
_PY_DEF = re.compile(r"^(def |class |async def )", re.MULTILINE)
_C_FUNC = re.compile(
    r"^(?:static\s+)?(?:[A-Za-z_][\w*\s]*)\s+\**[A-Za-z_]\w*\s*\([^;]*\)\s*\{",
    re.MULTILINE,
)
_C_STRUCT = re.compile(r"^(?:typedef\s+)?struct\s+[A-Za-z_]\w*", re.MULTILINE)

ChunkerStrategy = Literal["sentence_aware", "hierarchy"]


def chunk_file(path: str | Path) -> list[Chunk]:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    doc_id = str(p.name)
    ext = p.suffix.lower()
    if ext in (".md", ".sgml", ".rst", ".txt"):
        splits = _split_prose(text)
    elif ext in (".py",):
        splits = _split_python(text)
    elif ext in (".c", ".h"):
        splits = _split_c(text)
    else:
        splits = _split_plain(text)
    return _to_chunks(doc_id, splits, source_path=str(p))


def chunk_text(
    text: str,
    document_id: str,
    doc_type: str = "prose",
    strategy: ChunkerStrategy = "sentence_aware",
    title: str | None = None,
    max_chars: int = _HIER_DEFAULT_MAX_CHARS,
) -> list[Chunk]:
    """Split ``text`` into chunks for ingestion.

    ``strategy`` selects the chunker:
    - ``"sentence_aware"`` (default): preserves the original baseline. Heading
      or paragraph split, then heading-aware aggregation. Matches prior
      ``scotus.json`` raw results byte-identically.
    - ``"hierarchy"``: factorial-detour winner — prepends the section heading
      (or ``title`` when no headings exist) to each chunk so pgvector sees
      heading+body as one unit. Sections whose body exceeds ``max_chars`` are
      paragraph-aware sub-split; each sub-chunk carries the same heading
      prefix and ``metadata.section_part`` lets downstream callers rejoin.

    ``title`` only matters for ``strategy="hierarchy"``; ignored otherwise.
    ``max_chars`` only applies to ``strategy="hierarchy"``; sentence_aware
    uses the module-level ``_MAX_CHARS`` for its pre-existing baseline.
    """
    if strategy == "hierarchy":
        return _chunk_hierarchy(text, document_id, title=title, max_chars=max_chars)
    if strategy == "sentence_aware":
        splits = _split_plain(text) if doc_type == "code" else _split_prose(text)
        return _to_chunks(document_id, splits)
    raise ValueError(
        f"chunk_text: unknown strategy {strategy!r}; expected one of "
        "('sentence_aware', 'hierarchy')"
    )


def _chunk_hierarchy(
    text: str, document_id: str, title: str | None, max_chars: int
) -> list[Chunk]:
    """Hierarchy strategy — emits Chunks with heading + section_part metadata.

    Each section body larger than ``max_chars`` is paragraph-aware sub-split;
    every sub-chunk re-prefixes the heading so the embedder always sees
    ``heading + body`` as one unit.
    """
    sections = _split_hierarchy(text, title=title)
    chunks: list[Chunk] = []
    for heading, body in sections:
        if len(body) <= max_chars:
            sub_bodies = [body]
        else:
            sub_bodies = _split_body_paragraph_aware(body, max_chars)
        for part_idx, sub_body in enumerate(sub_bodies):
            sub_body = sub_body.strip()
            if not sub_body:
                continue
            content = f"{heading}\n\n{sub_body}" if heading else sub_body
            chunks.append(
                Chunk(
                    id=f"{document_id}::{len(chunks)}",
                    document_id=document_id,
                    content=content,
                    sequence=len(chunks),
                    metadata={
                        "heading": heading,
                        "section_part": part_idx,
                    },
                )
            )
    return chunks


def _split_prose(text: str) -> list[str]:
    headings = list(_MD_HEADING.finditer(text))
    if not headings:
        return _split_plain(text)
    result: list[str] = []
    for i, match in enumerate(headings):
        start = match.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        section = text[start:end].strip()
        if section:
            result.extend(_hard_split(section))
    # Prefix (anything before first heading) gets its own chunk(s)
    if headings[0].start() > 0:
        prefix = text[: headings[0].start()].strip()
        if prefix:
            result = _hard_split(prefix) + result
    # If the whole document is tiny (fits in one chunk), keep everything;
    # the MIN_CHARS filter is for dropping noise fragments in long docs.
    if len(text) <= _MAX_CHARS:
        return [s for s in result if s]
    return [s for s in result if len(s) >= _MIN_CHARS]


def _split_hierarchy(text: str, title: str | None = None) -> list[tuple[str, str]]:
    """Heading-aware section split. Returns list of ``(heading, body)`` pairs.

    Body has NO heading prefix — the caller (``_chunk_hierarchy``) is
    responsible for prepending ``{heading}\\n\\n`` when producing final chunk
    content, and for re-prefixing each sub-chunk when a section exceeds the
    configured max_chars.

    - One pair per markdown heading (H1–H6); body is the raw section text.
    - Pre-first-heading prefix becomes its own pair with ``title`` as heading.
    - No headings found: single pair = ``(title, body)`` (empty heading if
      title is empty). This is the scotus case — 0/772 docs have markdown
      headings, so the title-prefix fallback is the path that carried the
      factorial C/nomic = 18/30 result.
    - Sections shorter than ``_HIER_MIN_SECTION_CHARS`` are dropped in
      multi-heading docs, matching chunkshop so replication is faithful.
    """
    headings = list(_MD_HEADING_PARSE.finditer(text))
    title_prefix = (title or "").strip()

    if not headings:
        body = text.strip()
        if not body:
            return []
        return [(title_prefix, body)]

    result: list[tuple[str, str]] = []
    if headings[0].start() > 0:
        body = text[: headings[0].start()].strip()
        if len(body) >= _HIER_MIN_SECTION_CHARS:
            result.append((title_prefix, body))
    for i, m in enumerate(headings):
        heading_text = m.group(2).strip()
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[start:end].strip()
        if len(body) < _HIER_MIN_SECTION_CHARS:
            continue
        result.append((heading_text, body))
    return result


def _split_body_paragraph_aware(text: str, max_chars: int) -> list[str]:
    """Paragraph-aware hard split for a single section body.

    Walks paragraphs (split on blank lines), greedy-packs up to ``max_chars``,
    and hard-splits any single paragraph that itself exceeds the cap. Used by
    ``_chunk_hierarchy`` to sub-split oversized section bodies while keeping
    each sub-chunk aligned to natural prose boundaries when possible.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    result: list[str] = []
    buffer = ""
    for para in paragraphs:
        if len(para) > max_chars:
            if buffer:
                result.append(buffer.strip())
                buffer = ""
            for i in range(0, len(para), max_chars):
                result.append(para[i : i + max_chars])
        elif len(buffer) + len(para) + 2 > max_chars and buffer:
            result.append(buffer.strip())
            buffer = para
        else:
            buffer = f"{buffer}\n\n{para}" if buffer else para
    if buffer:
        result.append(buffer.strip())
    return result


def _split_python(text: str) -> list[str]:
    defs = list(_PY_DEF.finditer(text))
    if not defs:
        return _split_plain(text)
    result: list[str] = []
    # Module header
    if defs[0].start() > 0:
        header = text[: defs[0].start()].strip()
        if header:
            result.extend(_hard_split(header))
    for i, match in enumerate(defs):
        start = match.start()
        end = defs[i + 1].start() if i + 1 < len(defs) else len(text)
        block = text[start:end].strip()
        if block:
            result.extend(_hard_split(block))
    return result


def _split_c(text: str) -> list[str]:
    boundaries = sorted(
        [m.start() for m in _C_FUNC.finditer(text)] + [m.start() for m in _C_STRUCT.finditer(text)]
    )
    if not boundaries:
        return _split_plain(text)
    result: list[str] = []
    if boundaries[0] > 0:
        header = text[: boundaries[0]].strip()
        if header:
            result.extend(_hard_split(header))
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        block = text[start:end].strip()
        if block:
            result.extend(_hard_split(block))
    return result


def _split_plain(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    result: list[str] = []
    buffer = ""
    for para in paragraphs:
        if len(para) > _MAX_CHARS:
            if buffer:
                result.append(buffer.strip())
                buffer = ""
            result.extend(_hard_split(para))
        elif len(buffer) + len(para) + 2 > _MAX_CHARS and buffer:
            result.append(buffer.strip())
            buffer = para
        else:
            buffer = f"{buffer}\n\n{para}" if buffer else para
    if buffer:
        result.append(buffer.strip())
    return result


def _hard_split(text: str) -> list[str]:
    if len(text) <= _MAX_CHARS:
        return [text]
    out: list[str] = []
    for i in range(0, len(text), _MAX_CHARS):
        out.append(text[i : i + _MAX_CHARS])
    return out


def _to_chunks(document_id: str, splits: list[str], source_path: str | None = None) -> list[Chunk]:
    meta: dict = {}
    if source_path:
        meta["source_path"] = source_path
    return [
        Chunk(
            id=f"{document_id}::{i}",
            document_id=document_id,
            content=content,
            sequence=i,
            metadata=meta,
        )
        for i, content in enumerate(splits)
    ]
