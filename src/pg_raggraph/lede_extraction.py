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


def _entities_from_text(text: str) -> list[ExtractedEntity]:
    """Untyped entity strings via lede's spaCy backend → ExtractedEntity.

    lede 0.3.0's public API returns a flat tuple of surface strings with
    no NER labels, so entity_type is the generic "entity". Reuses the
    existing false-positive filter.
    """
    import lede
    import lede_spacy  # noqa: F401  (registers the spacy backend on import)

    from pg_raggraph.extraction import _is_valid_entity

    if not text or not text.strip():
        return []
    raw = lede.extract.metadata(text, backend="spacy").entities
    seen: set[str] = set()
    out: list[ExtractedEntity] = []
    for name in raw:
        name = (name or "").strip()
        if name in seen or not _is_valid_entity(name):
            continue
        seen.add(name)
        out.append(ExtractedEntity(name=name, entity_type="entity", description=""))
    return out


def _mentions(sentence: str, name: str) -> bool:
    """True if `name` appears in `sentence` on word-ish boundaries.

    Avoids substring false positives ("NASA" inside "NASASAT").
    """
    return (
        re.search(rf"(?<!\w){re.escape(name)}(?!\w)", sentence, flags=re.IGNORECASE)
        is not None
    )


def _cooccurrence_edges(
    names: list[str], sentences: list[str]
) -> list[ExtractedRelationship]:
    """RELATED_TO edges for entities co-occurring in the same sentence.

    weight = number of sentences the pair co-occurs in. description = the
    first supporting sentence verbatim. Deterministic: pairs are ordered
    by first appearance in `names`.
    """
    counts: dict[tuple[str, str], int] = {}
    support: dict[tuple[str, str], str] = {}
    for sent in sentences:
        present = [n for n in names if _mentions(sent, n)]
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                a, b = present[i], present[j]
                if a == b:
                    continue
                pair = (a, b)
                counts[pair] = counts.get(pair, 0) + 1
                support.setdefault(pair, sent.strip())
    return [
        ExtractedRelationship(
            source=a,
            target=b,
            rel_type="RELATED_TO",
            description=support[(a, b)],
            weight=float(n),
        )
        for (a, b), n in counts.items()
    ]


def _extract_one(text: str) -> ExtractionResult:
    from lede.sentences import split_sentences

    from pg_raggraph.extraction import filter_extraction

    entities = _entities_from_text(text)
    if not entities:
        return ExtractionResult()
    names = [e.name for e in entities]
    sentences = split_sentences(text) if text and text.strip() else []
    rels = _cooccurrence_edges(names, sentences)
    return filter_extraction(ExtractionResult(entities=entities, relationships=rels))


async def extract_from_chunks_lede(
    chunks: list[dict],
    llm,  # ignored — accepted for seam parity with extract_from_chunks
    db,  # unused — no LLM cache on the deterministic path
    config: PGRGConfig | None,
) -> list[ExtractionResult]:
    """Deterministic, LLM-free analogue of extraction.extract_from_chunks.

    One ExtractionResult per chunk. CPU-bound lede/spaCy work is run in a
    thread so the event loop is not blocked. Order is preserved.
    """

    def _work(text: str) -> ExtractionResult:
        try:
            return _extract_one(text)
        except Exception as e:  # never fail the whole ingest on one chunk
            logger.warning("lede extraction failed for a chunk: %s", e)
            return ExtractionResult()

    texts = [c.get("embedded_content") or c.get("content") or "" for c in chunks]
    return await asyncio.gather(*(asyncio.to_thread(_work, t) for t in texts))


def select_extractor(config):
    """Decide which extractor the ingest gate should use.

    Returns ``(extractor_fn_or_None, needs_llm)``.

    - ``fact_extractor == "lede_spacy"``: ``(extract_from_chunks_lede,
      False)`` — runs the deterministic path; no ``llm_base_url`` needed.
    - anything else: ``(None, True)`` — caller keeps the existing
      LLM / skip_extraction behavior unchanged.
    """
    if getattr(config, "fact_extractor", "none") == "lede_spacy":
        return extract_from_chunks_lede, False
    return None, True
