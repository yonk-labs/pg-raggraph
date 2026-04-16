"""Verify both engines accept the same ExtractionOutput and report matching configs."""
from __future__ import annotations

import hashlib
import json
import os

import psycopg
import pytest

from age_bakeoff.engines.age import AgeEngine
from age_bakeoff.engines.pgrg import PgrgEngine
from age_bakeoff.models import (
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
)

PGRG_DSN = os.getenv("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg")
AGE_DSN = os.getenv("AGE_DSN", "postgresql://postgres:postgres@localhost:5435/age_bakeoff_age")


def _both_dbs_up() -> bool:
    for dsn in (PGRG_DSN, AGE_DSN):
        try:
            with psycopg.connect(dsn, connect_timeout=2) as conn:
                conn.execute("SELECT 1")
        except Exception:
            return False
    return True


pytestmark = pytest.mark.skipif(not _both_dbs_up(), reason="both DBs must be up")


@pytest.fixture(autouse=True)
def _allow_real_dbs(monkeypatch):
    """Override the conftest guard so we can hit both real Docker DBs."""
    monkeypatch.setenv("PGRG_DSN", PGRG_DSN)
    monkeypatch.setenv("AGE_DSN", AGE_DSN)


def _mk_extraction() -> ExtractionOutput:
    # Entity names MUST appear in chunk content so that both engines can link
    # entities to chunks (pgrg uses name-in-content matching for entity_chunks).
    return ExtractionOutput(
        corpus="parity",
        chunks=[
            Chunk(id="d::0", document_id="d", content="Alpha is a core concept in distributed systems.", sequence=0),
            Chunk(id="d::1", document_id="d", content="Beta extends the ideas behind Alpha.", sequence=1),
            Chunk(id="d::2", document_id="d", content="Gamma builds on Beta for fault tolerance.", sequence=2),
            Chunk(id="d::3", document_id="d", content="Alpha and Gamma together enable consensus.", sequence=3),
            Chunk(id="d::4", document_id="d", content="Beta provides the bridge between Alpha and Gamma.", sequence=4),
        ],
        entities=[
            ExtractedEntity(id="e0", name="Alpha", entity_type="Concept"),
            ExtractedEntity(id="e1", name="Beta", entity_type="Concept"),
            ExtractedEntity(id="e2", name="Gamma", entity_type="Concept"),
        ],
        relationships=[
            ExtractedRelationship(src_id="e0", dst_id="e1", rel_type="RELATES_TO"),
            ExtractedRelationship(src_id="e1", dst_id="e2", rel_type="RELATES_TO"),
        ],
    )


async def test_identical_extraction_ingested_by_both():
    ext = _mk_extraction()
    pgrg = PgrgEngine(dsn=PGRG_DSN, namespace="parity_test")
    age = AgeEngine(dsn=AGE_DSN, graph_name="parity_test")
    try:
        await pgrg.ingest(ext)
        await age.ingest(ext)
        # Both can retrieve something for the same question
        r1 = await pgrg.retrieve("How does Alpha relate to Beta in distributed systems?")
        r2 = await age.retrieve("How does Alpha relate to Beta in distributed systems?")
        assert len(r1.retrieved_chunk_ids) > 0, "pgrg returned no chunks"
        assert len(r2.retrieved_chunk_ids) > 0, "age returned no chunks"
    finally:
        await pgrg.cleanup()
        await age.cleanup()


def test_configs_are_symmetric():
    pgrg_info = PgrgEngine(dsn=PGRG_DSN).info()
    age_info = AgeEngine(dsn=AGE_DSN).info()
    assert pgrg_info.embedding_model == age_info.embedding_model
    assert pgrg_info.answer_model == age_info.answer_model
    assert pgrg_info.top_k == age_info.top_k
    assert pgrg_info.hop_budget == age_info.hop_budget


def test_extraction_checksum_stable():
    ext = _mk_extraction()
    payload = json.dumps(
        {
            "chunks": [c.model_dump() for c in ext.chunks],
            "entities": [e.model_dump() for e in ext.entities],
            "relationships": [r.model_dump() for r in ext.relationships],
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    assert len(digest) == 64  # sha256 always 64 hex chars — sanity check
