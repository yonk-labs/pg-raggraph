"""SC-011: run_ab_matrix calls run_harness_mode once per (corpus, mode) cell."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pg_raggraph.ab_gate import GoldQuestion
from pg_raggraph.ab_gate.io import ABRunnerOutput
from pg_raggraph.ab_gate.runner import run_ab_matrix


@pytest.mark.asyncio
async def test_call_count_matches_corpora_x_modes(tmp_path: Path):
    """corpora=['A','B'] × modes=['m1','m2','m3'] ⇒ 6 harness calls."""
    rag = MagicMock()

    def make_output(corpus_id, mode, **_):
        return ABRunnerOutput(corpus_id=corpus_id, mode=mode, results=[])

    with patch(
        "pg_raggraph.ab_gate.runner.run_harness_mode",
        new=AsyncMock(side_effect=lambda rag, **kw: make_output(kw["corpus_id"], kw["mode"])),
    ) as mock_harness:
        gold = {
            "A": [GoldQuestion(id="q1", question="?")],
            "B": [GoldQuestion(id="q2", question="?")],
        }
        await run_ab_matrix(
            rag,
            corpora=["A", "B"],
            modes=["naive_vector", "graph_leg", "hybrid"],  # type: ignore[list-item]
            gold_questions_per_corpus=gold,
            output_dir=tmp_path,
            top_k=10,
        )
        assert mock_harness.await_count == 6, (
            f"expected 2 corpora × 3 modes = 6 harness calls; got {mock_harness.await_count}"
        )


@pytest.mark.asyncio
async def test_return_value_maps_pair_to_output_path(tmp_path: Path):
    """Returns dict[(corpus, mode), Path]."""
    rag = MagicMock()
    with patch(
        "pg_raggraph.ab_gate.runner.run_harness_mode",
        new=AsyncMock(
            side_effect=lambda rag, **kw: ABRunnerOutput(
                corpus_id=kw["corpus_id"], mode=kw["mode"], results=[]
            )
        ),
    ):
        paths = await run_ab_matrix(
            rag,
            corpora=["foo"],
            modes=["naive_vector"],
            gold_questions_per_corpus={"foo": [GoldQuestion(id="q1", question="?")]},
            output_dir=tmp_path,
            top_k=10,
        )
    assert set(paths.keys()) == {("foo", "naive_vector")}
    p = paths[("foo", "naive_vector")]
    assert p.name == "foo__naive_vector.json"
    assert p.parent == tmp_path
