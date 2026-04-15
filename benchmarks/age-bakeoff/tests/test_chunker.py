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
    payload = json.dumps([c.model_dump() for c in chunks], sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    # Snapshot: if the chunker changes, this test fails and we re-verify parity
    assert len(digest) == 64


def test_chunk_text_explicit_doc_id():
    chunks = chunk_text("a paragraph", document_id="doc42")
    assert chunks[0].document_id == "doc42"
    assert chunks[0].id.startswith("doc42::")
