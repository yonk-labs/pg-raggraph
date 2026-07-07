import asyncio
import builtins

import pytest

from pg_raggraph import lede_extraction
from pg_raggraph.lede_extraction import select_extractor


def test_ensure_lede_available_passes_when_installed():
    # lede/lede_spacy/en_core_web_sm are in the dev extra — should not raise.
    lede_extraction.ensure_lede_available()


def test_ensure_lede_available_message_when_lede_missing(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "lede" or name.startswith("lede."):
            raise ModuleNotFoundError("No module named 'lede'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError) as exc:
        lede_extraction.ensure_lede_available()
    msg = str(exc.value)
    assert "pg-raggraph[lede_spacy]" in msg
    assert "spacy download en_core_web_sm" in msg
    assert 'fact_extractor="lede_spacy"' in msg


def test_entities_from_text_are_untyped_and_filtered():
    text = (
        "NASA launched the Saturn V rocket from Kennedy Space Center. "
        "Neil Armstrong and Buzz Aldrin walked on the Moon."
    )
    ents = lede_extraction._entities_from_text(text)
    names = {e.name for e in ents}
    assert "NASA" in names
    assert "Neil Armstrong" in names
    # generic type for v1 (lede 0.3.0 exposes no NER labels)
    assert all(e.entity_type == "entity" for e in ents)
    # blocklist/short-token filter from extraction._is_valid_entity applied
    assert all(len(e.name) >= 2 for e in ents)


def test_cooccurrence_edges_weighted_and_supported():
    names = ["NASA", "Saturn V", "Congress"]
    sentences = [
        "NASA launched the Saturn V rocket.",
        "Congress funded NASA that decade.",
        "NASA and Saturn V appeared together again here.",
    ]
    rels = lede_extraction._cooccurrence_edges(names, sentences)
    by_pair = {(r.source, r.target): r for r in rels}
    # NASA<->Saturn V co-occur in 2 sentences
    key = ("NASA", "Saturn V") if ("NASA", "Saturn V") in by_pair else ("Saturn V", "NASA")
    assert by_pair[key].weight == 2.0
    assert by_pair[key].rel_type == "RELATED_TO"
    assert "NASA" in by_pair[key].description  # verbatim supporting sentence
    # substring false-positives avoided: "NASA" must not match inside a word
    assert lede_extraction._mentions("NASASAT orbiter", "NASA") is False
    assert lede_extraction._mentions("NASA launched.", "NASA") is True


def test_extract_from_chunks_lede_returns_one_result_per_chunk():
    chunks = [
        {
            "content": "NASA launched the Saturn V rocket. NASA and Saturn V again.",
            "embedded_content": ("NASA launched the Saturn V rocket. NASA and Saturn V again."),
        },
        {"content": "", "embedded_content": ""},
    ]
    results = asyncio.run(lede_extraction.extract_from_chunks_lede(chunks, None, None, None))
    assert len(results) == 2
    assert any(e.name == "NASA" for e in results[0].entities)
    assert results[1].entities == [] and results[1].relationships == []


class _Cfg:
    def __init__(self, fact_extractor, skip_extraction=False, llm_base_url=""):
        self.fact_extractor = fact_extractor
        self.skip_extraction = skip_extraction
        self.llm_base_url = llm_base_url


def test_select_extractor_lede_path_needs_no_llm():
    fn, needs_llm = select_extractor(_Cfg("lede_spacy"))
    assert needs_llm is False
    assert fn is lede_extraction.extract_from_chunks_lede


def test_select_extractor_llm_path_unchanged():
    fn, needs_llm = select_extractor(_Cfg("llm", llm_base_url="http://x"))
    assert needs_llm is True
    assert fn is None  # caller uses the existing extract_from_chunks

    fn, needs_llm = select_extractor(_Cfg("none"))
    assert needs_llm is True and fn is None


def test_select_extractor_prose_and_union():
    fn, needs_llm = select_extractor(_Cfg("lede_prose"))
    assert needs_llm is False
    assert fn is lede_extraction.extract_from_chunks_prose

    fn, needs_llm = select_extractor(_Cfg("llm+lede"))
    assert needs_llm is True  # union still wants the provider
    assert fn is lede_extraction.extract_from_chunks_union


# --- lede_prose ---------------------------------------------------------------

_PROSE_TEXT = (
    "Greta Reyes said she has been craving gumbo lately. "
    "The seafood gumbo at Bayou Belle in New Orleans is incredible. "
    "Marcus lives in Portland and loves wood-fired margherita pizza."
)


def test_prose_extract_captures_common_nouns_and_ner():
    result = lede_extraction._prose_extract_one(_PROSE_TEXT)
    by_name = {e.name: e for e in result.entities}
    # NER entities keep their surface form and lowercased label
    assert by_name["Greta Reyes"].entity_type == "person"
    assert "New Orleans" in by_name
    assert "Bayou Belle" in by_name  # FAC label kept (venues/businesses)
    # noun-chunk heads canonicalize variants onto one common-noun node
    assert by_name["gumbo"].entity_type == "concept"
    assert "pizza" in by_name
    assert "seafood gumbo" not in by_name  # variant collapsed into "gumbo"
    # the variant phrase survives as the description
    assert "seafood gumbo" in by_name["gumbo"].description.lower()


def test_prose_cooccurrence_builds_join_links():
    result = lede_extraction._prose_extract_one(_PROSE_TEXT)
    pairs = {frozenset((r.source, r.target)) for r in result.relationships}
    # person—craving (chat sentence) and dish—venue—city (review sentence)
    assert frozenset(("Greta Reyes", "gumbo")) in pairs
    assert frozenset(("gumbo", "Bayou Belle")) in pairs
    assert frozenset(("Bayou Belle", "New Orleans")) in pairs
    assert all(r.rel_type == "RELATED_TO" for r in result.relationships)


def test_prose_skips_pronouns_and_stoplist_heads():
    result = lede_extraction._prose_extract_one("She loves it. That was a great thing.")
    assert result.entities == []
    assert result.relationships == []


def test_extract_from_chunks_prose_one_result_per_chunk():
    chunks = [
        {"content": _PROSE_TEXT, "embedded_content": _PROSE_TEXT},
        {"content": "", "embedded_content": ""},
    ]
    results = asyncio.run(lede_extraction.extract_from_chunks_prose(chunks, None, None, None))
    assert len(results) == 2
    assert any(e.name == "gumbo" for e in results[0].entities)
    assert results[1].entities == [] and results[1].relationships == []


# --- llm+lede union -----------------------------------------------------------


def _mk_result(entities, relationships=()):
    from pg_raggraph.models import (
        ExtractedEntity,
        ExtractedRelationship,
        ExtractionResult,
    )

    return ExtractionResult(
        entities=[ExtractedEntity(name=n, entity_type=t, description=d) for n, t, d in entities],
        relationships=[
            ExtractedRelationship(source=s, target=o, rel_type=rt, description="", weight=1.0)
            for s, o, rt in relationships
        ],
    )


def test_merge_results_canonicalizes_endpoints():
    llm = _mk_result(
        [("Gumbo", "food", "a stew"), ("Greta Reyes", "person", "")],
        [("Greta Reyes", "Gumbo", "LIKES")],
    )
    det = _mk_result(
        [("gumbo", "concept", "The seafood gumbo"), ("Bayou Belle", "fac", "")],
        [("gumbo", "Bayou Belle", "RELATED_TO"), ("Greta Reyes", "gumbo", "LIKES")],
    )
    merged = lede_extraction._merge_results(llm, det)
    names = [e.name for e in merged.entities]
    # casefold dedupe: LLM's "Gumbo" wins, det's "gumbo" dropped
    assert "Gumbo" in names and "gumbo" not in names
    assert "Bayou Belle" in names
    # det rel endpoints remapped to the surviving name so ingest resolves them
    rel = next(r for r in merged.relationships if r.rel_type == "RELATED_TO")
    assert rel.source == "Gumbo"
    # duplicate LIKES (casefold-equal endpoints) not doubled
    likes = [r for r in merged.relationships if r.rel_type == "LIKES"]
    assert len(likes) == 1


def test_union_degrades_to_prose_without_llm():
    chunks = [{"content": _PROSE_TEXT, "embedded_content": _PROSE_TEXT}]
    results = asyncio.run(lede_extraction.extract_from_chunks_union(chunks, None, None, None))
    assert len(results) == 1
    assert any(e.name == "gumbo" for e in results[0].entities)


def test_union_merges_llm_and_deterministic_legs(monkeypatch):
    import pg_raggraph.extraction as extraction_mod

    async def fake_llm_extract(chunks, llm, db, config):
        return [
            _mk_result(
                [("Greta Reyes", "person", ""), ("Gumbo", "food", "")],
                [("Greta Reyes", "Gumbo", "LIKES")],
            )
            for _ in chunks
        ]

    monkeypatch.setattr(extraction_mod, "extract_from_chunks", fake_llm_extract)
    chunks = [{"content": _PROSE_TEXT, "embedded_content": _PROSE_TEXT}]
    results = asyncio.run(lede_extraction.extract_from_chunks_union(chunks, object(), None, None))
    assert len(results) == 1
    rel_types = {r.rel_type for r in results[0].relationships}
    # typed LLM edge AND deterministic co-occurrence net both present
    assert "LIKES" in rel_types
    assert "RELATED_TO" in rel_types
    names = [e.name for e in results[0].entities]
    assert "Gumbo" in names and "gumbo" not in names  # casefold union
    assert "Bayou Belle" in names  # deterministic leg contributed
