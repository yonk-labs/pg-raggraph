"""pg-raggraph A/B-gate package — #47 lookup callers + #50 results writer.

Public surface:

- ``ABRunnerOutput``, ``ABCaseResult``, ``ABRetrievedItem`` — the #49↔#50
  I/O schema (locked in mission brief SC-023).
- ``ABVerdict``, ``MetricVerdict``, ``MetricRollup`` — the #50 output shape.
- ``compute_verdict`` — applies chunkshop emission contract §3 combiner
  + §3.4 asymmetry guard.
- ``write_verdict_report`` — emits verdict.json / verdict.md / latency.json.

The sibling plan (2026-05-28-ab-gate-harness-and-runner.md) adds
``harness.py`` and ``runner.py`` to the same package; this module's public
API is the only contract between the two efforts.
"""

from __future__ import annotations

from pg_raggraph.ab_gate.harness import run_harness_mode
from pg_raggraph.ab_gate.io import (
    ABCaseResult,
    ABRetrievedItem,
    ABRunnerOutput,
    ABVerdict,
    GoldQuestion,
    MetricRollup,
    MetricVerdict,
)
from pg_raggraph.ab_gate.judge_seam import (
    _chunkshop_judge_config_to_llm_judge_provider,
)
from pg_raggraph.ab_gate.runner import load_gold_questions, run_ab_matrix
from pg_raggraph.ab_gate.writer import compute_verdict, write_verdict_report

__all__ = [
    "ABCaseResult",
    "ABRetrievedItem",
    "ABRunnerOutput",
    "ABVerdict",
    "GoldQuestion",
    "MetricRollup",
    "MetricVerdict",
    "_chunkshop_judge_config_to_llm_judge_provider",
    "compute_verdict",
    "load_gold_questions",
    "run_ab_matrix",
    "run_harness_mode",
    "write_verdict_report",
]
