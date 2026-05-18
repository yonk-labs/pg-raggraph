import asyncio
import builtins

import pytest

from pg_raggraph import lede_extraction


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
    key = (
        ("NASA", "Saturn V")
        if ("NASA", "Saturn V") in by_pair
        else ("Saturn V", "NASA")
    )
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
            "embedded_content": (
                "NASA launched the Saturn V rocket. NASA and Saturn V again."
            ),
        },
        {"content": "", "embedded_content": ""},
    ]
    results = asyncio.run(
        lede_extraction.extract_from_chunks_lede(chunks, None, None, None)
    )
    assert len(results) == 2
    assert any(e.name == "NASA" for e in results[0].entities)
    assert results[1].entities == [] and results[1].relationships == []


from pg_raggraph.lede_extraction import select_extractor


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
