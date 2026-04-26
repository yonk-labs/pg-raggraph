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
            assert set(report["best"]["weights"].keys()) == {"w_sem", "w_bm25"}
            # Config was updated
            assert rag.config.w_sem == report["best"]["weights"]["w_sem"]
            assert rag.config.w_bm25 == report["best"]["weights"]["w_bm25"]
        finally:
            os.unlink(f1)
            os.unlink(f2)
    finally:
        await rag.close()


async def test_tune_scoring_weights_write_back_false_restores_config():
    """write_back=False must leave rag.config exactly as it was before."""
    import os
    import tempfile

    rag = GraphRAG(
        dsn=DSN, namespace="test_tune_nowrite", llm_base_url="http://localhost:99999/v1"
    )
    await rag.connect()
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Doc\n\nThe color of the sky is blue.\n")
            p = f.name
        try:
            await rag.delete("test_tune_nowrite")
            await rag.ingest([p], namespace="test_tune_nowrite")
            before_w_sem = rag.config.w_sem
            before_w_bm25 = rag.config.w_bm25
            gold = [{"question": "What color is the sky?", "expected_substring": "blue"}]
            await rag.tune_scoring_weights(
                namespace="test_tune_nowrite",
                gold=gold,
                grid={"w_sem": [0.1, 0.9], "w_bm25": [0.05, 0.5]},
                mode="naive",
                write_back=False,
            )
            assert rag.config.w_sem == before_w_sem, "w_sem must be restored"
            assert rag.config.w_bm25 == before_w_bm25, "w_bm25 must be restored"
        finally:
            os.unlink(p)
    finally:
        await rag.close()


async def test_tune_scoring_weights_unknown_weight_raises():
    """Typo'd weight name must fail loudly, not silently create a new attribute."""
    rag = GraphRAG(dsn=DSN, namespace="test_tune_typo", llm_base_url="http://localhost:99999/v1")
    await rag.connect()
    try:
        with pytest.raises(ValueError, match="Unknown weight names"):
            await rag.tune_scoring_weights(
                namespace="test_tune_typo",
                gold=[{"question": "x", "expected_substring": "y"}],
                grid={"w_seam": [0.1]},  # typo
                mode="naive",
            )
    finally:
        await rag.close()


async def test_tune_scoring_weights_restores_config_on_query_failure():
    """If rag.query raises mid-grid, rag.config must be restored to the pre-call snapshot."""
    rag = GraphRAG(dsn=DSN, namespace="test_tune_fail", llm_base_url="http://localhost:99999/v1")
    await rag.connect()
    try:
        before_w_sem = rag.config.w_sem
        before_w_bm25 = rag.config.w_bm25

        async def failing_query(*args, **kwargs):
            raise RuntimeError("simulated retrieval failure")

        rag.query = failing_query
        gold = [{"question": "q", "expected_substring": "s"}]
        with pytest.raises(RuntimeError, match="simulated retrieval failure"):
            await rag.tune_scoring_weights(
                namespace="test_tune_fail",
                gold=gold,
                grid={"w_sem": [0.42], "w_bm25": [0.42]},
                mode="naive",
                write_back=True,
            )
        assert rag.config.w_sem == before_w_sem, "w_sem must be restored after exception"
        assert rag.config.w_bm25 == before_w_bm25, "w_bm25 must be restored after exception"
    finally:
        await rag.close()
