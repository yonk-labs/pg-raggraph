"""AGE engine adapter integration test. Requires Docker DB."""
from __future__ import annotations

import psycopg
import pytest

from age_bakeoff.engines.age import AgeEngine
from age_bakeoff.models import Chunk, ExtractedEntity, ExtractedRelationship, ExtractionOutput

DSN = "postgresql://postgres:postgres@localhost:5435/age_bakeoff_age"


def _db_available() -> bool:
    try:
        with psycopg.connect(DSN, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="AGE DB not reachable")


@pytest.fixture(autouse=True)
def _allow_real_db(monkeypatch):
    """Override the conftest guard so we can hit the real Docker DB."""
    monkeypatch.setenv("AGE_DSN", DSN)


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


async def test_age_ingest_and_retrieve(tiny_extraction):
    engine = AgeEngine(dsn=DSN, graph_name="bakeoff_test")
    try:
        await engine.ingest(tiny_extraction)
        resp = await engine.retrieve("Who works on Ingest?")
        assert len(resp.retrieved_chunk_ids) > 0
        assert resp.retrieval_ms > 0
    finally:
        await engine.cleanup()


def test_age_info_matches_config():
    engine = AgeEngine(dsn=DSN, graph_name="bakeoff_test")
    info = engine.info()
    assert info.name == "age"
