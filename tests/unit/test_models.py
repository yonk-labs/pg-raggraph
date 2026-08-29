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


def test_extracted_relationship_normalizes_rel_type():
    """Format variants of the same rel_type canonicalize identically (#106)."""
    from pg_raggraph.models import ExtractedRelationship

    variants = [
        "maintains relationship with",
        "Maintains-Relationship-With",
        "MAINTAINS_RELATIONSHIP_WITH",
        "  maintains  relationship  with  ",
        "maintains_relationship_with.",
    ]
    normalized = {
        ExtractedRelationship(source="a", target="b", rel_type=v).rel_type for v in variants
    }
    assert normalized == {"MAINTAINS_RELATIONSHIP_WITH"}


def test_extracted_relationship_rel_type_canonical_passthrough_and_fallback():
    from pg_raggraph.models import ExtractedRelationship

    # Already-canonical types are untouched.
    r = ExtractedRelationship(source="a", target="b", rel_type="DEPENDS_ON")
    assert r.rel_type == "DEPENDS_ON"
    # Degenerate input (nothing alphanumeric) falls back to the default.
    r = ExtractedRelationship(source="a", target="b", rel_type="---")
    assert r.rel_type == "RELATED_TO"
    # Default stays the default.
    r = ExtractedRelationship(source="a", target="b")
    assert r.rel_type == "RELATED_TO"


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
