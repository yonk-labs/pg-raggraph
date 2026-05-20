"""Tests for structured per-namespace metric events."""

import logging

import pytest

pytestmark = pytest.mark.integration


class TinyEmbedder:
    @property
    def dimension(self) -> int:
        return 384

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.02] * self.dimension for _ in texts]


async def test_ingest_and_query_emit_namespace_metric_events(scale_rag, caplog):
    scale_rag._embedder = TinyEmbedder()
    caplog.set_level(logging.INFO, logger="pg_raggraph.metrics")

    await scale_rag.ingest_records(
        [{"text": "K7 metric events alpha beta gamma.", "source_id": "scale_k7_doc"}],
        namespace="scale_k7",
    )

    ingest_metrics = [
        rec for rec in caplog.records if getattr(rec, "event", None) == "pgrg.ingest"
    ]
    assert len(ingest_metrics) == 1
    assert ingest_metrics[0].namespace == "scale_k7"
    assert ingest_metrics[0].mode == "records"
    assert ingest_metrics[0].latency_ms >= 0
    assert ingest_metrics[0].ingested == 1

    caplog.clear()
    await scale_rag.query("alpha beta?", mode="naive", namespace="scale_k7")

    query_metrics = [rec for rec in caplog.records if getattr(rec, "event", None) == "pgrg.query"]
    assert len(query_metrics) == 1
    assert query_metrics[0].namespace == "scale_k7"
    assert query_metrics[0].mode == "naive"
    assert query_metrics[0].latency_ms >= 0
    assert isinstance(query_metrics[0].top_k, int)
