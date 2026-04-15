"""Shared test fixtures for the age-bakeoff benchmark."""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def _disable_external_calls(monkeypatch):
    """Guard: no test may accidentally hit real OpenAI or a live DB without opting in."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-do-not-use")
    monkeypatch.setenv("PGRG_DSN", "postgresql://invalid:invalid@localhost:0/test")
    monkeypatch.setenv("AGE_DSN", "postgresql://invalid:invalid@localhost:0/test")
