"""Tests for extraction prompt selection."""

from pg_raggraph.extraction import (
    DEV_EXTRACTION_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    get_prompt,
)


def test_default_prompt():
    assert get_prompt("default") == EXTRACTION_SYSTEM_PROMPT


def test_dev_prompt():
    assert get_prompt("dev") == DEV_EXTRACTION_PROMPT
    assert "OWNS" in DEV_EXTRACTION_PROMPT
    assert "DEPENDS_ON" in DEV_EXTRACTION_PROMPT
    assert "person" in DEV_EXTRACTION_PROMPT
    assert "service" in DEV_EXTRACTION_PROMPT


def test_unknown_prompt_falls_back_to_default():
    assert get_prompt("nonexistent") == EXTRACTION_SYSTEM_PROMPT


def test_prompts_are_distinct():
    assert EXTRACTION_SYSTEM_PROMPT != DEV_EXTRACTION_PROMPT
