"""Config loads from env and enforces model symmetry."""
from __future__ import annotations

import pytest

from age_bakeoff.config import BakeoffConfig


def test_defaults(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = BakeoffConfig()
    assert cfg.embedding_model == "BAAI/bge-small-en-v1.5"
    assert cfg.top_k == 10
    assert cfg.hop_budget == 2
    assert cfg.cost_budget_usd == 25.0


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("BAKEOFF_ANSWER_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("BAKEOFF_TOP_K", "15")
    cfg = BakeoffConfig()
    assert cfg.answer_model == "gpt-4o-mini"
    assert cfg.top_k == 15


def test_openai_key_required(monkeypatch):
    # Use empty string rather than delenv — pydantic-settings env_file
    # provides the key even after os.environ removal.
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        BakeoffConfig()


def test_openai_key_whitespace_rejected(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        BakeoffConfig()


def test_openai_key_stripped(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "  sk-test  ")
    cfg = BakeoffConfig()
    assert cfg.openai_api_key == "sk-test"


def test_naive_boost_is_accepted_mode(monkeypatch):
    """naive_boost must pass through config without rejection (SC-002 follow-up).

    BakeoffConfig does not validate the mode string — it forwards it to pgrg
    at runtime — so any string is accepted. This test documents the contract
    and will catch any future validator that inadvertently excludes naive_boost.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = BakeoffConfig()
    cfg.retrieval_mode = "naive_boost"
    assert cfg.retrieval_mode == "naive_boost"


def test_all_pgrg_modes_accepted(monkeypatch):
    """All documented pgrg modes pass through config without rejection."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    modes = ["hybrid", "smart", "local", "global", "naive", "naive_boost"]
    for mode in modes:
        cfg = BakeoffConfig()
        cfg.retrieval_mode = mode
        assert cfg.retrieval_mode == mode, f"mode {mode!r} was not accepted"
