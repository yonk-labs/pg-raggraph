"""Integration tests for the PRG-1..4 consumer surface."""

from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def _connect(**kwargs) -> GraphRAG:
    rag = GraphRAG(dsn=DSN, **kwargs)
    await rag.connect()
    return rag


async def test_prg1_metadata_round_trip_present():
    rag = await _connect(namespace="test_prg1_meta")
    try:
        await rag.delete("test_prg1_meta")
        await rag.ingest_records(
            [{"text": "Payment service outage on the checkout path.",
              "source_id": "doc:1", "metadata": {"k": "v", "stele_ref": "x://1"}}],
            namespace="test_prg1_meta",
        )
        res = await rag.query("payment outage", mode="naive", namespace="test_prg1_meta")
        assert res.chunks, "expected at least one hit"
        assert res.chunks[0].metadata == {"k": "v", "stele_ref": "x://1"}
    finally:
        await rag.delete("test_prg1_meta")
        await rag.close()


async def test_prg1_metadata_none_when_absent():
    rag = await _connect(namespace="test_prg1_nometa")
    try:
        await rag.delete("test_prg1_nometa")
        await rag.ingest_records(
            [{"text": "Payment service outage on the checkout path.",
              "source_id": "doc:1"}],
            namespace="test_prg1_nometa",
        )
        res = await rag.query("payment outage", mode="naive", namespace="test_prg1_nometa")
        assert res.chunks
        assert res.chunks[0].metadata is None


    finally:
        await rag.delete("test_prg1_nometa")
        await rag.close()


async def test_prg1_evolution_fields_none_when_tier_off():
    # Default evolution_tier == "off" (config.py:207).
    rag = await _connect(namespace="test_prg1_off")
    try:
        await rag.delete("test_prg1_off")
        await rag.ingest_records(
            [{"text": "Payment service outage.", "source_id": "doc:1",
              "metadata": {"k": "v"}}],
            namespace="test_prg1_off",
        )
        res = await rag.query("payment outage", mode="naive", namespace="test_prg1_off")
        assert res.chunks
        c = res.chunks[0]
        # metadata is tier-independent caller data — still returned
        assert c.metadata == {"k": "v"}
        # evolution fields are None when tier == "off" (DEC-5)
        assert c.retracted is None
        assert c.version_label is None
        assert c.effective_from is None
        assert c.effective_to is None
        assert c.superseded_by_id is None
    finally:
        await rag.delete("test_prg1_off")
        await rag.close()


async def test_prg1_retracted_true_under_flag():
    # evolution on + retracted_behavior="flag" (default): retracted docs still
    # surface, but chunk.retracted is True so the caller can act.
    rag = await _connect(
        namespace="test_prg1_flag",
        evolution_tier="structural",
        retracted_behavior="flag",
    )
    try:
        await rag.delete("test_prg1_flag")
        await rag.ingest_records(
            [{"text": "Deprecated API key rotation policy.",
              "source_id": "doc:1",
              "metadata": {"retracted": True, "retraction_reason": "obsolete"}}],
            namespace="test_prg1_flag",
        )
        res = await rag.query("API key rotation", mode="naive", namespace="test_prg1_flag")
        assert res.chunks
        assert res.chunks[0].retracted is True
    finally:
        await rag.delete("test_prg1_flag")
        await rag.close()
