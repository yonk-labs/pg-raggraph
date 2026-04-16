"""Loaders that produce ExtractionOutput for Acme and SCOTUS corpora.

The data was ported from yonk-samples/graphrag-demo seed modules via
scripts/port_{acme,scotus}_seed.py. The bake-off is self-contained at
runtime — it reads JSON files, not the upstream modules.
"""
from __future__ import annotations

import json
from pathlib import Path

from age_bakeoff.chunker import chunk_text
from age_bakeoff.models import (
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
)

_DATA_DIR = Path(__file__).parent / "data"


def load_acme_extraction() -> ExtractionOutput:
    raw = json.loads((_DATA_DIR / "acme.json").read_text())
    return _build_output("acme", raw)


def load_scotus_extraction() -> ExtractionOutput:
    raw = json.loads((_DATA_DIR / "scotus.json").read_text())
    return _build_output("scotus", raw)


def _build_output(corpus: str, raw: dict) -> ExtractionOutput:
    entities = [ExtractedEntity(**e) for e in raw["entities"]]
    relationships = [ExtractedRelationship(**r) for r in raw["relationships"]]
    chunks: list[Chunk] = []
    for doc in raw["documents"]:
        doc_chunks = chunk_text(text=doc["content"], document_id=doc["id"])
        for c in doc_chunks:
            # Inject author/project metadata so retrieval scoring can
            # cross-reference entity graph with chunk provenance
            meta = {
                **c.metadata,
                "author_id": doc.get("author_id"),
                "project_id": doc.get("project_id"),
                "title": doc.get("title", ""),
                "doc_type": doc.get("doc_type", ""),
            }
            chunks.append(c.model_copy(update={"metadata": meta}))
    return ExtractionOutput(
        corpus=corpus,
        chunks=chunks,
        entities=entities,
        relationships=relationships,
    )
