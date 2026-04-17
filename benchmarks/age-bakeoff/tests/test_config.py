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
