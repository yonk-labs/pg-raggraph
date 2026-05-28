"""SC-003: graph_leg resolves question terms via resolve_entity_lookup once each."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pg_raggraph.ab_gate import GoldQuestion
from pg_raggraph.ab_gate.harness import run_harness_mode
from pg_raggraph.resolution import ResolvedEntity


@pytest.mark.asyncio
async def test_calls_resolve_entity_per_term():
    """Mock resolve_entity_lookup; assert call count == encoded-term count."""
    rag = MagicMock()
    rag.db.fetch_all = AsyncMock(return_value=[])
    rag.config = MagicMock()

    # Force the encoder to return exactly 3 terms.
    with (
        patch(
            "pg_raggraph.ab_gate.harness._encode_question_terms",
            return_value=["Bostock", "Title VII", "Clayton"],
        ),
        patch(
            "pg_raggraph.ab_gate.harness.resolve_entity_lookup",
            new=AsyncMock(
                side_effect=[
                    ResolvedEntity(
                        id=1,
                        surface="Bostock",
                        canonical_name="Bostock",
                        score=1.0,
                        match_type="exact",
                    ),
                    ResolvedEntity(
                        id=2,
                        surface="Title VII",
                        canonical_name="Title VII",
                        score=1.0,
                        match_type="exact",
                    ),
                    None,  # 'Clayton' doesn't resolve
                ]
            ),
        ) as mock_lookup,
    ):
        await run_harness_mode(
            rag,
            corpus_id="ns",
            mode="graph_leg",
            gold_questions=[GoldQuestion(id="q1", question="dummy — encoder is mocked")],
            top_k=10,
        )
        assert mock_lookup.await_count == 3, (
            f"expected 3 resolve_entity_lookup calls (one per encoded term); "
            f"got {mock_lookup.await_count}"
        )


@pytest.mark.asyncio
async def test_resolves_with_corpus_id_namespace():
    """SC-006-adjacent: every resolver call passes corpus_id."""
    rag = MagicMock()
    rag.db.fetch_all = AsyncMock(return_value=[])
    rag.config = MagicMock()

    with (
        patch(
            "pg_raggraph.ab_gate.harness._encode_question_terms",
            return_value=["X"],
        ),
        patch(
            "pg_raggraph.ab_gate.harness.resolve_entity_lookup",
            new=AsyncMock(return_value=None),
        ) as mock_lookup,
    ):
        await run_harness_mode(
            rag,
            corpus_id="my-corpus",
            mode="graph_leg",
            gold_questions=[GoldQuestion(id="q1", question="X")],
            top_k=10,
        )
        call = mock_lookup.await_args_list[0]
        assert call.kwargs["corpus_id"] == "my-corpus"
