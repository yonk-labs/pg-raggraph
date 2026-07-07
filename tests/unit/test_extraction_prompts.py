"""Tests for extraction prompt selection."""

import asyncio

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.extraction import (
    CODE_EXTRACTION_PROMPT,
    DEV_EXTRACTION_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    PROSE_EXTRACTION_PROMPT,
    HttpxLLMProvider,
    _cache_key,
    config_with_prompt,
    get_prompt,
    resolve_extraction_prompt,
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


# --- Per-KB prompt resolution (#94) ---


def _cfg(**kw) -> PGRGConfig:
    return PGRGConfig(**kw)


def test_resolve_precedence_override_wins():
    cfg = _cfg(extraction_prompt="dev", extraction_prompt_by_namespace={"kb": "code"})
    got = resolve_extraction_prompt(cfg, namespace="kb", override="prose", stamped="code")
    assert got == "prose"


def test_resolve_stamped_beats_namespace_map_and_global():
    cfg = _cfg(extraction_prompt="dev", extraction_prompt_by_namespace={"kb": "code"})
    assert resolve_extraction_prompt(cfg, namespace="kb", stamped="prose") == "prose"


def test_resolve_namespace_map_beats_global():
    cfg = _cfg(extraction_prompt="dev", extraction_prompt_by_namespace={"kb": "prose"})
    assert resolve_extraction_prompt(cfg, namespace="kb") == "prose"


def test_resolve_falls_back_to_global_config():
    cfg = _cfg(extraction_prompt="dev", extraction_prompt_by_namespace={"other": "prose"})
    assert resolve_extraction_prompt(cfg, namespace="kb") == "dev"
    assert resolve_extraction_prompt(cfg) == "dev"


def test_resolve_default_when_nothing_set():
    assert resolve_extraction_prompt(_cfg(), namespace="kb") == "default"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"override": "bogus"},
        {"stamped": "bogus"},
    ],
)
def test_resolve_unknown_prompt_raises(kwargs):
    with pytest.raises(ValueError, match="bogus"):
        resolve_extraction_prompt(_cfg(), namespace="kb", **kwargs)


def test_resolve_unknown_prompt_in_namespace_map_raises():
    cfg = _cfg(extraction_prompt_by_namespace={"kb": "bogus"})
    with pytest.raises(ValueError, match="extraction_prompt_by_namespace"):
        resolve_extraction_prompt(cfg, namespace="kb")
    # Other namespaces never touch the bad entry.
    assert resolve_extraction_prompt(cfg, namespace="clean") == "default"


def test_namespace_map_env_json(monkeypatch):
    monkeypatch.setenv("PGRG_EXTRACTION_PROMPT_BY_NAMESPACE", '{"kb-chats": "prose"}')
    cfg = PGRGConfig()
    assert cfg.extraction_prompt_by_namespace == {"kb-chats": "prose"}
    assert resolve_extraction_prompt(cfg, namespace="kb-chats") == "prose"


def test_config_with_prompt_copies_without_mutating():
    cfg = _cfg(extraction_prompt="default")
    same = config_with_prompt(cfg, "default")
    assert same is cfg
    copied = config_with_prompt(cfg, "prose")
    assert copied is not cfg
    assert copied.extraction_prompt == "prose"
    assert cfg.extraction_prompt == "default"


def test_cache_key_is_prompt_aware():
    # Regression pin from issue #94: switching prompts must never serve a
    # stale cross-prompt cache hit.
    assert _cache_key("x", "prose") != _cache_key("x", "default")
    assert _cache_key("x", "prose") == _cache_key("x", "prose")


def test_ingest_records_fails_loud_before_any_write():
    # Validation runs before connect/embedder/DB — an unconnected GraphRAG
    # is enough to prove the ValueError fires pre-write.
    from pg_raggraph import GraphRAG

    rag = GraphRAG(dsn="postgresql://x:x@localhost:1/x")
    with pytest.raises(ValueError, match="bogus"):
        asyncio.run(
            rag.ingest_records(
                [{"text": "t", "source_id": "s"}],
                namespace="kb",
                extraction_prompt="bogus",
            )
        )
    with pytest.raises(ValueError, match="bogus"):
        asyncio.run(rag.ingest(["/nonexistent"], namespace="kb", extraction_prompt="bogus"))
