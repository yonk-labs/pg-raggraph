"""Tests for chunking module."""

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
    """With chunk_strategy=hierarchy each section body is prefixed by its heading."""
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
    texts = [c["content"] for c in chunks]
    assert any(t.startswith("Miranda v. Arizona\n\n") for t in texts)
    assert any(t.startswith("Holding\n\n") for t in texts)
    assert any(t.startswith("Reasoning\n\n") for t in texts)


def test_hierarchy_fallback_prefixes_title_when_no_headings():
    """No headings + long body => single chunk prefixed by derived title."""
    body = "Sentence one. " * 50
    cfg = PGRGConfig(chunk_strategy="hierarchy")
    chunks = chunk_document(body, source_path="project-update-2026.md", config=cfg)
    assert len(chunks) == 1
    assert chunks[0]["content"].startswith("project-update-2026\n\n")


def test_hierarchy_whole_doc_preserves_short_bodies():
    """Short heading-less docs still emit a single chunk (MIN_CHARS not applied)."""
    cfg = PGRGConfig(chunk_strategy="hierarchy")
    chunks = chunk_document("tiny body.", source_path="t.md", config=cfg)
    assert len(chunks) == 1
    assert chunks[0]["content"] == "t\n\ntiny body."


def test_hierarchy_drops_short_sections_in_long_docs():
    """In a long doc, sections below MIN_CHARS (100) are dropped per chunkshop."""
    short = "x" * 20  # below MIN_CHARS
    long_ = "y" * 200  # above MIN_CHARS
    content = f"# A\n\n{short}\n\n## B\n\n{long_}\n"
    sections = _split_hierarchy(content, title="doc")
    # The pre-first-heading body is empty (0 chars), A's body is short (20),
    # B's body is long (200). Only B should survive.
    assert len(sections) == 1
    assert sections[0].startswith("B\n\n")


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


def test_hierarchy_skips_token_budget_split():
    """Hierarchy does not hard-split oversized sections — they go through as-is."""
    big_body = "word " * 2000  # ~2000 tokens, well over default 512 budget
    content = f"# Title\n\n{big_body}"
    cfg = PGRGConfig(chunk_strategy="hierarchy", chunk_max_tokens=512)
    chunks = chunk_document(content, source_path="big.md", config=cfg)
    # One chunk, because hierarchy does not enforce token budget.
    assert len(chunks) == 1
    assert chunks[0]["token_count"] > 512
