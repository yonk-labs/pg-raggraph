"""Shared data contracts for the bake-off."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Chunk(BaseModel):
    """A single content chunk — the fairness boundary between engines."""

    model_config = ConfigDict(frozen=True)

    id: str
    document_id: str
    content: str
    sequence: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedEntity(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    entity_type: str
    description: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class ExtractedRelationship(BaseModel):
    model_config = ConfigDict(frozen=True)

    src_id: str
    dst_id: str
    rel_type: str
    weight: float = 1.0
    description: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class ExtractionOutput(BaseModel):
    """Byte-identical payload that both engines ingest."""

    corpus: str
    chunks: list[Chunk]
    entities: list[ExtractedEntity]
    relationships: list[ExtractedRelationship]


class QuestionClass(str, Enum):
    semantic = "semantic"
    single_hop = "single_hop"
    multi_hop_bridging = "multi_hop_bridging"
    factual = "factual"


class Question(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    question: str
    gold_answer: str
    required_facts: list[str]
    required_entities: list[str] = Field(default_factory=list)
    question_class: QuestionClass
    notes: str = ""


class RunResult(BaseModel):
    engine: str  # "pgrg" | "age"
    corpus: str
    question_id: str
    run_number: int
    cold: bool
    retrieval_ms: float
    answer_ms: float
    retrieved_chunk_ids: list[str]
    generated_answer: str
    error: str | None = None
