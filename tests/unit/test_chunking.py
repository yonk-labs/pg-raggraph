"""Tests for chunking module."""

import pytest

from pg_raggraph.chunking import (
    _derive_title,
    _split_by_code_structure,
    _split_hierarchy,
    chunk_document,
    content_hash,
    token_count,
)
from pg_raggraph.config import PGRGConfig


def test_token_count():
    assert token_count("hello world") > 0
    assert token_count("") == 0


def test_content_hash_deterministic():
    h1 = content_hash("hello")
    h2 = content_hash("hello")
    h3 = content_hash("world")
    assert h1 == h2
    assert h1 != h3


def test_markdown_heading_split():
    content = """# Title

Introduction paragraph.

## Section One

Content of section one with multiple sentences. It has details.

## Section Two

Content of section two.
"""
    config = PGRGConfig(chunk_max_tokens=500)
    chunks = chunk_document(content, source_path="test.md", config=config)
    assert len(chunks) >= 2  # Should split on headings
    # First chunk should contain title/intro
    assert "Title" in chunks[0]["content"] or "Introduction" in chunks[0]["content"]


def test_large_section_splits_further():
    """A single section that exceeds token budget should be sub-split."""
    long_text = "# Big Section\n\n" + "This is a sentence. " * 200
    config = PGRGConfig(chunk_max_tokens=100)
    chunks = chunk_document(long_text, source_path="big.md", config=config)
    assert len(chunks) > 1
    for chunk in chunks:
        # Each chunk should be within budget (with some tolerance)
        assert chunk["token_count"] <= 150  # Allow some overflow at sentence boundaries


def test_plain_text_chunking():
    """Plain text (no headings) should still chunk properly."""
    text = "This is a plain text document. " * 100
    config = PGRGConfig(chunk_max_tokens=50)
    chunks = chunk_document(text, source_path="readme.txt", config=config)
    assert len(chunks) > 1


def test_empty_content():
    chunks = chunk_document("", source_path="empty.md")
    assert chunks == []


def test_single_line():
    chunks = chunk_document("Just one line.", source_path="one.txt")
    assert len(chunks) == 1
    assert chunks[0]["content"] == "Just one line."


def test_chunk_has_required_fields():
    chunks = chunk_document("# Hello\n\nWorld.", source_path="test.md")
    assert len(chunks) >= 1
    chunk = chunks[0]
    assert "content" in chunk
    assert "token_count" in chunk
    assert "content_hash" in chunk
    assert "metadata" in chunk
    assert chunk["token_count"] > 0
    assert len(chunk["content_hash"]) == 64  # SHA-256 hex


def test_python_code_structure_split():
    """Python files are split on def/class boundaries."""
    code = '''"""Module docstring."""

import os
import sys


def foo():
    """Foo function."""
    return 1


def bar(x, y):
    return x + y


class Baz:
    def method1(self):
        pass

    def method2(self):
        return "hi"
'''
    sections = _split_by_code_structure(code, "mymodule.py")
    # Preamble + 3 top-level defs (foo, bar, Baz)
    assert len(sections) >= 4
    # First section should be the preamble (imports + docstring)
    assert "import os" in sections[0]
    # Second should be foo
    assert "def foo" in sections[1]
    # bar should be its own section
    assert any("def bar" in s for s in sections)
    # Baz class boundary
    assert any("class Baz" in s for s in sections)


def test_javascript_code_structure_split():
    """JS/TS files split on function/class/const boundaries."""
    code = """\
import { foo } from 'bar';

export function greet(name) {
    return `Hello, ${name}`;
}

export class User {
    constructor(name) {
        this.name = name;
    }
}

const helper = () => 42;
"""
    sections = _split_by_code_structure(code, "app.ts")
    assert len(sections) >= 3
    assert any("function greet" in s for s in sections)
    assert any("class User" in s for s in sections)


def test_non_code_file_single_section():
    """Non-code files fall through to single-section output."""
    sections = _split_by_code_structure("plain text", "readme.txt")
    assert sections == ["plain text"]


def test_code_chunking_integrates_with_chunk_document():
    """The public chunk_document API picks up code-aware chunking."""
    code = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
    config = PGRGConfig(chunk_max_tokens=500)
    chunks = chunk_document(code, source_path="mod.py", config=config)
    # Should have separate chunks for foo and bar
    texts = [c["content"] for c in chunks]
    assert any("def foo" in t for t in texts)
    assert any("def bar" in t for t in texts)


# --- chunk_strategy=hierarchy ---


def test_default_strategy_is_not_hierarchy():
    """Default 'auto' strategy does not prefix chunks with heading/title."""
    content = "# Miranda v. Arizona\n\n" + ("A" * 300)
    chunks = chunk_document(content, source_path="miranda.md", config=PGRGConfig())
    # Default path keeps the heading inline via _split_by_headings, but does
    # NOT rewrite bodies as `{heading}\n\n{body}` — the second chunk would
    # not start with the heading text as a standalone prefix.
    assert chunks[0]["content"].startswith("# Miranda v. Arizona")


def test_hierarchy_strategy_prefixes_heading():
    """With chunk_strategy=hierarchy each section body is prefixed by its heading
    in embedded_content (content stays body-only)."""
    content = (
        "# Miranda v. Arizona\n\n"
        + ("Intro paragraph. " * 20)
        + "\n\n## Holding\n\n"
        + ("Holding body. " * 20)
        + "\n\n## Reasoning\n\n"
        + ("Reasoning body. " * 20)
    )
    cfg = PGRGConfig(chunk_strategy="hierarchy")
    chunks = chunk_document(content, source_path="miranda.md", config=cfg)
    embedded = [c["embedded_content"] for c in chunks]
    assert any(t.startswith("Miranda v. Arizona\n\n") for t in embedded)
    assert any(t.startswith("Holding\n\n") for t in embedded)
    assert any(t.startswith("Reasoning\n\n") for t in embedded)


def test_hierarchy_fallback_prefixes_title_when_no_headings():
    """No headings + long body => single chunk with title prefix in embedded_content."""
    body = "Sentence one. " * 50
    cfg = PGRGConfig(chunk_strategy="hierarchy")
    chunks = chunk_document(body, source_path="project-update-2026.md", config=cfg)
    assert len(chunks) == 1
    assert chunks[0]["embedded_content"].startswith("project-update-2026\n\n")


def test_hierarchy_whole_doc_preserves_short_bodies():
    """Short heading-less docs still emit a single chunk (MIN_CHARS not applied)."""
    cfg = PGRGConfig(chunk_strategy="hierarchy")
    chunks = chunk_document("tiny body.", source_path="t.md", config=cfg)
    assert len(chunks) == 1
    assert chunks[0]["content"] == "tiny body."
    assert chunks[0]["embedded_content"] == "t\n\ntiny body."


def test_hierarchy_drops_short_sections_in_long_docs():
    """In a long doc, sections below MIN_CHARS (100) are dropped per chunkshop."""
    short = "x" * 20  # below MIN_CHARS
    long_ = "y" * 200  # above MIN_CHARS
    content = f"# A\n\n{short}\n\n## B\n\n{long_}\n"
    sections = _split_hierarchy(content, title="doc")
    # The pre-first-heading body is empty (0 chars), A's body is short (20),
    # B's body is long (200). Only B should survive.
    # _split_hierarchy returns (heading, body) tuples; body has no prefix.
    assert len(sections) == 1
    heading, body = sections[0]
    assert heading == "B"
    assert body.startswith("y")


def test_derive_title_prefers_h1_over_filename():
    content = "# Real Title\n\nBody.\n## Sub"
    assert _derive_title(content, "ignored-name.md") == "Real Title"


def test_derive_title_falls_back_to_basename():
    assert _derive_title("no headings here", "/path/to/weekly-sync.md") == "weekly-sync"


def test_derive_title_ignores_subheadings():
    """Only H1 counts as title; H2/H3 are section headings."""
    content = "## Subsection\n\nbody"
    assert _derive_title(content, "fallback.md") == "fallback"


def test_hierarchy_empty_content():
    """Empty doc emits no chunks regardless of strategy."""
    cfg = PGRGConfig(chunk_strategy="hierarchy")
    assert chunk_document("", source_path="empty.md", config=cfg) == []


def test_hierarchy_splits_oversized_sections():
    """An oversized section body is hard-split into multiple chunks.

    Each sub-chunk must:
    - respect ``chunk_max_tokens`` (with sentence-boundary tolerance)
    - retain the same heading prefix so the embedder sees ``heading + body``
      as one unit on every sub-chunk
    """
    # ~2000 tokens of body, well over the 512 budget
    big_body = "This is a sentence about the topic. " * 400
    content = f"# Oncology overview\n\n{big_body}"
    cfg = PGRGConfig(chunk_strategy="hierarchy", chunk_max_tokens=512)
    chunks = chunk_document(content, source_path="med.md", config=cfg)
    # Oversized section should produce multiple sub-chunks.
    assert len(chunks) > 1
    # Every sub-chunk respects the token budget (allow small sentence-boundary tolerance).
    for c in chunks:
        assert c["token_count"] <= 600, f"sub-chunk exceeds budget: {c['token_count']} tokens"
    # Every sub-chunk is prefixed by the heading so the embedder sees heading+body.
    for c in chunks:
        assert c["embedded_content"].startswith("Oncology overview\n\n"), (
            f"sub-chunk missing heading prefix: {c['embedded_content'][:60]!r}"
        )


def test_hierarchy_sub_chunks_carry_metadata():
    """Each hierarchy sub-chunk carries metadata.heading + metadata.section_part."""
    big_body = "This is a sentence about the topic. " * 400
    content = f"# Oncology overview\n\n{big_body}"
    cfg = PGRGConfig(chunk_strategy="hierarchy", chunk_max_tokens=512)
    chunks = chunk_document(content, source_path="med.md", config=cfg)
    assert len(chunks) > 1
    # heading preserved on every sub-chunk
    for c in chunks:
        assert c["metadata"].get("heading") == "Oncology overview"
    # section_part is 0-indexed and monotonically increasing
    parts = [c["metadata"].get("section_part") for c in chunks]
    assert parts == list(range(len(chunks)))


def test_hierarchy_normal_section_has_section_part_zero():
    """A single-chunk section gets section_part=0 and its heading in metadata."""
    content = (
        "# Miranda v. Arizona\n\n"
        + ("Intro paragraph. " * 20)
        + "\n\n## Holding\n\n"
        + ("Holding body. " * 20)
    )
    cfg = PGRGConfig(chunk_strategy="hierarchy", chunk_max_tokens=512)
    chunks = chunk_document(content, source_path="miranda.md", config=cfg)
    # Find the "Holding" chunk (body-only content, heading is only in embedded_content)
    holding = next(c for c in chunks if c["metadata"].get("heading") == "Holding")
    assert holding["metadata"].get("section_part") == 0


# --- dual content field (content vs embedded_content) ---


def test_chunk_has_embedded_content_field():
    """Every chunk dict carries both content (raw body) and embedded_content."""
    chunks = chunk_document("# Hello\n\nWorld.", source_path="test.md")
    assert len(chunks) >= 1
    for c in chunks:
        assert "content" in c
        assert "embedded_content" in c


def test_auto_strategy_content_equals_embedded_content():
    """Non-hierarchy strategies do not transform embedded_content."""
    content = "Just some plain text that fits one chunk."
    chunks = chunk_document(content, source_path="plain.txt", config=PGRGConfig())
    for c in chunks:
        assert c["content"] == c["embedded_content"]


def test_hierarchy_content_is_body_only():
    """Hierarchy strategy: content is raw body (no heading), embedded_content prepends heading."""
    content = "# Oncology overview\n\n" + ("A clinical paragraph. " * 20)
    cfg = PGRGConfig(chunk_strategy="hierarchy", chunk_max_tokens=512)
    chunks = chunk_document(content, source_path="med.md", config=cfg)
    # Body-only content lets audit/grep find the clinical text without heading noise;
    # embedded_content is what the embedder and FTS see.
    for c in chunks:
        assert not c["content"].startswith("Oncology overview"), (
            f"content should be body only, got: {c['content'][:80]!r}"
        )
        assert c["embedded_content"].startswith("Oncology overview\n\n"), (
            f"embedded_content should carry heading prefix, got: {c['embedded_content'][:80]!r}"
        )


def test_hierarchy_oversized_section_each_sub_chunk_has_dual_content():
    """Oversized section: each sub-chunk's content=sub-body, embedded_content=heading+sub-body."""
    big_body = "This is a sentence about the topic. " * 400
    content = f"# Oncology overview\n\n{big_body}"
    cfg = PGRGConfig(chunk_strategy="hierarchy", chunk_max_tokens=512)
    chunks = chunk_document(content, source_path="med.md", config=cfg)
    assert len(chunks) > 1
    for c in chunks:
        assert not c["content"].startswith("Oncology overview")
        assert c["embedded_content"].startswith("Oncology overview\n\n")
        # embedded_content must equal heading + content for each sub-chunk
        assert c["embedded_content"] == f"Oncology overview\n\n{c['content']}"


# --- chunkshop delegation (optional dep) ------------------------------------
# These exercise the chunkshop:* pass-through. They are skipped when chunkshop
# is not installed, but when it is they guard against chunkshop API drift (e.g.
# the 0.5.0 NeighborExpandChunker constructor change that required routing
# construction through chunkshop.chunkers.load_chunker).

chunkshop = pytest.importorskip("chunkshop")
chunkshop_config = pytest.importorskip("chunkshop.config")

_CHUNKSHOP_STRATEGIES = [
    "chunkshop:hierarchy",
    "chunkshop:sentence_aware",
    "chunkshop:semantic",
    "chunkshop:fixed_overlap",
    "chunkshop:neighbor_expand",
]
_CHUNKSHOP_CODE_STRATEGIES = [
    pytest.param(
        "chunkshop:code_aware",
        marks=pytest.mark.skipif(
            not hasattr(chunkshop_config, "CodeAwareChunker"),
            reason="chunkshop build does not expose CodeAwareChunker",
        ),
    ),
    pytest.param(
        "chunkshop:symbol_aware",
        marks=pytest.mark.skipif(
            not hasattr(chunkshop_config, "SymbolAwareChunker"),
            reason="chunkshop build does not expose SymbolAwareChunker",
        ),
    ),
]


@pytest.mark.parametrize("strategy", _CHUNKSHOP_STRATEGIES)
def test_chunkshop_delegation_emits_chunks(strategy):
    """Every supported chunkshop:* strategy must produce non-empty chunks."""
    body = "This is a sentence that repeats to build up length. " * 30
    content = f"# Title\n\n{body}\n\n## Section A\n\n{body}\n\n## Section B\n\n{body}"
    cfg = PGRGConfig(chunk_strategy=strategy, chunk_max_tokens=512, chunk_overlap_tokens=50)
    chunks = chunk_document(content, source_path="doc.md", config=cfg)
    assert chunks, f"{strategy} produced no chunks"
    for c in chunks:
        assert c["content"].strip()
        assert c["embedded_content"].strip()
        assert c["token_count"] > 0
        assert c["metadata"]["chunkshop_strategy"] == strategy.split(":", 1)[1]


@pytest.mark.parametrize("strategy", _CHUNKSHOP_CODE_STRATEGIES)
def test_chunkshop_code_delegation_preserves_symbol_metadata(strategy):
    """Chunkshop 0.6 code chunkers should carry symbol metadata through."""
    code = '''"""Small module."""

import os


def alpha(value):
    return os.fspath(value)


class Beta:
    def gamma(self):
        return alpha("x")
'''
    cfg = PGRGConfig(chunk_strategy=strategy, chunk_max_tokens=512, chunk_overlap_tokens=50)
    chunks = chunk_document(code, source_path="pkg/example.py", config=cfg)
    assert chunks, f"{strategy} produced no chunks"
    assert all(c["metadata"]["chunkshop_strategy"] == strategy.split(":", 1)[1] for c in chunks)

    if strategy == "chunkshop:symbol_aware":
        symbol_chunks = [c for c in chunks if c["metadata"].get("strategy") == "symbol_aware"]
        assert symbol_chunks
        assert any(c["metadata"].get("symbol_name") == "alpha" for c in symbol_chunks)
        assert all(c["metadata"].get("fqn") for c in symbol_chunks)
        assert all(c["metadata"].get("node_id") for c in symbol_chunks)


def test_chunkshop_unknown_strategy_raises():
    cfg = PGRGConfig(chunk_strategy="chunkshop:does_not_exist")
    content = "# T\n\nbody text here that is long enough." * 5
    with pytest.raises(ValueError, match="Unknown chunkshop strategy"):
        chunk_document(content, source_path="d.md", config=cfg)
