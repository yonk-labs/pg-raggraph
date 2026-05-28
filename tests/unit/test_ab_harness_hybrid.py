"""SC-007: hybrid mode ships as NotImplementedError per the brief's deferral clause."""

from unittest.mock import MagicMock

import pytest

from pg_raggraph.ab_gate import GoldQuestion
from pg_raggraph.ab_gate.harness import run_harness_mode


@pytest.mark.asyncio
async def test_hybrid_raises_not_implemented():
    """SC-007: brief allows shipping hybrid with NotImplementedError; the message
    must name the issue so operators can find the tracking ticket."""
    rag = MagicMock()
    with pytest.raises(NotImplementedError) as ei:
        await run_harness_mode(
            rag,
            corpus_id="ns",
            mode="hybrid",
            gold_questions=[GoldQuestion(id="q1", question="X")],
            top_k=10,
        )
    assert "hybrid" in str(ei.value).lower()
    assert "#48" in str(ei.value)
