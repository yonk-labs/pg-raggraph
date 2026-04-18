"""Tests for report aggregation and generation."""
from __future__ import annotations

import pytest
from age_bakeoff.models import QuestionClass, RunResult
from age_bakeoff.report.aggregate import (
    group_by_engine,
    group_by_engine_and_class,
    latency_percentiles,
)
from age_bakeoff.report.generator import generate_report
from age_bakeoff.scorers.llm_judge import JudgeVerdict


def _result(
    engine="pgrg",
    corpus="test",
    question_id="q1",
    retrieval_ms=10.0,
    answer_ms=100.0,
):
    return RunResult(
        engine=engine,
        corpus=corpus,
        question_id=question_id,
        run_number=1,
        cold=True,
        retrieval_ms=retrieval_ms,
        answer_ms=answer_ms,
        retrieved_chunk_ids=["c1"],
        generated_answer="answer",
    )


def test_latency_percentiles():
    results = [_result(retrieval_ms=i * 10.0) for i in range(1, 11)]
    p = latency_percentiles(results)
    assert p["p50"] == pytest.approx(55.0, abs=1.0)
    assert p["mean"] == pytest.approx(55.0)
    assert p["n"] == 10


def test_latency_percentiles_empty():
    p = latency_percentiles([])
    assert p["n"] == 0
    assert p["p50"] == 0.0


def test_latency_skips_negative():
    results = [_result(retrieval_ms=-1.0), _result(retrieval_ms=50.0)]
    p = latency_percentiles(results)
    assert p["n"] == 1
    assert p["mean"] == 50.0


def test_group_by_engine():
    results = [
        _result(engine="pgrg"),
        _result(engine="age"),
        _result(engine="pgrg"),
    ]
    grouped = group_by_engine(results)
    assert len(grouped["pgrg"]) == 2
    assert len(grouped["age"]) == 1


def test_group_by_engine_and_class():
    results = [
        _result(engine="pgrg", question_id="q1"),
        _result(engine="pgrg", question_id="q2"),
        _result(engine="age", question_id="q1"),
    ]
    qc = {
        "q1": QuestionClass.factual,
        "q2": QuestionClass.multi_hop_bridging,
    }
    grouped = group_by_engine_and_class(results, qc)
    assert QuestionClass.factual in grouped["pgrg"]
    assert QuestionClass.multi_hop_bridging in grouped["pgrg"]
    assert len(grouped["pgrg"][QuestionClass.factual]) == 1


def test_generate_report_basic():
    results = [
        _result(engine="pgrg", corpus="acme", retrieval_ms=10.0),
        _result(engine="age", corpus="acme", retrieval_ms=15.0),
    ]
    report = generate_report({"acme": results})
    assert "# AGE vs pg-raggraph Bake-off Report" in report
    assert "acme" in report
    assert "pgrg" in report
    assert "age" in report
    assert "Retrieval Latency" in report


def test_generate_report_with_fact_recall():
    results = [
        _result(engine="pgrg", corpus="acme"),
        _result(engine="age", corpus="acme"),
    ]
    fact_recall = {
        "acme": {
            "pgrg": {"q1": 1.0},
            "age": {"q1": 0.5},
        }
    }
    report = generate_report({"acme": results}, fact_recall_by_corpus=fact_recall)
    assert "Fact Recall" in report
    assert "1.000" in report
    assert "0.500" in report


def test_generate_report_with_judge():
    results = [_result(engine="pgrg", corpus="acme")]
    judge = {
        "acme": {
            "pgrg": {"q1": JudgeVerdict.fully_correct},
        }
    }
    report = generate_report(
        {"acme": results}, judge_by_corpus=judge
    )
    assert "LLM Judge" in report
    assert "Fully Correct" in report


def test_generate_report_writes_file(tmp_path):
    results = [_result(engine="pgrg", corpus="acme")]
    out = tmp_path / "REPORT.md"
    report = generate_report({"acme": results}, output_path=out)
    assert out.exists()
    assert out.read_text() == report


def test_where_age_wins_section():
    results = [
        _result(engine="pgrg", corpus="acme", retrieval_ms=50.0),
        _result(engine="age", corpus="acme", retrieval_ms=10.0),
    ]
    report = generate_report({"acme": results})
    assert "Where AGE Wins" in report
    assert "faster" in report


def test_report_includes_fact_recall_and_per_class_when_provided():
    from age_bakeoff.models import QuestionClass, RunResult
    from age_bakeoff.report.generator import generate_report

    results = [
        RunResult(engine="pgrg", corpus="acme", question_id="q1", run_number=1,
                  cold=True, retrieval_ms=20.0, answer_ms=100.0,
                  retrieved_chunk_ids=["a::1"], generated_answer="x"),
        RunResult(engine="age", corpus="acme", question_id="q1", run_number=1,
                  cold=True, retrieval_ms=40.0, answer_ms=110.0,
                  retrieved_chunk_ids=["a::1"], generated_answer="y"),
    ]
    md = generate_report(
        results_by_corpus={"acme": results},
        fact_recall_by_corpus={"acme": {"pgrg": {"q1": 1.0}, "age": {"q1": 0.5}}},
        question_classes={"acme": {"q1": QuestionClass.multi_hop_bridging}},
    )
    assert "### Fact Recall" in md
    assert "### Per-Question-Class Latency Breakdown" in md
    assert "multi_hop_bridging" in md


def test_report_cli_computes_fact_recall_from_raw_and_questions(tmp_path, monkeypatch):
    """CLI report command computes fact recall from retrieved_chunk_contents + gold required_facts."""
    import json

    from age_bakeoff import cli as cli_module
    from click.testing import CliRunner

    # Build a fixture tree mirroring what the CLI expects.
    results_dir = tmp_path / "results"
    raw_dir = results_dir / "raw"
    raw_dir.mkdir(parents=True)
    questions_dir = tmp_path / "questions"
    questions_dir.mkdir()

    # Minimal 2-question YAML (loose-mode parse, since <30 questions).
    questions_yaml = """\
corpus: tiny
questions:
  - id: tiny-q-001
    question: "What is Alpha?"
    gold_answer: "Alpha is a core concept."
    required_facts: ["Alpha"]
    required_entities: ["alpha"]
    question_class: single_hop
  - id: tiny-q-002
    question: "How does Beta relate to Gamma?"
    gold_answer: "Beta relates to Gamma through association."
    required_facts: ["Beta", "Gamma"]
    required_entities: ["beta", "gamma"]
    question_class: multi_hop_bridging
"""
    (questions_dir / "tiny.yaml").write_text(questions_yaml)

    # Raw results: pgrg retrieves chunks covering both facts; age misses Gamma.
    raw_payload = [
        {
            "engine": "pgrg",
            "corpus": "tiny",
            "question_id": "tiny-q-001",
            "run_number": 1,
            "cold": True,
            "retrieval_ms": 20.0,
            "answer_ms": 100.0,
            "retrieved_chunk_ids": ["c1"],
            "retrieved_chunk_contents": ["Alpha is the first concept."],
            "generated_answer": "Alpha answer",
            "error": None,
        },
        {
            "engine": "pgrg",
            "corpus": "tiny",
            "question_id": "tiny-q-002",
            "run_number": 1,
            "cold": True,
            "retrieval_ms": 22.0,
            "answer_ms": 105.0,
            "retrieved_chunk_ids": ["c2"],
            "retrieved_chunk_contents": ["Beta connects to Gamma via bridge."],
            "generated_answer": "Beta-Gamma answer",
            "error": None,
        },
        {
            "engine": "age",
            "corpus": "tiny",
            "question_id": "tiny-q-001",
            "run_number": 1,
            "cold": True,
            "retrieval_ms": 40.0,
            "answer_ms": 110.0,
            "retrieved_chunk_ids": ["c1"],
            "retrieved_chunk_contents": ["Alpha is the first concept."],
            "generated_answer": "Alpha answer age",
            "error": None,
        },
        {
            "engine": "age",
            "corpus": "tiny",
            "question_id": "tiny-q-002",
            "run_number": 1,
            "cold": True,
            "retrieval_ms": 44.0,
            "answer_ms": 115.0,
            "retrieved_chunk_ids": ["c2"],
            # Only covers Beta, not Gamma -> recall 0.5
            "retrieved_chunk_contents": ["Beta stands alone."],
            "generated_answer": "Beta answer age",
            "error": None,
        },
    ]
    (raw_dir / "tiny.json").write_text(json.dumps(raw_payload, indent=2))

    # Point the CLI's module-level dirs at tmp_path.
    monkeypatch.setattr(cli_module, "_RESULTS_DIR", results_dir)
    monkeypatch.setattr(cli_module, "_QUESTIONS_DIR", questions_dir)

    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["report"])
    assert result.exit_code == 0, result.output

    out_path = results_dir / "REPORT.md"
    assert out_path.exists()
    md = out_path.read_text()
    assert "### Fact Recall" in md
    assert "### Per-Question-Class Latency Breakdown" in md
    assert "multi_hop_bridging" in md
    # pgrg covers 100% of facts on both questions -> mean 1.000
    assert "1.000" in md
    # age covers Alpha fully (1.0) and Beta/Gamma partially (0.5) -> min 0.500
    assert "0.500" in md


def test_report_cli_scores_zero_retrieval_when_schema_current(tmp_path, monkeypatch):
    """Current-schema rows with retrieved_chunk_contents=[] score 0.0, not skipped.

    Pins Fix 1: the legacy-vs-zero-retrieval distinction happens at JSON load
    time (by checking whether the key exists in the raw dict), not at scoring
    time. An engine that legitimately retrieved no chunks for a question must
    receive a 0.0 fact-recall score — silently excluding it biases the result.
    """
    import json

    from age_bakeoff import cli as cli_module
    from click.testing import CliRunner

    results_dir = tmp_path / "results"
    raw_dir = results_dir / "raw"
    raw_dir.mkdir(parents=True)
    questions_dir = tmp_path / "questions"
    questions_dir.mkdir()

    (questions_dir / "zero.yaml").write_text(
        """\
corpus: zero
questions:
  - id: zero-q-001
    question: "What is Alpha?"
    gold_answer: "Alpha is first."
    required_facts: ["Alpha"]
    required_entities: ["alpha"]
    question_class: single_hop
"""
    )

    # Key IS present (current schema) but the list is empty -- real zero-retrieval.
    zero_payload = [
        {
            "engine": "pgrg",
            "corpus": "zero",
            "question_id": "zero-q-001",
            "run_number": 1,
            "cold": True,
            "retrieval_ms": 20.0,
            "answer_ms": 100.0,
            "retrieved_chunk_ids": [],
            "retrieved_chunk_contents": [],
            "generated_answer": "no context",
            "error": None,
        },
        {
            "engine": "age",
            "corpus": "zero",
            "question_id": "zero-q-001",
            "run_number": 1,
            "cold": True,
            "retrieval_ms": 40.0,
            "answer_ms": 110.0,
            "retrieved_chunk_ids": ["c1"],
            "retrieved_chunk_contents": ["Alpha is the first concept."],
            "generated_answer": "Alpha answer",
            "error": None,
        },
    ]
    (raw_dir / "zero.json").write_text(json.dumps(zero_payload, indent=2))

    monkeypatch.setattr(cli_module, "_RESULTS_DIR", results_dir)
    monkeypatch.setattr(cli_module, "_QUESTIONS_DIR", questions_dir)

    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["report"])
    assert result.exit_code == 0, result.output
    # No legacy-skip warning -- schema is current.
    assert "Fact recall skipped" not in result.output

    out_path = results_dir / "REPORT.md"
    md = out_path.read_text()
    assert "### Fact Recall" in md
    # pgrg had no retrieval -> 0.000; age covered Alpha -> 1.000
    assert "0.000" in md
    assert "1.000" in md


def test_report_cli_warns_when_legacy_raw_json_skips_fact_recall(tmp_path, monkeypatch):
    """Fix 2: emit a click warning when legacy raw JSON causes a skip."""
    import json

    from age_bakeoff import cli as cli_module
    from click.testing import CliRunner

    results_dir = tmp_path / "results"
    raw_dir = results_dir / "raw"
    raw_dir.mkdir(parents=True)
    questions_dir = tmp_path / "questions"
    questions_dir.mkdir()

    (questions_dir / "legacywarn.yaml").write_text(
        """\
corpus: legacywarn
questions:
  - id: legacywarn-q-001
    question: "What is Alpha?"
    gold_answer: "Alpha is first."
    required_facts: ["Alpha"]
    required_entities: ["alpha"]
    question_class: single_hop
"""
    )

    # Legacy rows: key absent entirely.
    legacy_payload = [
        {
            "engine": "pgrg",
            "corpus": "legacywarn",
            "question_id": "legacywarn-q-001",
            "run_number": 1,
            "cold": True,
            "retrieval_ms": 20.0,
            "answer_ms": 100.0,
            "retrieved_chunk_ids": ["c1"],
            "generated_answer": "ans",
            "error": None,
        },
    ]
    (raw_dir / "legacywarn.json").write_text(json.dumps(legacy_payload, indent=2))

    monkeypatch.setattr(cli_module, "_RESULTS_DIR", results_dir)
    monkeypatch.setattr(cli_module, "_QUESTIONS_DIR", questions_dir)

    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["report"])
    assert result.exit_code == 0, result.output
    assert "Fact recall skipped" in result.output
    assert "legacywarn" in result.output
    assert "Rerun `age-bakeoff run`" in result.output


def test_report_cli_skips_legacy_rows_without_chunk_contents(tmp_path, monkeypatch):
    """Legacy raw JSON rows (no retrieved_chunk_contents) should not crash or score 0."""
    import json

    from age_bakeoff import cli as cli_module
    from click.testing import CliRunner

    results_dir = tmp_path / "results"
    raw_dir = results_dir / "raw"
    raw_dir.mkdir(parents=True)
    questions_dir = tmp_path / "questions"
    questions_dir.mkdir()

    (questions_dir / "legacy.yaml").write_text(
        """\
corpus: legacy
questions:
  - id: legacy-q-001
    question: "What is Alpha?"
    gold_answer: "Alpha is first."
    required_facts: ["Alpha"]
    required_entities: ["alpha"]
    question_class: single_hop
"""
    )

    # Legacy row has NO retrieved_chunk_contents key -- model default kicks in.
    legacy_payload = [
        {
            "engine": "pgrg",
            "corpus": "legacy",
            "question_id": "legacy-q-001",
            "run_number": 1,
            "cold": True,
            "retrieval_ms": 20.0,
            "answer_ms": 100.0,
            "retrieved_chunk_ids": ["c1"],
            "generated_answer": "ans",
            "error": None,
        },
    ]
    (raw_dir / "legacy.json").write_text(json.dumps(legacy_payload, indent=2))

    monkeypatch.setattr(cli_module, "_RESULTS_DIR", results_dir)
    monkeypatch.setattr(cli_module, "_QUESTIONS_DIR", questions_dir)

    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["report"])
    assert result.exit_code == 0, result.output

    out_path = results_dir / "REPORT.md"
    assert out_path.exists()
    md = out_path.read_text()
    # Report still generates; no fact-recall section should appear for this corpus
    # (since all rows were skipped as legacy).
    assert "AGE vs pg-raggraph Bake-off Report" in md
