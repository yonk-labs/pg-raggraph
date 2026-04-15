"""Shared pre-chunker — both engines ingest the output of this module.

Responsibilities:
1. Prose: split on markdown headings, fall back to paragraph+sentence aggregation
2. Code (.py, .c, .h): split on top-level function/class/struct boundaries,
   fall back to hard 800-token split
3. Plain text: paragraph-aware hard split

Determinism: given the same bytes on disk, produces byte-identical output.
"""
from __future__ import annotations

import re
from pathlib import Path

from age_bakeoff.models import Chunk

_MAX_CHARS = 3000  # ~750 tokens for BAAI/bge-small-en-v1.5
_MIN_CHARS = 200

_MD_HEADING = re.compile(r"^#{1,6}\s+.+$", re.MULTILINE)
_PY_DEF = re.compile(r"^(def |class |async def )", re.MULTILINE)
_C_FUNC = re.compile(
    r"^(?:static\s+)?(?:[A-Za-z_][\w*\s]*)\s+\**[A-Za-z_]\w*\s*\([^;]*\)\s*\{",
    re.MULTILINE,
)
_C_STRUCT = re.compile(r"^(?:typedef\s+)?struct\s+[A-Za-z_]\w*", re.MULTILINE)


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


def chunk_text(text: str, document_id: str, doc_type: str = "prose") -> list[Chunk]:
    if doc_type == "code":
        splits = _split_plain(text)
    else:
        splits = _split_prose(text)
    return _to_chunks(document_id, splits)


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
        [m.start() for m in _C_FUNC.finditer(text)]
        + [m.start() for m in _C_STRUCT.finditer(text)]
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
        if len(buffer) + len(para) + 2 > _MAX_CHARS and buffer:
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


def _to_chunks(
    document_id: str, splits: list[str], source_path: str | None = None
) -> list[Chunk]:
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
