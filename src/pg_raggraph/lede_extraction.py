"""Deterministic, LLM-free extraction via lede + lede-spacy.

`fact_extractor="lede_spacy"` selects this path. Entities come from
lede's spaCy NER backend (untyped surface strings in lede 0.3.0);
edges are sentence-level co-occurrence. No LLM, no network.

Optional deps — install with:
    pip install 'pg-raggraph[lede_spacy]'
    python -m spacy download en_core_web_sm
"""

from __future__ import annotations

import asyncio
import logging
import re

from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
)

logger = logging.getLogger("pg_raggraph.lede_extraction")

_INSTALL_HINT = (
    'fact_extractor="lede_spacy" requires the optional extra and the '
    "spaCy model:\n"
    "    pip install 'pg-raggraph[lede_spacy]'\n"
    "    python -m spacy download en_core_web_sm"
)


def ensure_lede_available() -> None:
    """Raise RuntimeError with exact remediation if the lede path can't run.

    Distinguishes missing ``lede``, missing ``lede_spacy``, and missing
    spaCy model so the operator knows which command to run.
    """
    try:
        import lede  # noqa: F401
    except ModuleNotFoundError as e:
        raise RuntimeError(f"`lede` not installed. {_INSTALL_HINT}") from e
    try:
        import lede_spacy  # noqa: F401  (import registers the spacy backend)
    except ModuleNotFoundError as e:
        raise RuntimeError(f"`lede-spacy` not installed. {_INSTALL_HINT}") from e
    try:
        import spacy

        spacy.load("en_core_web_sm")
    except (ModuleNotFoundError, OSError) as e:
        raise RuntimeError(
            f"spaCy model `en_core_web_sm` not available. {_INSTALL_HINT}"
        ) from e
