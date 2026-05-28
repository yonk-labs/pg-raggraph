"""Unit tests for the A/B runner output schema (SC-023)."""

import json


def test_runner_output_dataclasses_importable():
    from pg_raggraph.ab_gate import (  # noqa: F401
        ABCaseResult,
        ABRetrievedItem,
        ABRunnerOutput,
    )


def test_runner_output_round_trip():
    """SC-023: ABRunnerOutput round-trips through JSON without loss."""
    from pg_raggraph.ab_gate import ABCaseResult, ABRetrievedItem, ABRunnerOutput

    output = ABRunnerOutput(
        corpus_id="bakeoff-scotus-ab",
        mode="graph_leg",
        results=[
            ABCaseResult(
                question_id="scotus-q1",
                question="What does Marbury v. Madison establish?",
                gold_answer="Judicial review.",
                retrieved=[
                    ABRetrievedItem(
                        rank=1,
                        source="scotus:doc-1803-marbury",
                        score=0.91,
                        content_snippet=(
                            "It is emphatically the province and duty of the judicial "
                            "department to say what the law is."
                        ),
                    ),
                    ABRetrievedItem(
                        rank=2,
                        source="scotus:doc-1789-judiciary-act",
                        score=0.74,
                        content_snippet=(
                            "The Judiciary Act of 1789 created the federal court system."
                        ),
                    ),
                ],
                latency_ms=183.4,
            ),
        ],
    )

    raw = output.to_dict()
    blob = json.dumps(raw)
    restored = ABRunnerOutput.from_dict(json.loads(blob))

    assert restored == output


def test_runner_output_round_trip_missing_gold_answer():
    """ABCaseResult.gold_answer is Optional — None must round-trip."""
    from pg_raggraph.ab_gate import ABCaseResult, ABRunnerOutput

    output = ABRunnerOutput(
        corpus_id="bakeoff-ntsb-ab",
        mode="naive_vector",
        results=[
            ABCaseResult(
                question_id="ntsb-q5",
                question="What caused the crash of Flight 232?",
                gold_answer=None,
                retrieved=[],
                latency_ms=12.0,
            ),
        ],
    )

    restored = ABRunnerOutput.from_dict(json.loads(json.dumps(output.to_dict())))
    assert restored.results[0].gold_answer is None


def test_runner_output_rejects_unknown_mode_loosely():
    """Mode is a free string by the contract — caller decides which values are legal.

    The schema does not validate mode; #49 may emit hybrid/custom modes.
    """
    from pg_raggraph.ab_gate import ABRunnerOutput

    output = ABRunnerOutput(corpus_id="x", mode="weird-custom", results=[])
    # No error — the schema accepts any string.
    assert output.mode == "weird-custom"
