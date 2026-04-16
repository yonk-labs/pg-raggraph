"""Postgres source extractor — mocked OpenAI, tests aggregation and caching."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from age_bakeoff.extraction.pg_src import extract_pg_src
from age_bakeoff.models import Chunk, ExtractionOutput


def _fake_client(response_json: str):
    msg = MagicMock()
    msg.message = MagicMock()
    msg.message.content = response_json
    completion = MagicMock()
    completion.choices = [msg]
    completion.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = MagicMock(return_value=completion)
    return client


def test_extract_deduplicates_entities(tmp_path):
    chunks = [
        Chunk(id="a::0", document_id="a", content="void ExecSeqScan() { }", sequence=0),
        Chunk(id="a::1", document_id="a", content="struct Plan { };", sequence=1),
    ]
    fake = _fake_client(json.dumps({
        "entities": [
            {"name": "ExecSeqScan", "entity_type": "Function", "description": "Runs seq scan"}
        ],
        "relationships": [],
    }))
    out = extract_pg_src(chunks, client=fake, cache_path=tmp_path / "pg.json")
    assert isinstance(out, ExtractionOutput)
    assert out.corpus == "pg_src"
    names = [e.name for e in out.entities]
    assert names.count("ExecSeqScan") == 1


def test_extract_caches_to_disk(tmp_path):
    cache = tmp_path / "cached.json"
    payload = ExtractionOutput(corpus="pg_src", chunks=[], entities=[], relationships=[])
    cache.write_text(payload.model_dump_json(indent=2))
    sentinel = MagicMock(side_effect=AssertionError("should not call LLM"))
    out = extract_pg_src([], client=sentinel, cache_path=cache)
    assert out.corpus == "pg_src"


def test_extract_drops_dangling_relationships(tmp_path):
    fake = _fake_client(json.dumps({
        "entities": [
            {"name": "foo", "entity_type": "Function", "description": "does foo"}
        ],
        "relationships": [
            {"src": "foo", "dst": "bar_missing", "rel_type": "CALLS", "description": "x"}
        ],
    }))
    chunks = [Chunk(id="x::0", document_id="x", content="code here", sequence=0)]
    out = extract_pg_src(chunks, client=fake, cache_path=tmp_path / "pg.json")
    assert len(out.relationships) == 0  # bar_missing not in entities -> dropped
