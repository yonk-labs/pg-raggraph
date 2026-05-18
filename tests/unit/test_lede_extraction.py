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
