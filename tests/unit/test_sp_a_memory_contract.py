"""SP-A `agent_memory.memory` column contract test (#4 SP-B bridge).

Mirrors chunkshop's `test_pgraggraph_contract_columns_present` (their
side asserts the table HAS these columns; we assert our bridge READS
this set). Drift on either side fails CI on both sides — the column set
is the contract between SP-A (writer) and SP-B (reader).

Reference: chunkshop SP-A design spec
``docs/superpowers/specs/2026-05-19-chunkshop-memory-primitives-sp-a-design.md``
"""

from __future__ import annotations

from pg_raggraph.memory_bridge import SP_A_MEMORY_COLUMNS

# The published SP-A v1 contract. If chunkshop adds a column,
# pg-raggraph's bridge can choose to read it (and this set grows); if
# chunkshop renames or drops a column, this test fails before the bridge
# silently breaks at runtime.
EXPECTED_SP_A_COLUMNS = frozenset({
    # Identity / classification
    "session_id",
    "tier",  # 'provisional' | 'consolidated'
    "kind",  # 'episode' | 'fact'
    # Episode payload (chunkshop-canonical pgvector shape)
    "doc_id",
    "seq_num",
    "original_content",
    "embedded_content",
    "embedding",
    "metadata",  # jsonb; carries session_id, namespace, tier, recorded_at
    # Fact payload — SPO triple + provenance (only populated when kind='fact')
    "subject",
    "predicate",
    "object",
    "support_span",
    "confidence",  # SP-A promotes as text; bridge parses to float
    "source_chunk_seq",  # parent episode pointer for facts (int)
    # Bi-temporal — episode and fact rows
    "effective_from",
    "effective_to",
    # Soft-invalidation — fact rows
    "retracted",
    "retracted_at",
    # Provenance
    "extractor",
    "namespace",
    "recorded_at",
})


def test_bridge_contract_matches_sp_a_published_columns():
    """The bridge's source-of-truth column set must equal SP-A's spec.

    Failure modes this catches:
    - chunkshop renamed a column → bridge breaks silently → this test fails
    - bridge module drops a column from SP_A_MEMORY_COLUMNS → contract
      narrowed without an explicit SP-A spec change → this test fails
    """
    assert SP_A_MEMORY_COLUMNS == EXPECTED_SP_A_COLUMNS


def test_bridge_columns_are_lowercase_identifiers():
    """SP-A spec uses lowercase identifiers; catches a typo'd Title-Case col."""
    for col in SP_A_MEMORY_COLUMNS:
        assert col == col.lower(), f"SP-A column {col!r} should be lowercase"
        assert col.replace("_", "a").isalnum(), (
            f"SP-A column {col!r} should be a simple identifier"
        )


def test_required_discriminators_present():
    """`tier` and `kind` are SP-A's discriminator columns; bridge cannot omit."""
    assert "tier" in SP_A_MEMORY_COLUMNS
    assert "kind" in SP_A_MEMORY_COLUMNS


def test_bitemporal_columns_present():
    """SP-A's bi-temporal contract requires effective_from/effective_to and
    retracted/retracted_at. Missing any of these breaks O8 (time semantics)."""
    for col in ("effective_from", "effective_to", "retracted", "retracted_at"):
        assert col in SP_A_MEMORY_COLUMNS


def test_episode_payload_columns_present():
    """Episode rows go through pg-raggraph's `pre_chunked` seam, which
    requires content + embedding at minimum. Bridge must read both."""
    for col in ("original_content", "embedded_content", "embedding"):
        assert col in SP_A_MEMORY_COLUMNS


def test_fact_payload_columns_present():
    """Fact rows feed pg-raggraph's `relationships=` seam via SPO mapping.
    Bridge must read subject/predicate/object + support_span for provenance."""
    for col in ("subject", "predicate", "object", "support_span"):
        assert col in SP_A_MEMORY_COLUMNS
