"""Engine protocol — the boundary both adapters implement."""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from age_bakeoff.models import ExtractionOutput


class EngineInfo(BaseModel):
    name: str  # "pgrg" | "age"
    embedding_model: str
    answer_model: str
    top_k: int
    hop_budget: int


class RetrievalResponse(BaseModel):
    retrieved_chunk_ids: list[str]
    retrieved_chunk_contents: list[str]
    retrieval_ms: float


class Engine(Protocol):
    async def ingest(self, extraction: ExtractionOutput) -> None: ...
    async def retrieve(self, question: str) -> RetrievalResponse: ...
    async def generate_answer(self, question: str, retrieved_contents: list[str]) -> tuple[str, float]: ...
    def info(self) -> EngineInfo: ...
