"""Tests for Pydantic models."""

from pg_raggraph.models import (
    Chunk,
    Document,
    Entity,
    ExtractionResult,
    QueryResult,
    Relationship,
)


def test_document_defaults():
    doc = Document(content_hash="abc123")
    assert doc.id is None
    assert doc.namespace == "default"
    assert doc.metadata == {}


def test_entity_serialization():
    e = Entity(name="PostgreSQL", entity_type="technology", description="A database")
    data = e.model_dump()
    assert data["name"] == "PostgreSQL"
    assert data["properties"] == {}


def test_extraction_result():
    result = ExtractionResult.model_validate(
        {
            "entities": [
                {"name": "PostgreSQL", "entity_type": "technology", "description": "A database"}
            ],
            "relationships": [
                {
                    "source": "pgvector",
                    "target": "PostgreSQL",
                    "rel_type": "EXTENDS",
                    "description": "pgvector extends PostgreSQL",
                }
            ],
        }
    )
    assert len(result.entities) == 1
    assert len(result.relationships) == 1
    assert result.relationships[0].weight == 1.0


def test_query_result():
    r = QueryResult(query_mode="hybrid", latency_ms=42.5)
    assert r.chunks == []
    assert r.answer == ""
    assert r.latency_ms == 42.5


def test_chunk_defaults():
    c = Chunk(document_id=1, content="test")
    assert c.embedding is None
    assert c.token_count == 0


def test_relationship_defaults():
    r = Relationship(src_id=1, dst_id=2, rel_type="RELATED")
    assert r.weight == 1.0
    assert r.namespace == "default"


def test_chunkresult_consumer_surface_fields_default_none():
    from pg_raggraph.models import ChunkResult

    c = ChunkResult(content="x", score=0.5)
    # PRG-1 additive fields default to None / are optional
    assert c.metadata is None
    assert c.retracted is None
    assert c.version_label is None
    assert c.effective_from is None
    assert c.effective_to is None
    assert c.superseded_by_id is None
    # PRG-4: chunk_id stays optional in the type, default None
    assert c.chunk_id is None


def test_chunkresult_consumer_surface_fields_accept_values():
    from datetime import datetime, timezone

    from pg_raggraph.models import ChunkResult

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    c = ChunkResult(
        content="x",
        score=0.5,
        chunk_id=42,
        metadata={"k": "v"},
        retracted=True,
        version_label="v2",
        effective_from=now,
        effective_to=None,
        superseded_by_id=99,
    )
    assert c.chunk_id == 42
    assert c.metadata == {"k": "v"}
    assert c.retracted is True
    assert c.version_label == "v2"
    assert c.effective_from == now
    assert c.superseded_by_id == 99
