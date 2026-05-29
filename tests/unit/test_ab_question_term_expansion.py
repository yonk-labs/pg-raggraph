"""Query-term expansion for graph_leg (verdict-hardening).

lede_spacy NER returns full noun phrases ("Bostock v. Clayton County"), but the
materialized entity nodes are single surfaces ("Bostock", "Clayton County"). A
full-phrase term resolves to nothing, so graph_leg silently skipped questions
whose entities were multi-word. _expand_entity_terms emits both the full phrase
AND its component word-tokens so they resolve against the single-surface nodes.
"""

from __future__ import annotations

from pg_raggraph.ab_gate.harness import _expand_entity_terms


def test_expands_multiword_entity_into_components():
    terms = _expand_entity_terms(["Bostock v. Clayton County"])
    # Full phrase preserved (exact-match chance) + component words for resolution.
    assert "Bostock v. Clayton County" in terms
    assert "Bostock" in terms
    assert "Clayton" in terms
    assert "County" in terms


def test_drops_punctuation_and_single_char_joiners():
    terms = _expand_entity_terms(["Apple v. Pepper"])
    assert "Apple v. Pepper" in terms
    assert "Apple" in terms
    assert "Pepper" in terms
    # The citation joiner "v" (single char after punctuation strip) is dropped.
    assert "v" not in [t.lower() for t in terms]


def test_dedupes_case_insensitively_first_seen_wins():
    terms = _expand_entity_terms(["Apple", "apple", "APPLE Inc"])
    lows = [t.lower() for t in terms]
    assert lows.count("apple") == 1
    # "APPLE Inc" contributes "Inc" but "apple" is already seen.
    assert "Inc" in terms


def test_drops_stopwords():
    terms = _expand_entity_terms(["the Court of Appeals"])
    assert "the" not in [t.lower() for t in terms]
    assert "of" not in [t.lower() for t in terms]
    assert "Court" in terms
    assert "Appeals" in terms


def test_empty_input_empty_output():
    assert _expand_entity_terms([]) == []
    assert _expand_entity_terms(["", "  "]) == []
