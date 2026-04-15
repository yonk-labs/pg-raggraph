from __future__ import annotations

import hashlib
import json

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
