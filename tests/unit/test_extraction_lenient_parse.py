"""Lenient per-item extraction parsing (issue #69).

A single malformed item in the LLM's JSON (e.g. a relationship missing the
required ``target`` field) must NOT discard the whole chunk's extraction. Only
the malformed item should be dropped; valid entities and relationships survive.
"""

from __future__ import annotations

from pg_raggraph.extraction import _parse_extraction


def test_malformed_relationship_keeps_valid_items():
    """One relationship missing `target` drops only that edge, not the chunk."""
    parsed = {
        "entities": [
            {"name": "Alice", "entity_type": "person"},
            {"name": "Bob", "entity_type": "person"},
            {"name": "Acme", "entity_type": "org"},
        ],
        "relationships": [
            {"source": "Alice", "target": "Bob", "rel_type": "KNOWS"},
            {"source": "Alice", "rel_type": "WORKS_AT"},  # malformed: no target
            {"source": "Bob", "target": "Acme", "rel_type": "WORKS_AT"},
        ],
    }

    result = _parse_extraction(parsed)

    # All three entities are valid and survive.
    assert {e.name for e in result.entities} == {"Alice", "Bob", "Acme"}
    # The two well-formed relationships survive; the malformed one is skipped.
    pairs = {(r.source, r.target) for r in result.relationships}
    assert pairs == {("Alice", "Bob"), ("Bob", "Acme")}


def test_malformed_entity_skips_only_that_entity():
    """An entity missing the required `name` drops only that entity."""
    parsed = {
        "entities": [
            {"name": "Alice", "entity_type": "person"},
            {"entity_type": "person"},  # malformed: no name
            {"name": "Bob", "entity_type": "person"},
        ],
        "relationships": [
            {"source": "Alice", "target": "Bob", "rel_type": "KNOWS"},
        ],
    }

    result = _parse_extraction(parsed)

    assert {e.name for e in result.entities} == {"Alice", "Bob"}
    assert {(r.source, r.target) for r in result.relationships} == {("Alice", "Bob")}


def test_non_dict_json_returns_empty():
    """A non-object JSON payload (list, string) yields an empty result, not a crash."""
    assert _parse_extraction(["not", "a", "dict"]).entities == []
    assert _parse_extraction("nonsense").relationships == []


def test_missing_keys_returns_empty():
    """A dict without entities/relationships keys yields an empty result."""
    result = _parse_extraction({})
    assert result.entities == []
    assert result.relationships == []
