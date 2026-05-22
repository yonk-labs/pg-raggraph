"""Unit tests for retrieval-term expansion (SC-101..106)."""

from __future__ import annotations

from pg_raggraph import summary as summary_mod
from pg_raggraph.config import PGRGConfig
from pg_raggraph.retrieval import _to_or_tsquery


def test_expansion_off_returns_empty_without_alias():
    cfg = PGRGConfig(retrieval_expansion="off")
    assert summary_mod.expand_query_terms("how do counties work?", cfg) == []


def test_alias_map_applies_even_when_expansion_off():
    cfg = PGRGConfig(
        retrieval_expansion="off",
        retrieval_alias_map={"Brooklyn": ["Kings County"]},
    )
    terms = summary_mod.expand_query_terms("What is happening in Brooklyn?", cfg)
    assert "kings county" in terms  # SC-106: alias injected, lowercased


def test_alias_map_word_boundary():
    cfg = PGRGConfig(retrieval_alias_map={"york": ["alias_hit"]})
    assert "alias_hit" in summary_mod.expand_query_terms("New York news", cfg)
    assert "alias_hit" not in summary_mod.expand_query_terms("yorkshire pudding", cfg)


def test_lexical_expansion_is_deterministic_and_capped():
    cfg = PGRGConfig(retrieval_expansion="moderate", max_hints=5)
    q = "automobile insurance policy renewal claims"
    t1 = summary_mod.expand_query_terms(q, cfg)
    t2 = summary_mod.expand_query_terms(q, cfg)
    assert t1 == t2
    assert len(t1) <= 5


def test_expand_query_terms_never_raises_on_empty():
    cfg = PGRGConfig(retrieval_expansion="moderate")
    assert summary_mod.expand_query_terms("", cfg) == []


def test_tsquery_byte_identical_without_extra_terms():
    # SC-101: extra_terms=None path must equal the historical behavior.
    assert _to_or_tsquery("payment service outage") == "payment | service | outage"
    assert _to_or_tsquery("a an") == "empty"  # all <=2 chars filtered (len > 2 rule)


def test_tsquery_includes_extra_terms_deduped():
    q = _to_or_tsquery("brooklyn news", extra_terms=["kings county", "brooklyn"])
    parts = q.split(" | ")
    assert "brooklyn" in parts and "kings" in parts and "county" in parts
    assert parts.count("brooklyn") == 1  # SC-102: deduped
