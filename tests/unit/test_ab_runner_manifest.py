"""SC-013: manifest.json lists every output file with the locked fields."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import pg_raggraph
from pg_raggraph.ab_gate import GoldQuestion
from pg_raggraph.ab_gate.io import ABRunnerOutput
from pg_raggraph.ab_gate.runner import run_ab_matrix


@pytest.mark.asyncio
async def test_manifest_lists_every_output(tmp_path: Path):
    rag = MagicMock()
    with patch(
        "pg_raggraph.ab_gate.runner.run_harness_mode",
        new=AsyncMock(
            side_effect=lambda rag, **kw: ABRunnerOutput(
                corpus_id=kw["corpus_id"], mode=kw["mode"], results=[]
            )
        ),
    ):
        await run_ab_matrix(
            rag,
            corpora=["alpha", "beta"],
            modes=["naive_vector", "graph_leg"],
            gold_questions_per_corpus={
                "alpha": [GoldQuestion(id="q1", question="?")],
                "beta": [GoldQuestion(id="q1", question="?")],
            },
            output_dir=tmp_path,
            top_k=10,
        )
    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists(), "expected manifest.json at output root"
    manifest = json.loads(manifest_path.read_text())
    assert "run_started_at" in manifest
    assert "run_ended_at" in manifest
    assert manifest["pg_raggraph_version"] == pg_raggraph.__version__
    files = manifest["files"]
    assert isinstance(files, list)
    assert len(files) == 4, f"expected 4 entries (2 corpora × 2 modes); got {len(files)}"
    for entry in files:
        assert set(entry.keys()) >= {"corpus", "mode", "path", "question_count"}
    pairs = {(e["corpus"], e["mode"]) for e in files}
    assert pairs == {
        ("alpha", "naive_vector"),
        ("alpha", "graph_leg"),
        ("beta", "naive_vector"),
        ("beta", "graph_leg"),
    }
