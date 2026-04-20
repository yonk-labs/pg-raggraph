"""Loaders that produce ExtractionOutput for Acme and SCOTUS corpora.

The data was ported from yonk-samples/graphrag-demo seed modules via
scripts/port_{acme,scotus}_seed.py. The bake-off is self-contained at
runtime — it reads JSON files, not the upstream modules.

Chunker strategy is controlled by ``BAKEOFF_CHUNKER`` (``sentence_aware`` —
the prior baseline default — or ``hierarchy``, the factorial-detour winner).
Callers can also pass ``chunker_strategy`` explicitly.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from age_bakeoff.chunker import ChunkerStrategy, chunk_text
from age_bakeoff.models import (
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
)

_DATA_DIR = Path(__file__).parent / "data"


def _resolve_strategy(explicit: ChunkerStrategy | None) -> ChunkerStrategy:
    if explicit is not None:
        return explicit
    val = os.environ.get("BAKEOFF_CHUNKER", "sentence_aware").strip()
    if val not in ("sentence_aware", "hierarchy"):
        raise ValueError(
            f"BAKEOFF_CHUNKER={val!r} invalid; expected "
            "'sentence_aware' or 'hierarchy'"
        )
    return val  # type: ignore[return-value]


def load_acme_extraction(
    chunker_strategy: ChunkerStrategy | None = None,
) -> ExtractionOutput:
    raw = json.loads((_DATA_DIR / "acme.json").read_text())
    return _build_output("acme", raw, _resolve_strategy(chunker_strategy))


def load_scotus_extraction(
    chunker_strategy: ChunkerStrategy | None = None,
) -> ExtractionOutput:
    raw = json.loads((_DATA_DIR / "scotus.json").read_text())
    return _build_output("scotus", raw, _resolve_strategy(chunker_strategy))


def _build_output(
    corpus: str, raw: dict, strategy: ChunkerStrategy
) -> ExtractionOutput:
    entities = [ExtractedEntity(**e) for e in raw["entities"]]
    relationships = [ExtractedRelationship(**r) for r in raw["relationships"]]
    chunks: list[Chunk] = []
    for doc in raw["documents"]:
        title = doc.get("title", "")
        doc_chunks = chunk_text(
            text=doc["content"],
            document_id=doc["id"],
            strategy=strategy,
            title=title,
        )
        for c in doc_chunks:
            # Inject author/project metadata so retrieval scoring can
            # cross-reference entity graph with chunk provenance
            meta = {
                **c.metadata,
                "author_id": doc.get("author_id"),
                "project_id": doc.get("project_id"),
                "title": title,
                "doc_type": doc.get("doc_type", ""),
            }
            chunks.append(c.model_copy(update={"metadata": meta}))
    return ExtractionOutput(
        corpus=corpus,
        chunks=chunks,
        entities=entities,
        relationships=relationships,
    )
