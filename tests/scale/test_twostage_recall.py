# tests/scale/test_twostage_recall.py
#
# Recall A/B (Task 1.1 Step 4 / spike Step 5): on a freshly-ingested ~5k
# `ts` fixture, the two-stage path's top-k chunk-id set must overlap the
# single-stage path's set by >= 0.95. Acceptance: no recall regression at
# the default candidate_k=200. Toggling `config.two_stage_retrieval` is the
# spike-sanctioned A/B switch.
import pytest

from pg_raggraph import GraphRAG  # noqa: F401  (fixture provides instance)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_twostage_recall_matches_singlestage(scale_rag):
    rows = [
        {"text": f"doc {i} about topic {i % 7}", "source_id": f"t{i}"}
        for i in range(5000)
    ]
    await scale_rag.ingest_records(rows, namespace="ts")

    # Two-stage (default True).
    scale_rag.config.two_stage_retrieval = True
    r_two = await scale_rag.query("topic 3", mode="naive", namespace="ts")
    two = {c.chunk_id for c in r_two.chunks}

    # Single-stage A/B control.
    scale_rag.config.two_stage_retrieval = False
    r_one = await scale_rag.query("topic 3", mode="naive", namespace="ts")
    one = {c.chunk_id for c in r_one.chunks}

    assert two, "two-stage returned no chunks"
    assert one, "single-stage returned no chunks"
    overlap = len(two & one) / len(two)
    assert overlap >= 0.95, (
        f"recall regression: two-stage/single-stage overlap {overlap:.3f} "
        f"(two={sorted(two)} one={sorted(one)})"
    )
