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

from pg_raggraph.ab_gate.io import (
    ABCaseResult,
    ABRetrievedItem,
    ABRunnerOutput,
    ABVerdict,
    MetricRollup,
    MetricVerdict,
)
from pg_raggraph.ab_gate.writer import compute_verdict

__all__ = [
    "ABCaseResult",
    "ABRetrievedItem",
    "ABRunnerOutput",
    "ABVerdict",
    "MetricRollup",
    "MetricVerdict",
    "compute_verdict",
]
