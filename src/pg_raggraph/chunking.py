"""Structure-aware document chunking."""

from __future__ import annotations

import hashlib
import os
import re

import tiktoken

from pg_raggraph.config import PGRGConfig

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")
_enc = tiktoken.get_encoding("cl100k_base")


def token_count(text: str) -> int:
    return len(_enc.encode(text))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def chunk_document(
    content: str,
    source_path: str | None = None,
    config: PGRGConfig | None = None,
) -> list[dict]:
    """Chunk a document into pieces respecting structure.

    Returns list of dicts with keys: content, token_count, content_hash, metadata.
    """
    if config is None:
        config = PGRGConfig()

    max_tokens = config.chunk_max_tokens
    overlap_tokens = config.chunk_overlap_tokens

    # Detect type
    is_markdown = _is_markdown(content, source_path)
    is_code = _is_code(source_path)

    if is_code:
        sections = _split_by_code_structure(content, source_path)
    elif is_markdown:
        sections = _split_by_headings(content)
    else:
        sections = [content]

    chunks = []
    for section in sections:
        section_chunks = _split_to_token_budget(section, max_tokens, overlap_tokens)
        chunks.extend(section_chunks)

    # Build output with metadata
    result = []
    for i, chunk_text in enumerate(chunks):
        if not chunk_text.strip():
            continue
        tc = token_count(chunk_text)
        result.append(
            {
                "content": chunk_text.strip(),
                "token_count": tc,
                "content_hash": content_hash(chunk_text.strip()),
                "metadata": {
                    "source_path": source_path,
                    "chunk_index": i,
                },
            }
        )
    return result


def _is_markdown(content: str, source_path: str | None) -> bool:
    if source_path and source_path.endswith(".md"):
        return True
    if content.lstrip().startswith("#"):
        return True
    return False


_CODE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java"}


def _is_code(source_path: str | None) -> bool:
    if not source_path:
        return False
    _, ext = os.path.splitext(source_path)
    return ext.lower() in _CODE_EXTENSIONS


_PY_BOUNDARY_RE = re.compile(r"^(class|def|async def)\s+\w+", re.MULTILINE)
_JS_BOUNDARY_RE = re.compile(
    r"^(export\s+)?(async\s+)?(function|class|const|let|var)\s+\w+", re.MULTILINE
)
_GO_BOUNDARY_RE = re.compile(r"^func\s+(\(\w+\s+\*?\w+\)\s+)?\w+", re.MULTILINE)
_RS_BOUNDARY_RE = re.compile(r"^(pub\s+)?(fn|struct|impl|trait|enum)\s+\w+", re.MULTILINE)


def get_git_info(file_path: str) -> dict:
    """Best-effort: get last commit + author for a file.

    Returns empty dict if not in a git repo or git is not available.
    Use this to attach git metadata to chunks during dev KB ingestion.
    """
    import subprocess

    try:
        cwd = os.path.dirname(os.path.abspath(file_path)) or "."
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H|%an|%ae|%aI|%s", "--", file_path],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}
        parts = result.stdout.strip().split("|", 4)
        if len(parts) < 5:
            return {}
        return {
            "git_commit": parts[0],
            "git_author": parts[1],
            "git_email": parts[2],
            "git_date": parts[3],
            "git_subject": parts[4],
        }
    except Exception:
        return {}


def _split_by_code_structure(content: str, source_path: str | None) -> list[str]:
    """Split source code on function/class/struct boundaries.

    Keeps the definition line with its body. Uses simple regex matching —
    good enough for most cases, not a full parser.
    """
    ext = os.path.splitext(source_path or "")[1].lower()
    if ext == ".py":
        pattern = _PY_BOUNDARY_RE
    elif ext in (".js", ".ts", ".tsx", ".jsx"):
        pattern = _JS_BOUNDARY_RE
    elif ext == ".go":
        pattern = _GO_BOUNDARY_RE
    elif ext == ".rs":
        pattern = _RS_BOUNDARY_RE
    else:
        return [content]

    # Find all boundary positions
    positions = [m.start() for m in pattern.finditer(content)]
    if not positions:
        return [content]

    # Include the preamble (imports, module docstring) as the first section
    sections = []
    if positions[0] > 0:
        sections.append(content[: positions[0]])

    # Each boundary starts a new section that runs to the next boundary
    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(content)
        sections.append(content[start:end])

    return [s for s in sections if s.strip()]


def _split_by_headings(content: str) -> list[str]:
    """Split markdown content by headings (H1-H4), keeping heading with its content."""
    # Split on heading lines
    parts = re.split(r"(?=^#{1,4}\s)", content, flags=re.MULTILINE)
    sections = [p for p in parts if p.strip()]
    return sections if sections else [content]


def _hard_split_tokens(text: str, max_tokens: int) -> list[str]:
    """Last-resort: split a single long 'sentence' by tokens.

    Uses tiktoken to encode, then splits the token stream into fixed-size
    chunks. Decoded back to text. Loses sentence boundaries but guarantees
    no chunk exceeds max_tokens.
    """
    tokens = _enc.encode(text)
    if len(tokens) <= max_tokens:
        return [text]
    result = []
    for i in range(0, len(tokens), max_tokens):
        chunk_tokens = tokens[i : i + max_tokens]
        result.append(_enc.decode(chunk_tokens))
    return result


def _split_to_token_budget(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Split text into chunks within token budget, respecting sentence boundaries.

    Falls back to hard token-split for sentences that individually exceed the budget
    (common in SEC filings, tables, unformatted data).
    """
    tc = token_count(text)
    if tc <= max_tokens:
        return [text]

    sentences = _SENTENCE_END_RE.split(text)
    chunks = []
    current = []
    current_tokens = 0

    for sentence in sentences:
        stc = token_count(sentence)

        # If a single sentence is larger than the budget, hard-split it
        if stc > max_tokens:
            # First flush current buffer
            if current:
                chunks.append(" ".join(current))
                current = []
                current_tokens = 0
            # Then hard-split the oversized sentence
            chunks.extend(_hard_split_tokens(sentence, max_tokens))
            continue

        if current_tokens + stc > max_tokens and current:
            chunks.append(" ".join(current))
            # Overlap: keep last few sentences
            overlap_text = ""
            overlap_count = 0
            for s in reversed(current):
                stc2 = token_count(s)
                if overlap_count + stc2 > overlap_tokens:
                    break
                overlap_text = s + " " + overlap_text
                overlap_count += stc2
            current = [overlap_text.strip()] if overlap_text.strip() else []
            current_tokens = overlap_count
        current.append(sentence)
        current_tokens += stc

    if current:
        chunks.append(" ".join(current))

    return chunks
