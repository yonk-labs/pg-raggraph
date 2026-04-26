"""Integration tests for rag.tune_scoring_weights()."""

from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def test_tune_scoring_weights_returns_best_cell_and_updates_config():
    rag = GraphRAG(dsn=DSN, namespace="test_tune", llm_base_url="http://localhost:99999/v1")
    await rag.connect()
    try:
        # Seed a small corpus with obvious relevance
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Q1\n\nThe answer to question one is apples.\n")
            f1 = f.name
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Q2\n\nThe answer to question two is bananas.\n")
            f2 = f.name
        try:
            await rag.delete("test_tune")
            await rag.ingest([f1, f2], namespace="test_tune")
            gold = [
                {"question": "What's the answer to question one?", "expected_substring": "apples"},
                {
                    "question": "What's the answer to question two?",
                    "expected_substring": "bananas",
                },
            ]
            report = await rag.tune_scoring_weights(
                namespace="test_tune",
                gold=gold,
                grid={
                    "w_sem": [0.3, 0.7],
                    "w_bm25": [0.1, 0.3],
                },
                mode="naive",
                write_back=True,
            )
            # Shape
            assert "best" in report
            assert report["best"]["score"] > 0
            assert set(report["best"]["weights"].keys()) >= {"w_sem", "w_bm25"}
            # Config was updated
            assert rag.config.w_sem == report["best"]["weights"]["w_sem"]
            assert rag.config.w_bm25 == report["best"]["weights"]["w_bm25"]
        finally:
            os.unlink(f1)
            os.unlink(f2)
    finally:
        await rag.close()
