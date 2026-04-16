"""LLM-based extraction over Postgres source chunks with on-disk caching."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from age_bakeoff.extraction.prompts import EXTRACTION_SYSTEM, EXTRACTION_USER_TEMPLATE
from age_bakeoff.models import (
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
)

_NAME_SAFE = re.compile(r"[^a-zA-Z0-9_]+")


def _slug(name: str) -> str:
    return _NAME_SAFE.sub("_", name).lower().strip("_")


def extract_pg_src(
    chunks: list[Chunk],
    client: Any,
    cache_path: Path,
    model: str = "gpt-5-mini",
) -> ExtractionOutput:
    """Run LLM extraction, cache, dedupe, return.

    If cache_path exists, load and return without calling the LLM.
    """
    cache_path = Path(cache_path)
    if cache_path.exists():
        raw = json.loads(cache_path.read_text())
        return ExtractionOutput(**raw)

    entities_by_id: dict[str, ExtractedEntity] = {}
    relationships: list[ExtractedRelationship] = []

    for chunk in chunks:
        user_msg = EXTRACTION_USER_TEMPLATE.format(
            source_path=chunk.metadata.get("source_path", chunk.document_id),
            content=chunk.content,
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            continue

        for e in data.get("entities", []):
            eid = _slug(e["name"])
            if eid not in entities_by_id:
                entities_by_id[eid] = ExtractedEntity(
                    id=eid,
                    name=e["name"],
                    entity_type=e.get("entity_type", "Concept"),
                    description=e.get("description", ""),
                )
        for r in data.get("relationships", []):
            src_id = _slug(r["src"])
            dst_id = _slug(r["dst"])
            if src_id in entities_by_id and dst_id in entities_by_id:
                relationships.append(
                    ExtractedRelationship(
                        src_id=src_id,
                        dst_id=dst_id,
                        rel_type=r.get("rel_type", "RELATES_TO"),
                        description=r.get("description", ""),
                    )
                )

    output = ExtractionOutput(
        corpus="pg_src",
        chunks=chunks,
        entities=sorted(entities_by_id.values(), key=lambda e: e.id),
        relationships=relationships,
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(output.model_dump_json(indent=2))
    return output
