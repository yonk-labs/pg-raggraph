"""Structure-aware document chunking."""

from __future__ import annotations

import hashlib
import logging
import os
import re

import tiktoken

from pg_raggraph.config import PGRGConfig

_logger = logging.getLogger("pg_raggraph.chunking")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")
_enc = tiktoken.get_encoding("cl100k_base")

# Hierarchy strategy constants — ported byte-for-byte from age-bakeoff
# (benchmarks/age-bakeoff/src/age_bakeoff/chunker.py, which itself lineages to
# chunkshop's HierarchyChunker at github.com/yonk-labs/chunkshop) so the +8
# SCOTUS lift reproduces. Char-based on purpose; no token-budget split.
# See docs/chunkshop-integration.md § port policy when updating.
_HIER_MAX_CHARS = 3000
_HIER_MIN_SECTION_CHARS = 100
_HIER_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)$", re.MULTILINE)


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

    `config.chunk_strategy` accepts these values:

    - ``"auto"`` (default) — detect markdown / code / text by extension + content,
      pick the best built-in splitter.
    - ``"hierarchy"`` — heading-prefixed, ported from chunkshop's HierarchyChunker
      (lineage annotation in this file). Built-in, no dependency.
    - ``"chunkshop:<chunker_name>"`` — delegate to chunkshop directly. Optional
      dependency: install with ``pip install pg-raggraph[chunkshop]``. Supported
      chunker names: ``hierarchy``, ``sentence_aware``, ``semantic``,
      ``fixed_overlap``, ``neighbor_expand``, ``summary_embed``,
      ``hierarchical_summary``. See docs/cookbook/chunkshop-integration.md.
    """
    if config is None:
        config = PGRGConfig()

    max_tokens = config.chunk_max_tokens
    overlap_tokens = config.chunk_overlap_tokens

    # chunkshop pass-through strategies. Lazy import so users without the
    # optional dep don't pay; gracefully tell them how to install when missing.
    if config.chunk_strategy.startswith("chunkshop:"):
        return _chunk_via_chunkshop(content, source_path, config)

    # Hierarchy strategy: heading-prefixed, token-capped. Each section body is
    # sub-split through _split_to_token_budget when it exceeds chunk_max_tokens;
    # each sub-chunk re-prefixes the heading into embedded_content so the
    # embedder always sees `heading + body` as one unit, while content stays
    # body-only for clean audit/grep.
    if config.chunk_strategy == "hierarchy":
        title = _derive_title(content, source_path)
        sections = _split_hierarchy(content, title=title)

        result: list[dict] = []
        for heading, body in sections:
            if token_count(body) <= max_tokens:
                sub_bodies = [body]
            else:
                sub_bodies = _split_to_token_budget(body, max_tokens, overlap_tokens)
            for part_idx, sub_body in enumerate(sub_bodies):
                body_text = sub_body.strip()
                if not body_text:
                    continue
                embedded = f"{heading}\n\n{body_text}" if heading else body_text
                result.append(
                    {
                        "content": body_text,
                        "embedded_content": embedded,
                        "token_count": token_count(embedded),
                        "content_hash": content_hash(body_text),
                        "metadata": {
                            "source_path": source_path,
                            "chunk_index": len(result),
                            "heading": heading,
                            "section_part": part_idx,
                        },
                    }
                )
        return result

    # Auto strategy: detect type, split by structure, then by token budget.
    # embedded_content == content on this path (no heading rewrite, no neighbor
    # expansion) — the dual-field primitive is ready for future neighbor_expand
    # / summary-embed integrations without touching this branch.
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

    result = []
    for i, chunk_text in enumerate(chunks):
        stripped = chunk_text.strip()
        if not stripped:
            continue
        result.append(
            {
                "content": stripped,
                "embedded_content": stripped,
                "token_count": token_count(stripped),
                "content_hash": content_hash(stripped),
                "metadata": {
                    "source_path": source_path,
                    "chunk_index": i,
                },
            }
        )
    return result


def _chunk_via_chunkshop(
    content: str,
    source_path: str | None,
    config: PGRGConfig,
) -> list[dict]:
    """Delegate chunking to chunkshop (optional dep).

    chunkshop is a sibling library on PyPI / crates.io. pg-raggraph treats
    it as the recommended chunker when available; the strategies in
    chunkshop's registry (hierarchy, semantic, sentence_aware, etc.) are
    typically richer than our built-in chunker and have been tuned across
    multiple corpora.

    Install: ``pip install pg-raggraph[chunkshop]`` (or pin chunkshop
    yourself for the version of your choice).
    """
    try:
        from chunkshop.chunkers import load_chunker
        from chunkshop.config import (
            FixedOverlapChunker as FixedCfg,
        )
        from chunkshop.config import (
            HierarchyChunker as HierCfg,
        )
        from chunkshop.config import (
            NeighborExpandChunker as NeighborCfg,
        )
        from chunkshop.config import (
            SemanticChunker as SemanticCfg,
        )
        from chunkshop.config import (
            SentenceAwareChunker as SentCfg,
        )
        from chunkshop.sources.base import Document
    except ImportError as e:
        raise ImportError(
            "chunk_strategy='chunkshop:*' requires the chunkshop package. "
            "Install with: pip install 'pg-raggraph[chunkshop]'  "
            "(or pin chunkshop directly: pip install chunkshop). "
            f"Original import error: {e}"
        ) from e

    name = config.chunk_strategy.split(":", 1)[1]
    title = _derive_title(content, source_path)
    doc = Document(
        id=source_path or "doc",
        content=content,
        title=title or None,
        metadata={"source_path": source_path} if source_path else None,
    )

    # Each chunker takes its own config. Defaults chosen to track our existing
    # chunk_max_tokens budget (1 token ≈ 4 chars for English).
    max_chars = max(config.chunk_max_tokens * 4, 800)

    # chunkshop's pydantic Cfgs all require a `type` discriminator. Build the
    # config here so callers don't need to know the chunkshop schema, then let
    # chunkshop's own `load_chunker` registry instantiate the chunker. Routing
    # through the registry keeps us forward-compatible with chunkshop's
    # constructor changes (e.g. nested chunkers like neighbor_expand now take a
    # separately-built `base` chunker as a positional arg in 0.5.0).
    chunker_cfg_map = {
        "hierarchy": HierCfg(type="hierarchy", max_chars=max_chars),
        "sentence_aware": SentCfg(type="sentence_aware", max_chars=max_chars),
        "semantic": SemanticCfg(type="semantic", max_chunk_chars=max_chars),
        "fixed_overlap": FixedCfg(type="fixed_overlap"),
        "neighbor_expand": NeighborCfg(
            type="neighbor_expand",
            base=HierCfg(type="hierarchy", max_chars=max_chars),
        ),
    }

    if name not in chunker_cfg_map:
        raise ValueError(
            f"Unknown chunkshop strategy 'chunkshop:{name}'. "
            f"Supported: {sorted(chunker_cfg_map.keys())}. "
            "For summary_embed and hierarchical_summary (which require an "
            "embedder + summarizer), use chunkshop's own pipeline directly "
            "and feed the resulting chunks to rag.ingest_records()."
        )

    chunker = load_chunker(chunker_cfg_map[name])
    cs_chunks = chunker.chunk(doc)

    result: list[dict] = []
    for cs in cs_chunks:
        body = (cs.original_content or "").strip()
        if not body:
            continue
        embedded = (cs.embedded_content or body).strip()
        meta = dict(cs.metadata or {})
        # Preserve our standard metadata keys alongside chunkshop's.
        meta.setdefault("source_path", source_path)
        meta.setdefault("chunk_index", len(result))
        meta.setdefault("chunkshop_strategy", name)
        meta.setdefault("chunkshop_seq_num", cs.seq_num)
        result.append(
            {
                "content": body,
                "embedded_content": embedded,
                "token_count": token_count(embedded),
                "content_hash": content_hash(body),
                "metadata": meta,
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
    except Exception as e:
        _logger.debug("git metadata lookup failed for %s: %s", file_path, e)
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


def _derive_title(content: str, source_path: str | None) -> str:
    """Pick a title for hierarchy-strategy title-prefix fallback.

    First markdown H1 if present; else the source_path basename without
    extension; else empty (then ``_split_hierarchy`` emits unprefixed chunks).
    """
    for m in _HIER_HEADING_RE.finditer(content):
        if m.group(1) == "#":
            return m.group(2).strip()
    if source_path:
        return os.path.splitext(os.path.basename(source_path))[0]
    return ""


def _split_hierarchy(text: str, title: str = "") -> list[tuple[str, str]]:
    """Heading-aware section split. Returns list of (heading, body) pairs.

    Body text has NO heading prefix — the caller (``chunk_document``) is
    responsible for prepending ``{heading}\\n\\n`` when producing final chunk
    content, and for re-prefixing each sub-chunk when a section exceeds the
    token budget.

    - One pair per markdown heading (H1-H6); body is the section text beneath.
    - Pre-first-heading prefix becomes its own pair with ``title`` as heading.
    - No headings: single pair = ``(title, body)``; heading is "" if title is
      empty. This is the path that carried the +8 SCOTUS lift.
    - Sections shorter than ``_HIER_MIN_SECTION_CHARS`` are dropped in
      multi-heading docs, matching chunkshop. Whole-doc case preserves short
      bodies (mirrors the heading-less single-chunk fall-through).
    """
    headings = list(_HIER_HEADING_RE.finditer(text))
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
