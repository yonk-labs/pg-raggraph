"""pg-raggraph engine adapter integration test. Requires Docker DB."""
from __future__ import annotations

import psycopg
import pytest

from age_bakeoff.engines.pgrg import PgrgEngine
from age_bakeoff.models import Chunk, ExtractedEntity, ExtractedRelationship, ExtractionOutput

DSN = "postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg"


def _db_available() -> bool:
    try:
        with psycopg.connect(DSN, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="pg-raggraph DB not reachable")


@pytest.fixture(autouse=True)
def _allow_real_db(monkeypatch):
    """Override the conftest guard so we can hit the real Docker DB."""
    monkeypatch.setenv("PGRG_DSN", DSN)


@pytest.fixture
def tiny_extraction():
    return ExtractionOutput(
        corpus="test",
        chunks=[
            Chunk(id="d1::0", document_id="d1", content="Alice works on Ingest.", sequence=0),
            Chunk(id="d1::1", document_id="d1", content="Ingest depends on Kafka.", sequence=1),
        ],
        entities=[
            ExtractedEntity(id="alice", name="Alice", entity_type="Person"),
            ExtractedEntity(id="ingest", name="Ingest", entity_type="Project"),
            ExtractedEntity(id="kafka", name="Kafka", entity_type="Service"),
        ],
        relationships=[
            ExtractedRelationship(src_id="alice", dst_id="ingest", rel_type="WORKS_ON"),
            ExtractedRelationship(src_id="ingest", dst_id="kafka", rel_type="DEPENDS_ON"),
        ],
    )


async def test_pgrg_ingest_and_retrieve(tiny_extraction):
    engine = PgrgEngine(dsn=DSN, namespace="bakeoff_test")
    try:
        await engine.ingest(tiny_extraction)
        resp = await engine.retrieve("Who works on Ingest?")
        assert len(resp.retrieved_chunk_ids) > 0
        assert resp.retrieval_ms > 0
    finally:
        await engine.cleanup()


def test_pgrg_info_matches_config():
    engine = PgrgEngine(dsn=DSN, namespace="bakeoff_test")
    info = engine.info()
    assert info.name == "pgrg"
    assert info.embedding_model == "BAAI/bge-small-en-v1.5"
