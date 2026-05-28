"""Unit tests for the A/B verdict writer (SC-009..SC-015)."""

import json  # noqa: F401  # used by tests added in Task B3+
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
