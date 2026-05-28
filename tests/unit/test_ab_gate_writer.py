"""Unit tests for the A/B verdict writer (SC-009..SC-015)."""

import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ab_gate"


def test_threshold_constants_match_contract():
    """SC-011: the three thresholds match chunkshop contract §3.2 verbatim."""
    from pg_raggraph.ab_gate import writer

    assert writer.RECALL_AT_10_LIFT_PP == 5.0, (
        "chunkshop contract §3.2: recall@10 lift threshold is +5pp"
    )
    assert writer.MRR_DELTA == 0.05, "chunkshop contract §3.2: MRR delta threshold is +0.05"
    assert writer.JUDGE_WIN_RATE_DELTA == 0.10, (
        "chunkshop contract §3.2: LLM-judge win-rate delta threshold is +0.10"
    )


def _load_premeasured(path: Path) -> dict:
    """Helper: read a fixture and return its 'premeasured_metrics' block."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["premeasured_metrics"]


def test_worked_example_inconclusive():
    """SC-010: §3.7 worked-example fixture → INCONCLUSIVE."""
    from pg_raggraph.ab_gate import compute_verdict

    fixture = _load_premeasured(FIXTURE_DIR / "runner_output_worked_example.json")
    verdict = compute_verdict.from_premeasured(fixture)

    assert verdict.label == "INCONCLUSIVE", (
        f"§3.7 worked example must produce INCONCLUSIVE; got {verdict.label}"
    )

    expected_labels = fixture["expected_metric_labels"]
    assert verdict.combined is not None
    assert verdict.combined.recall_at_10.label == expected_labels["recall_at_10"]
    assert verdict.combined.mrr.label == expected_labels["mrr"]
    assert verdict.combined.judge_win_rate.label == expected_labels["judge_win_rate"]


def test_compute_verdict_returns_dataclass_round_trip():
    """SC-009 + SC-013: ABVerdict serializes round-trip through JSON."""
    from pg_raggraph.ab_gate import compute_verdict

    fixture = _load_premeasured(FIXTURE_DIR / "runner_output_worked_example.json")
    verdict = compute_verdict.from_premeasured(fixture)

    blob = json.dumps(verdict.to_dict())
    restored_dict = json.loads(blob)

    # Round-trip equality at the dict level (ABVerdict has nested dataclasses
    # that asdict() converts to dicts — the equality check is on the dict form).
    assert restored_dict == verdict.to_dict()
    assert restored_dict["label"] == "INCONCLUSIVE"


def test_per_corpus_asymmetry_overrides_combined_win():
    """SC-012: combined GRAPH_WINS but graph loses 3-0 on one corpus → INCONCLUSIVE."""
    from pg_raggraph.ab_gate import compute_verdict

    fixture = _load_premeasured(FIXTURE_DIR / "runner_output_asymmetric.json")
    verdict = compute_verdict.from_premeasured(fixture)

    assert verdict.label == "INCONCLUSIVE", (
        f"§3.4 asymmetry guard must downgrade GRAPH_WINS to INCONCLUSIVE "
        f"when graph loses 3-0 on one corpus; got {verdict.label}"
    )
    # Sanity: at least one per-corpus rollup should show graph losing all three.
    losing_rollups = [
        r
        for r in verdict.per_corpus
        if r.recall_at_10.label == "NAIVE_WINS"
        and r.mrr.label == "NAIVE_WINS"
        and r.judge_win_rate.label == "NAIVE_WINS"
    ]
    assert len(losing_rollups) == 1, (
        f"asymmetric fixture must have exactly one corpus where graph loses all 3 "
        f"metrics; got {len(losing_rollups)}"
    )


import re  # noqa: E402


def test_markdown_output_has_required_sections(tmp_path):
    """SC-014: verdict.md mirrors §3.7's worked-example structure."""
    from pg_raggraph.ab_gate import compute_verdict, write_verdict_report

    fixture = _load_premeasured(FIXTURE_DIR / "runner_output_worked_example.json")
    verdict = compute_verdict.from_premeasured(fixture)

    write_verdict_report(verdict, out_dir=tmp_path, latency_rows=[])

    md = (tmp_path / "verdict.md").read_text(encoding="utf-8")

    required_headers = [
        r"^#\s+A/B Gate Verdict",
        r"^##\s+Inputs",
        r"^##\s+Per-metric deltas",
        r"^##\s+Per-corpus breakdown",
        r"^##\s+Verdict computation walkthrough",
        r"^##\s+Final verdict",
    ]
    for pattern in required_headers:
        assert re.search(pattern, md, re.MULTILINE), (
            f"verdict.md is missing header matching {pattern!r}"
        )
    # The final verdict line MUST be present.
    assert "INCONCLUSIVE" in md


def test_verdict_json_round_trips(tmp_path):
    """SC-013: verdict.json on disk parses back to an equivalent ABVerdict shape."""
    from pg_raggraph.ab_gate import compute_verdict, write_verdict_report

    fixture = _load_premeasured(FIXTURE_DIR / "runner_output_worked_example.json")
    verdict = compute_verdict.from_premeasured(fixture)

    write_verdict_report(verdict, out_dir=tmp_path, latency_rows=[])

    reparsed = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
    assert reparsed == verdict.to_dict()


def test_latency_json_is_emitted_but_not_read_for_verdict(tmp_path):
    """SC-015: latency.json shape is documented, but mutating it doesn't change the verdict."""
    from pg_raggraph.ab_gate import compute_verdict, write_verdict_report

    fixture = _load_premeasured(FIXTURE_DIR / "runner_output_worked_example.json")
    verdict_1 = compute_verdict.from_premeasured(fixture)

    latency = [
        {
            "corpus": "bakeoff-scotus",
            "mode": "graph_leg",
            "question_id": "q1",
            "latency_ms": 100.0,
        },
        {
            "corpus": "bakeoff-scotus",
            "mode": "naive_vector",
            "question_id": "q1",
            "latency_ms": 20.0,
        },
    ]
    write_verdict_report(verdict_1, out_dir=tmp_path, latency_rows=latency)

    rows = json.loads((tmp_path / "latency.json").read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    assert {"corpus", "mode", "question_id", "latency_ms"} <= set(rows[0].keys())

    # Mutate latency.json on disk: this MUST NOT affect a subsequent verdict
    # computation, because compute_verdict never reads latency.json.
    (tmp_path / "latency.json").write_text("[]", encoding="utf-8")
    verdict_2 = compute_verdict.from_premeasured(fixture)
    assert verdict_1.label == verdict_2.label
    assert verdict_1.to_dict() == verdict_2.to_dict()
