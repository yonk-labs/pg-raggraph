"""Runner schema test -- uses mocked engines, no DB or OpenAI needed."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from age_bakeoff.config import BakeoffConfig
from age_bakeoff.engines.base import EngineInfo, RetrievalResponse
from age_bakeoff.questions.schema import load_question_set
from age_bakeoff.runner import Runner, RunnerOptions


def _mock_engine(name="mock"):
    eng = MagicMock()
    eng.info.return_value = EngineInfo(
        name=name,
        embedding_model="BAAI/bge-small-en-v1.5",
        answer_model="gpt-5-mini",
        top_k=10,
        hop_budget=2,
    )
    eng.ingest = AsyncMock()
    eng.retrieve = AsyncMock(
        return_value=RetrievalResponse(
            retrieved_chunk_ids=["c::0"],
            retrieved_chunk_contents=["content"],
            retrieval_ms=5.0,
        )
    )
    eng.generate_answer = AsyncMock(return_value=("The answer.", 100.0))
    return eng


async def test_runner_output_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = BakeoffConfig()
    engines = {"pgrg": _mock_engine("pgrg"), "age": _mock_engine("age")}
    runner = Runner(
        config=cfg,
        engines=engines,
        options=RunnerOptions(runs_per_question=1, output_dir=tmp_path),
    )
    fixtures = Path(__file__).parent / "fixtures"
    qset = load_question_set(fixtures / "tiny_questions.yaml", strict=False)
    results = await runner.run_corpus("parity", qset)
    assert len(results) == 4  # 2 questions x 2 engines x 1 run
    for r in results:
        assert r.retrieval_ms >= 0
        assert r.generated_answer
    out_file = tmp_path / "parity.json"
    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert len(data) == 4


async def test_runner_handles_engine_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = BakeoffConfig()
    bad_engine = _mock_engine("bad")
    bad_engine.retrieve = AsyncMock(side_effect=RuntimeError("boom"))
    engines = {"bad": bad_engine}
    runner = Runner(
        config=cfg,
        engines=engines,
        options=RunnerOptions(runs_per_question=1, output_dir=tmp_path),
    )
    fixtures = Path(__file__).parent / "fixtures"
    qset = load_question_set(fixtures / "tiny_questions.yaml", strict=False)
    results = await runner.run_corpus("parity", qset)
    assert len(results) == 2
    for r in results:
        assert r.error == "boom"
        assert r.retrieval_ms == -1.0


def test_verify_symmetry_mismatch(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = BakeoffConfig()
    e1 = _mock_engine("a")
    e2 = _mock_engine("b")
    e2.info.return_value = EngineInfo(
        name="b",
        embedding_model="different-model",
        answer_model="gpt-5-mini",
        top_k=10,
        hop_budget=2,
    )
    runner = Runner(
        config=cfg,
        engines={"a": e1, "b": e2},
        options=RunnerOptions(output_dir=Path("/tmp/test")),
    )
    with pytest.raises(RuntimeError, match="Embedding model mismatch"):
        runner.verify_symmetry()


async def test_runner_writes_label_suffix_in_filename(tmp_path, monkeypatch):
    """RunnerOptions.label produces raw_dir/{corpus}__{label}.json filenames."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = BakeoffConfig()
    engines = {"stub": _mock_engine("stub")}
    opts = RunnerOptions(
        output_dir=tmp_path, runs_per_question=1, label="smart"
    )
    runner = Runner(config=cfg, engines=engines, options=opts)

    fixtures = Path(__file__).parent / "fixtures"
    qset = load_question_set(fixtures / "tiny_questions.yaml", strict=False)
    await runner.run_corpus("acme", qset)

    assert (tmp_path / "acme__smart.json").exists()
    assert not (tmp_path / "acme.json").exists()
