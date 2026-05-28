"""A/B verdict writer — applies chunkshop emission contract §3 to runner output.

This module owns the verdict computation (``compute_verdict``) and the
report emission (``write_verdict_report``). The LLM-judge integration is
intentionally siloed in ``judge_seam.py`` so the verdict logic can be
unit-tested with hand-crafted score fixtures, no llm-judge dependency.
"""

from __future__ import annotations

# ============================================================================
# Threshold constants — chunkshop emission contract §3.2.
# These are the verdict knobs. Changing them MUST be a deliberate edit
# coordinated with chunkshop (see contract §5 Change-Management).
# ============================================================================

#: Graph wins the recall metric if its recall@10 is at least +5pp above naive.
RECALL_AT_10_LIFT_PP: float = 5.0

#: Graph wins the MRR metric if its MRR is at least +0.05 above naive.
MRR_DELTA: float = 0.05

#: Graph wins the LLM-judge metric if its win-rate is at least +0.10 above naive.
JUDGE_WIN_RATE_DELTA: float = 0.10
