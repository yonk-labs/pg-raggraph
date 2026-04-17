"""Postgres source corpus loader -- reads from LLM extraction cache."""
from __future__ import annotations

import json
from pathlib import Path

from age_bakeoff.models import ExtractionOutput

_CACHE_PATH = (
    Path(__file__).resolve().parents[3] / "corpora" / "pg-src" / "extraction_cache.json"
)


class PgSrcCorpus:
    name = "pg-src"

    def load(self) -> ExtractionOutput:
        if not _CACHE_PATH.exists():
            raise FileNotFoundError(
                f"pg-src extraction cache not found at {_CACHE_PATH}. "
                "Run the LLM extraction first (scripts/extract_pg_src.py) "
                "to populate the cache."
            )
        raw = json.loads(_CACHE_PATH.read_text())
        return ExtractionOutput(**raw)
