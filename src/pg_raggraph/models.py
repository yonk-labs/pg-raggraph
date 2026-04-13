"""Pydantic data models for pg-raggraph."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# --- Storage models (mirror DB tables) ---


class Document(BaseModel):
    id: int | None = None
    namespace: str = "default"
    content_hash: str
    source_path: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class Chunk(BaseModel):
    id: int | None = None
    document_id: int
    content: str
    embedding: list[float] | None = None
    token_count: int = 0
    metadata: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class Entity(BaseModel):
    id: int | None = None
    namespace: str = "default"
    name: str
    entity_type: str
    description: str = ""
    embedding: list[float] | None = None
    community_id: int | None = None
    properties: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class Relationship(BaseModel):
    id: int | None = None
    namespace: str = "default"
    src_id: int
    dst_id: int
    rel_type: str
    weight: float = 1.0
    description: str = ""
    properties: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class EntityChunk(BaseModel):
    entity_id: int
    chunk_id: int
    confidence: float = 1.0
    provenance: str = "extracted"  # extracted | inferred | ambiguous


class RelationshipChunk(BaseModel):
    relationship_id: int
    chunk_id: int
    confidence: float = 1.0
    provenance: str = "extracted"


# --- Extraction models (LLM output) ---


class ExtractedEntity(BaseModel):
    name: str
    entity_type: str = "concept"
    description: str = ""


class ExtractedRelationship(BaseModel):
    source: str
    target: str
    rel_type: str = "RELATED_TO"
    description: str = ""
    # Accept None from the LLM — it sometimes returns weight=null.
    # Coerce to 1.0 to avoid Pydantic validation errors.
    weight: float | None = 1.0

    def model_post_init(self, __context) -> None:
        if self.weight is None:
            self.weight = 1.0


class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)


# --- Query models ---


class ChunkResult(BaseModel):
    content: str
    score: float
    document_source: str | None = None
    entities: list[str] = Field(default_factory=list)
    chunk_id: int | None = None  # DB id, used for graph boost lookups


class EntityResult(BaseModel):
    name: str
    entity_type: str
    description: str


class RelationshipResult(BaseModel):
    source: str
    target: str
    rel_type: str
    description: str


class QueryResult(BaseModel):
    answer: str = ""
    chunks: list[ChunkResult] = Field(default_factory=list)
    entities: list[EntityResult] = Field(default_factory=list)
    relationships: list[RelationshipResult] = Field(default_factory=list)
    query_mode: str = "hybrid"
    latency_ms: float = 0.0
    # Confidence signals (populated from chunks)
    top_score: float = 0.0
    avg_score: float = 0.0
    confidence: str = "unknown"  # high | medium | low | unknown

    def populate_confidence(
        self,
        high_threshold: float = 0.7,
        low_threshold: float = 0.4,
    ) -> None:
        """Compute top_score, avg_score, and confidence level from chunks."""
        if not self.chunks:
            self.top_score = 0.0
            self.avg_score = 0.0
            self.confidence = "low"
            return
        scores = [c.score for c in self.chunks]
        self.top_score = max(scores)
        self.avg_score = sum(scores) / len(scores)
        if self.top_score >= high_threshold:
            self.confidence = "high"
        elif self.top_score < low_threshold:
            self.confidence = "low"
        else:
            self.confidence = "medium"
