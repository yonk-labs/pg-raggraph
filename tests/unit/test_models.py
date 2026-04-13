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
