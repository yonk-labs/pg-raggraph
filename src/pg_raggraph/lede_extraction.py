"""Deterministic, LLM-free extraction via lede + lede-spacy.

Three ``fact_extractor`` values route here:

- ``lede_spacy`` — entities from lede's spaCy NER backend (untyped surface
  strings in lede 0.3.0); edges are sentence-level co-occurrence. No LLM,
  no network.
- ``lede_prose`` — widens the deterministic net for everyday prose: full
  spaCy NER (keeps FAC/ORG — venues, businesses) plus noun-chunk head
  lemmas as entities ("the seafood gumbo" -> "gumbo", variant phrase kept
  in the description); same sentence co-occurrence edges. Head-lemma
  canonicalization makes dish/thing variants land on one node.
- ``llm+lede`` — runs the LLM extractor AND ``lede_prose`` per chunk and
  unions the results: typed LLM edges plus a deterministic co-occurrence
  net that guarantees in-sentence links survive even when the LLM drops
  them. Degrades to the deterministic leg (one warning) without an LLM.

Optional deps — install with:
    pip install 'pg-raggraph[lede_spacy]'
    python -m spacy download en_core_web_sm
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading

from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
)

logger = logging.getLogger("pg_raggraph.lede_extraction")

# fact_extractor values that can build a graph without an LLM provider.
# __init__._ingest_document consults this to keep extraction enabled when
# llm is None; "llm+lede" degrades to its deterministic leg in that case.
LEDE_CAPABLE_EXTRACTORS = frozenset({"lede_spacy", "lede_prose", "llm+lede"})

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
        raise RuntimeError(f"spaCy model `en_core_web_sm` not available. {_INSTALL_HINT}") from e


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
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", sentence, flags=re.IGNORECASE) is not None


def _edges_from_presence(
    presence: list[tuple[list[str], str]],
) -> list[ExtractedRelationship]:
    """RELATED_TO edges from per-sentence entity presence lists.

    ``presence`` is ``[(names_in_sentence, sentence_text), ...]``.
    weight = number of sentences the pair co-occurs in. description = the
    first supporting sentence verbatim. Deterministic: pairs are ordered
    by appearance within each sentence's presence list.
    """
    counts: dict[tuple[str, str], int] = {}
    support: dict[tuple[str, str], str] = {}
    for present, sent in presence:
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


def _cooccurrence_edges(names: list[str], sentences: list[str]) -> list[ExtractedRelationship]:
    """RELATED_TO edges for entities co-occurring in the same sentence.

    Regex-mention variant used by the ``lede_spacy`` path, where entities
    are surface strings that must be re-located in sentence text.
    """
    presence = [([n for n in names if _mentions(sent, n)], sent) for sent in sentences]
    return _edges_from_presence(presence)


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


# --- lede_prose: NER + noun-chunk heads --------------------------------------

# NER labels that are numbers/dates, not graph nodes.
_NER_SKIP_LABELS = frozenset(
    {"CARDINAL", "ORDINAL", "QUANTITY", "PERCENT", "MONEY", "DATE", "TIME"}
)

# High-frequency abstract heads that add noise, not joins. Extends the
# generic blocklist in extraction._is_valid_entity for the noun-chunk path.
# ponytail: naive stoplist; swap for a frequency/IDF gate if graphs get fat.
_PROSE_HEAD_STOPLIST = frozenset(
    {
        "thing",
        "things",
        "time",
        "times",
        "day",
        "days",
        "week",
        "month",
        "year",
        "way",
        "lot",
        "lots",
        "people",
        "person",
        "one",
        "ones",
        "bit",
        "kind",
        "sort",
        "stuff",
        "place",
        "places",
        "someone",
        "somebody",
        "something",
        "anyone",
        "anything",
        "everyone",
        "everything",
        "nothing",
        "part",
        "side",
        "end",
        "point",
        "case",
        "fact",
        "idea",
        "area",
    }
)

_NLP = None
# spaCy Language objects are not guaranteed thread-safe for concurrent
# calls, and extraction fans out via asyncio.to_thread.
# ponytail: one lock serializes parsing; per-thread pipelines if throughput matters.
_NLP_LOCK = threading.Lock()


def _get_nlp():
    global _NLP
    if _NLP is None:
        import spacy

        _NLP = spacy.load("en_core_web_sm")
    return _NLP


def _prose_extract_one(text: str) -> ExtractionResult:
    """NER + noun-chunk-head entities with sentence co-occurrence edges.

    One spaCy parse supplies everything: NER spans (typed by lowercased
    label), noun-chunk head lemmas as canonical common-noun entities (the
    full phrase becomes the description, so "The seafood gumbo" and
    "wood-fired margherita pizza" land on nodes ``gumbo`` / ``pizza``),
    sentence boundaries, and span-accurate presence — no regex re-matching.
    """
    from pg_raggraph.extraction import _is_valid_entity, filter_extraction

    if not text or not text.strip():
        return ExtractionResult()

    with _NLP_LOCK:
        doc = _get_nlp()(text)

    entities: dict[str, ExtractedEntity] = {}
    presence: list[tuple[list[str], str]] = []

    for sent in doc.sents:
        present: list[str] = []
        for ent in sent.ents:
            if ent.label_ in _NER_SKIP_LABELS:
                continue
            name = ent.text.strip()
            if not _is_valid_entity(name):
                continue
            entities.setdefault(
                name,
                ExtractedEntity(name=name, entity_type=ent.label_.lower(), description=""),
            )
            present.append(name)
        for nc in sent.noun_chunks:
            root = nc.root
            # Skip chunks already covered by an NER span, and pronouns.
            if root.ent_type_ or root.pos_ == "PRON":
                continue
            head = root.lemma_.lower().strip()
            if head in _PROSE_HEAD_STOPLIST or not _is_valid_entity(head):
                continue
            phrase = nc.text.strip()
            existing = entities.get(head)
            if existing is None:
                entities[head] = ExtractedEntity(
                    name=head,
                    entity_type="concept",
                    description=phrase if phrase.lower() != head else "",
                )
            elif not existing.description and phrase.lower() != head:
                # First variant phrase seen becomes the description.
                entities[head] = ExtractedEntity(
                    name=head, entity_type=existing.entity_type, description=phrase
                )
            present.append(head)
        # Order-stable dedupe within the sentence.
        presence.append((list(dict.fromkeys(present)), sent.text))

    if not entities:
        return ExtractionResult()
    rels = _edges_from_presence(presence)
    return filter_extraction(
        ExtractionResult(entities=list(entities.values()), relationships=rels)
    )


async def _run_deterministic(chunks: list[dict], one_fn) -> list[ExtractionResult]:
    """Thread-fanout shared by the deterministic extractors.

    One ExtractionResult per chunk. CPU-bound lede/spaCy work is run in a
    thread so the event loop is not blocked. Order is preserved.
    """

    def _work(text: str) -> ExtractionResult:
        try:
            return one_fn(text)
        except Exception as e:  # never fail the whole ingest on one chunk
            logger.warning("deterministic extraction failed for a chunk: %s", e)
            return ExtractionResult()

    texts = [c.get("embedded_content") or c.get("content") or "" for c in chunks]
    return await asyncio.gather(*(asyncio.to_thread(_work, t) for t in texts))


async def extract_from_chunks_lede(
    chunks: list[dict],
    llm,  # ignored — accepted for seam parity with extract_from_chunks
    db,  # unused — no LLM cache on the deterministic path
    config: PGRGConfig | None,
) -> list[ExtractionResult]:
    """Deterministic, LLM-free analogue of extraction.extract_from_chunks."""
    return await _run_deterministic(chunks, _extract_one)


async def extract_from_chunks_prose(
    chunks: list[dict],
    llm,  # ignored — accepted for seam parity with extract_from_chunks
    db,  # unused — no LLM cache on the deterministic path
    config: PGRGConfig | None,
) -> list[ExtractionResult]:
    """Deterministic prose extraction: NER + noun-chunk heads + co-occurrence."""
    return await _run_deterministic(chunks, _prose_extract_one)


def _merge_results(primary: ExtractionResult, secondary: ExtractionResult) -> ExtractionResult:
    """Union two per-chunk extractions; the primary (LLM) result wins.

    Entities dedupe casefold ("Gumbo" vs "gumbo" keep the primary's form);
    secondary relationship endpoints are remapped to the surviving name so
    they still resolve in the ingest path's exact-name entity map.
    """
    canonical: dict[str, str] = {}
    entities: list[ExtractedEntity] = []
    for ent in list(primary.entities) + list(secondary.entities):
        key = ent.name.casefold()
        if key not in canonical:
            canonical[key] = ent.name
            entities.append(ent)

    def _canon(name: str) -> str:
        return canonical.get(name.casefold(), name)

    seen = {(r.source.casefold(), r.target.casefold(), r.rel_type) for r in primary.relationships}
    rels = list(primary.relationships)
    for r in secondary.relationships:
        key = (r.source.casefold(), r.target.casefold(), r.rel_type)
        if key in seen:
            continue
        seen.add(key)
        rels.append(
            ExtractedRelationship(
                source=_canon(r.source),
                target=_canon(r.target),
                rel_type=r.rel_type,
                description=r.description,
                weight=r.weight,
            )
        )
    return ExtractionResult(entities=entities, relationships=rels)


_warned_union_no_llm = False


async def extract_from_chunks_union(
    chunks: list[dict],
    llm,
    db,
    config: PGRGConfig | None,
) -> list[ExtractionResult]:
    """``llm+lede``: LLM extraction unioned with the deterministic prose net.

    The LLM leg supplies typed, intent-carrying edges (LIKES, SERVES, ...);
    the lede_prose leg guarantees in-sentence co-occurrence links exist even
    for facts the LLM drops. Without an LLM provider, runs the deterministic
    leg alone (single warning).
    """
    if llm is None:
        global _warned_union_no_llm
        if not _warned_union_no_llm:
            logger.warning(
                "fact_extractor='llm+lede' but no LLM provider is configured — "
                "running the deterministic lede_prose leg only."
            )
            _warned_union_no_llm = True
        return await extract_from_chunks_prose(chunks, None, None, config)

    from pg_raggraph.extraction import extract_from_chunks

    llm_results, det_results = await asyncio.gather(
        extract_from_chunks(chunks, llm, db, config),
        extract_from_chunks_prose(chunks, None, None, config),
    )
    return [_merge_results(a, b) for a, b in zip(llm_results, det_results)]


def select_extractor(config):
    """Decide which extractor the ingest gate should use.

    Returns ``(extractor_fn_or_None, needs_llm)``.

    - ``"lede_spacy"`` / ``"lede_prose"``: deterministic path, no LLM needed.
    - ``"llm+lede"``: union path — wants an LLM (degrades to deterministic
      without one), so ``needs_llm`` is True and callers should still build
      the provider.
    - anything else: ``(None, True)`` — caller keeps the existing
      LLM / skip_extraction behavior unchanged.
    """
    fe = getattr(config, "fact_extractor", "none")
    if fe == "lede_spacy":
        return extract_from_chunks_lede, False
    if fe == "lede_prose":
        return extract_from_chunks_prose, False
    if fe == "llm+lede":
        return extract_from_chunks_union, True
    return None, True
