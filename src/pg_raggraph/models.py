"""Pydantic data models for pg-raggraph."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# --- Evolution tracking type aliases ---

FactEdgeType = Literal["SUPERSEDES", "CONTRADICTS", "PRECEDES", "SUPPORTS", "REFINES"]
"""Typed fact-edge relations. SUPERSEDES = src replaces dst (dst invalid forward);
CONTRADICTS = src and dst incompatible, neither superseded; PRECEDES = temporal
order only (weaker); SUPPORTS = src evidence for dst; REFINES = src is more specific."""

FactEdgeInferredBy = Literal["explicit", "llm", "temporal", "heuristic", "document_hint"]
"""How a fact edge was produced. explicit = caller-supplied; llm = slow-path
LLM inference; temporal = derived from effective_from ordering; heuristic =
rule-based (e.g., same entity, newer doc); document_hint = derived from
document_versions.supersedes_document_id."""

# --- Storage models (mirror DB tables) ---


class Document(BaseModel):
    id: int | None = None
    namespace: str = "default"
    content_hash: str
    source_path: str | None = None
    metadata: dict = Field(default_factory=dict)
    # Evolution tracking (Tier 1+) — all optional. effective_to=None means "still effective".
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    retracted: bool = False
    version_label: str | None = None
    created_at: datetime | None = None


class Chunk(BaseModel):
    id: int | None = None
    document_id: int
    content: str
    embedded_content: str = ""
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


# --- Evolution tracking (Tier 1+) ---


class DocumentVersion(BaseModel):
    id: int | None = None
    namespace: str  # NOT NULL in schema — required
    document_id: int
    version_label: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    supersedes_document_id: int | None = None
    retracted: bool = False
    retracted_at: datetime | None = None
    retraction_reason: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class Fact(BaseModel):
    id: int | None = None
    namespace: str  # NOT NULL in schema — required
    source_chunk_id: int
    subject: str
    subject_entity_id: int | None = None
    predicate: str
    object: str
    object_entity_id: int | None = None
    support_span: str
    confidence: float = 1.0
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    retracted: bool = False
    retracted_at: datetime | None = None
    retraction_reason: str | None = None
    extractor: str = "unknown"
    properties: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class FactEdge(BaseModel):
    id: int | None = None
    src_fact_id: int
    dst_fact_id: int
    edge_type: FactEdgeType
    confidence: float = 1.0
    inferred_by: FactEdgeInferredBy
    created_at: datetime | None = None


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
    chunk_id: int | None = None
    """DB id (chunks.id). PRG-4 guarantee: always populated and stable for
    results returned by GraphRAG.query()/ask() — the same stored chunk has an
    identical, non-null chunk_id across re-queries. The type stays optional
    for back-compat with direct ChunkResult construction."""
    # --- PRG-1: opaque caller metadata + evolution status (all optional) ---
    metadata: dict | None = None
    retracted: bool | None = None
    version_label: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    superseded_by_id: int | None = None


class EntityResult(BaseModel):
    name: str
    entity_type: str
    description: str


class RelationshipResult(BaseModel):
    source: str
    target: str
    rel_type: str
    description: str
    # Per-fact temporal fields (migration 006). None when the relationship
    # was extracted from text or supplied without temporal info — caller
    # should treat them as "always valid, never retracted". Populated for
    # SP-A bridge-produced facts and for known_relationships that opt in.
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    retracted: bool = False
    retracted_at: datetime | None = None


class QueryResult(BaseModel):
    answer: str = ""
    context: str = ""
    """Profile-packed context intended for answer synthesis. Empty means the
    legacy formatter should use the retrieved chunks directly."""
    summary: str = ""
    """Deterministic, LLM-free lede summary of the retrieved chunks. Populated
    by mode="summary" and by smart-mode tier-0; empty for other modes. When
    non-empty, generate_answer() ships it directly without an LLM round-trip."""
    result_id: str | None = None
    """Stable id for this result when retained in GraphRAG's in-process result
    cache (set by ask() when caching is enabled). Lets a follow-up call fetch
    the full chunks via GraphRAG.get_cached_result(result_id)."""
    chunks: list[ChunkResult] = Field(default_factory=list)
    entities: list[EntityResult] = Field(default_factory=list)
    relationships: list[RelationshipResult] = Field(default_factory=list)
    query_mode: str = "hybrid"
    latency_ms: float = 0.0
    # Confidence signals (populated from chunks)
    top_score: float = 0.0
    avg_score: float = 0.0
    confidence: str = "unknown"  # high | medium | low | unknown
    metadata: dict = Field(default_factory=dict)
    """Per-result metadata. Current keys (forward-compatible — callers should
    treat unknown keys as advisory):

      * ``graph_status_summary`` — per-status doc counts for the queried
        namespace. Set when background extraction is in play; lets a caller
        decide whether to retry (`pending > 0` means the graph is still
        backfilling) without breaking the existing API shape.
    """

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
