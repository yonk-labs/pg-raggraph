"""SC-010: question-term encoder uses lede_spacy NER with fallback."""

import logging
from unittest.mock import patch

from pg_raggraph.ab_gate.harness import _encode_question_terms


def test_lede_spacy_path_returns_extracted_entities():
    """When lede_spacy returns entities, those are the encoded terms."""
    with patch(
        "pg_raggraph.ab_gate.harness._lede_spacy_entities",
        return_value=["Bostock", "Title VII"],
    ):
        terms = _encode_question_terms("What did Bostock say about Title VII?")
    assert terms == ["Bostock", "Title VII"]


def test_fallback_path_when_lede_spacy_raises(caplog):
    """When _lede_spacy_entities raises, fall back to whitespace + stoplist."""

    def boom(_text: str) -> list[str]:
        raise RuntimeError("lede_spacy not installed")

    with patch("pg_raggraph.ab_gate.harness._lede_spacy_entities", side_effect=boom):
        with caplog.at_level(logging.WARNING, logger="pg_raggraph.ab_gate.harness"):
            terms = _encode_question_terms("What did Bostock say about Title VII?")
    # Stopwords ('what', 'did', 'say', 'about') gone; content words preserved.
    assert "Bostock" in terms
    assert "Title" in terms
    # Should have logged the fallback.
    assert any("lede_spacy" in rec.message.lower() for rec in caplog.records)


def test_fallback_dedupes_case_insensitively():
    def boom(_text: str) -> list[str]:
        raise RuntimeError("force fallback")

    with patch("pg_raggraph.ab_gate.harness._lede_spacy_entities", side_effect=boom):
        terms = _encode_question_terms("apple Apple APPLE")
    # Fallback dedupes — same surface in different cases collapses.
    assert len(terms) == 1
    assert terms[0].lower() == "apple"


def test_empty_question_returns_empty_list():
    terms = _encode_question_terms("")
    assert terms == []


def test_lede_spacy_empty_returns_falls_through_to_fallback():
    """If lede_spacy returns [] (no entities), use the fallback so graph_leg
    still has surfaces to resolve."""
    with patch(
        "pg_raggraph.ab_gate.harness._lede_spacy_entities",
        return_value=[],
    ):
        terms = _encode_question_terms("Bostock cited Title VII.")
    # Fallback fires; 'Bostock' / 'Title' / 'VII' make it through.
    assert "Bostock" in terms
