from __future__ import annotations

import hashlib
import json

import pytest

from age_bakeoff.chunker import chunk_file, chunk_text
from age_bakeoff.models import Chunk


def test_prose_chunker_splits_on_headings(fixtures_dir):
    chunks = chunk_file(fixtures_dir / "tiny_doc.md")
    assert len(chunks) >= 2
    assert all(isinstance(c, Chunk) for c in chunks)
    assert chunks[0].sequence == 0
    assert chunks[1].sequence == 1
    # Section A and Section B produce distinct chunks
    contents = [c.content for c in chunks]
    assert any("Section A" in c for c in contents)
    assert any("Section B" in c for c in contents)


def test_code_chunker_splits_on_function_boundaries(fixtures_dir):
    chunks = chunk_file(fixtures_dir / "tiny_doc.py")
    contents = "\n---\n".join(c.content for c in chunks)
    assert "def alpha" in contents
    assert "def beta" in contents
    assert "class Gamma" in contents


def test_chunker_is_deterministic(fixtures_dir):
    a = chunk_file(fixtures_dir / "tiny_doc.md")
    b = chunk_file(fixtures_dir / "tiny_doc.md")
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]


def test_chunker_produces_stable_hashes(fixtures_dir):
    chunks = chunk_file(fixtures_dir / "tiny_doc.md")
    # Strip source_path from metadata — it contains an absolute filesystem path
    # that varies by checkout location. We want the hash to pin content, not
    # machine state.
    content_only = [
        {**c.model_dump(), "metadata": {}} for c in chunks
    ]
    payload = json.dumps(content_only, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    # Pinned snapshot — any chunker change that touches tiny_doc.md output
    # must re-verify parity and update this hash deliberately.
    assert digest == "ee548f550452741b5b2d7fd81a07764078575db03b431fc02c77c4135bf86729"


def test_chunk_text_explicit_doc_id():
    chunks = chunk_text("a paragraph", document_id="doc42")
    assert chunks[0].document_id == "doc42"
    assert chunks[0].id.startswith("doc42::")


def test_plain_oversized_paragraph_is_hard_split():
    """Regression: _split_plain must hard-split paragraphs larger than _MAX_CHARS."""
    big_para = "word " * 800  # 4000 chars, exceeds _MAX_CHARS=3000
    chunks = chunk_text(big_para, document_id="oversized")
    assert len(chunks) >= 2
    assert all(len(c.content) <= 3000 for c in chunks)


def test_plain_oversized_para_between_small_paras():
    small = "tiny."
    huge = "x" * 5000
    text = f"{small}\n\n{huge}\n\n{small}"
    chunks = chunk_text(text, document_id="mixed")
    assert all(len(c.content) <= 3000 for c in chunks)
    combined = " ".join(c.content for c in chunks)
    assert combined.count("x") == 5000
    assert combined.count("tiny.") == 2


def test_hierarchy_prefixes_heading():
    """Each markdown heading becomes its own chunk with the heading as prefix."""
    # Sections must be >= 100 chars (chunkshop min_section_chars default) so
    # padding is real text, not noise. The hierarchy chunker drops shorter
    # sections by design — this matches the factorial-detour configuration.
    body_a = "Alpha content. " * 10  # ~150 chars
    body_b = "Bravo content. " * 10
    text = f"## Section A\n\n{body_a}\n\n## Section B\n\n{body_b}"
    chunks = chunk_text(
        text, document_id="doc1", strategy="hierarchy", title="My Title"
    )
    assert len(chunks) == 2
    assert chunks[0].content.startswith("Section A\n\n")
    assert "Alpha content." in chunks[0].content
    assert chunks[1].content.startswith("Section B\n\n")
    assert "Bravo content." in chunks[1].content


def test_hierarchy_title_fallback_when_no_headings():
    """Scotus-shape docs (no headings) get title prefix on a single chunk.

    This is the path that drove factorial C/nomic = 18/30 — every scotus chunk
    starts with the case name because 0/772 docs contain markdown headings.
    """
    body = "Plain prose about a SCOTUS case. " * 20
    chunks = chunk_text(
        body, document_id="d1", strategy="hierarchy", title="Air v. Devries"
    )
    assert len(chunks) == 1
    assert chunks[0].content.startswith("Air v. Devries\n\n")


def test_hierarchy_no_title_no_heading_returns_body_only():
    body = "Plain prose without any prefix. " * 20
    chunks = chunk_text(body, document_id="d1", strategy="hierarchy")
    assert len(chunks) == 1
    assert not chunks[0].content.startswith("\n")
    assert chunks[0].content.startswith("Plain prose")


def test_hierarchy_drops_short_sections():
    """Sections under 100 chars get dropped (matches chunkshop)."""
    text = "## Short\n\nhi.\n\n## Longer\n\n" + ("longer body. " * 20)
    chunks = chunk_text(text, document_id="d1", strategy="hierarchy")
    assert len(chunks) == 1
    assert chunks[0].content.startswith("Longer\n\n")


def test_sentence_aware_default_is_unchanged(fixtures_dir):
    """Default strategy must produce byte-identical chunks to the prior baseline.

    If this test fails, the pinned hash in test_chunker_produces_stable_hashes
    will too — but this gives a sharper failure message: the default changed.
    """
    explicit = chunk_text(
        (fixtures_dir / "tiny_doc.md").read_text(), document_id="tiny_doc.md"
    )
    default = chunk_text(
        (fixtures_dir / "tiny_doc.md").read_text(),
        document_id="tiny_doc.md",
        strategy="sentence_aware",
    )
    assert [c.model_dump() for c in explicit] == [
        c.model_dump() for c in default
    ]


def test_chunk_text_rejects_unknown_strategy():
    """Unknown strategy values should surface a clear error, not silently
    fall through to the default."""
    with pytest.raises((ValueError, TypeError)):
        # Typing prevents this in static callers, but runtime callers could
        # still pass env-var-derived strings. Route the error via loaders'
        # env parser; here we just confirm the chunker doesn't silently
        # accept it.
        chunk_text(
            "anything", document_id="d", strategy="bogus"  # type: ignore[arg-type]
        )  # noqa: S101
