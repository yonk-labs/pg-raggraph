"""Tests for extraction prompt selection."""

import asyncio

from pg_raggraph.extraction import (
    CODE_EXTRACTION_PROMPT,
    DEV_EXTRACTION_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    PROSE_EXTRACTION_PROMPT,
    HttpxLLMProvider,
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


def test_code_prompt():
    assert get_prompt("code") == CODE_EXTRACTION_PROMPT
    # code-structure vocabulary (concepts/modules/deps), not incident/ticket
    assert "module" in CODE_EXTRACTION_PROMPT.lower()
    assert "DEPENDS_ON" in CODE_EXTRACTION_PROMPT


def test_prose_prompt():
    assert get_prompt("prose") == PROSE_EXTRACTION_PROMPT
    # prose vocabulary: preference/location relations + common-noun entities
    assert "LIKES" in PROSE_EXTRACTION_PROMPT
    assert "DISLIKES" in PROSE_EXTRACTION_PROMPT
    assert "PREFERS" in PROSE_EXTRACTION_PROMPT
    assert "LIVES_IN" in PROSE_EXTRACTION_PROMPT
    assert "SERVES" in PROSE_EXTRACTION_PROMPT
    # preference-verb synonyms map onto the closed set, not bespoke types
    assert "crave" in PROSE_EXTRACTION_PROMPT
    assert "CRAVES" not in PROSE_EXTRACTION_PROMPT
    assert "Do NOT require proper nouns" in PROSE_EXTRACTION_PROMPT
    # base-form canonicalization rule (variant dishes land on one node)
    assert "BASE form" in PROSE_EXTRACTION_PROMPT


def test_prompts_are_distinct():
    prompts = [
        EXTRACTION_SYSTEM_PROMPT,
        DEV_EXTRACTION_PROMPT,
        CODE_EXTRACTION_PROMPT,
        PROSE_EXTRACTION_PROMPT,
    ]
    assert len(set(prompts)) == len(prompts)


class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": "{}"}}]}


class _FakeClient:
    def __init__(self, captured):
        self._captured = captured

    async def post(self, url, headers=None, json=None):
        self._captured.update(json or {})
        return _FakeResp()

    async def aclose(self):
        pass


def test_llm_max_tokens_sent_when_configured():
    captured: dict = {}
    provider = HttpxLLMProvider("http://x", "m", max_tokens=4096)
    asyncio.run(provider.aclose())  # release the real pool before swapping
    provider._client = _FakeClient(captured)
    asyncio.run(provider.complete([{"role": "user", "content": "x"}]))
    assert captured["max_tokens"] == 4096


def test_llm_max_tokens_omitted_by_default():
    captured: dict = {}
    provider = HttpxLLMProvider("http://x", "m")
    asyncio.run(provider.aclose())
    provider._client = _FakeClient(captured)
    asyncio.run(provider.complete([{"role": "user", "content": "x"}]))
    assert "max_tokens" not in captured
