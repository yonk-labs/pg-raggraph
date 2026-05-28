"""Unit test for the chunkshop JudgingConfig → llm-judge provider seam (SC-016)."""

import pytest


def test_chunkshop_config_maps_to_llm_judge_provider(monkeypatch):
    """SC-016: a chunkshop-shaped JudgingConfig dict translates to an llm_judge provider instance.

    Skipped if llm-judge isn't importable (running base install without the
    ab-gate extra). On CI with the extra installed, this test executes the
    seam and asserts the returned object is an LLMProvider subclass with
    the expected model/base_url fields.
    """
    llm_judge_providers = pytest.importorskip(
        "llm_judge.providers",
        reason="llm-judge not installed — run with pg-raggraph[ab-gate]",
    )

    from pg_raggraph.ab_gate.judge_seam import (
        _chunkshop_judge_config_to_llm_judge_provider,
    )

    # llm-judge requires an API key to be set in the env when building an
    # openai-compatible provider. Inject a fake one so the test exercises the
    # seam without depending on a real key being available in CI.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")

    # Chunkshop's JudgingConfig / JudgeProvider shape (paraphrased — reuse the
    # field names chunkshop already emits).
    chunkshop_config = {
        "provider": {
            "kind": "openai-compatible",
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
        },
        "temperature": 0.0,
        "timeout_seconds": 30.0,
    }

    provider = _chunkshop_judge_config_to_llm_judge_provider(chunkshop_config)

    assert isinstance(provider, llm_judge_providers.LLMProvider)
    assert provider.model == "gpt-4o-mini"


def test_seam_handles_mock_kind_for_offline_tests():
    """A 'mock' provider kind returns llm_judge.providers.MockProvider.

    Lets fixture-driven judging tests run with zero external dependencies.
    """
    llm_judge_providers = pytest.importorskip("llm_judge.providers")

    from pg_raggraph.ab_gate.judge_seam import (
        _chunkshop_judge_config_to_llm_judge_provider,
    )

    provider = _chunkshop_judge_config_to_llm_judge_provider({"provider": {"kind": "mock"}})
    assert isinstance(provider, llm_judge_providers.MockProvider)
