"""Chunkshop JudgingConfig → llm-judge provider translation seam (SC-016).

This is the single auditable point where chunkshop's evaluation config shape
becomes an ``llm_judge.providers.LLMProvider`` instance. Keeping the
translation here (vs spreading it through the verdict writer) means a
schema drift in either library is localized to one function.

llm-judge is an optional dependency installed via the ``pg-raggraph[ab-gate]``
extra. If callers reach this seam without the extra installed, we raise a
clear ``ImportError`` pointing at the fix.
"""

from __future__ import annotations

from typing import Any

_INSTALL_HINT = (
    "llm-judge is required for pg-raggraph A/B-gate verdict computation. "
    "Install via:\n\n"
    "    pip install pg-raggraph[ab-gate]\n\n"
    "If installing from source: pip install 'pg-raggraph[ab-gate] @ "
    "git+https://github.com/yonk-labs/pg-raggraph.git'"
)


def _require_llm_judge():
    """Lazy-import llm_judge; raise a friendly ImportError if missing."""
    try:
        import llm_judge.engine as _engine
        import llm_judge.providers as _providers

        return _providers, _engine
    except ImportError as exc:
        raise ImportError(_INSTALL_HINT) from exc


def _chunkshop_judge_config_to_llm_judge_provider(config: dict[str, Any]):
    """Translate a chunkshop-shaped JudgingConfig dict into an llm-judge provider.

    Parameters
    ----------
    config:
        Shape::

            {
              "provider": {
                "kind": "openai-compatible" | "ollama" | "anthropic" | "mock" | …,
                "model": str,
                "base_url": str | None,
                "api_key_env": str | None,
              },
              "temperature": float,           # optional
              "timeout_seconds": float,       # optional
            }

        Field names match chunkshop's ``JudgeProvider`` schema; semantics
        match llm-judge's ``build_provider`` interface.

    Returns
    -------
    llm_judge.providers.LLMProvider
        A configured provider ready to pass to ``llm_judge.engine.evaluate_cases``
        as ``judge_provider=...``.
    """
    providers, _engine = _require_llm_judge()

    provider_block = config.get("provider", {})
    kind = provider_block.get("kind", "mock").lower()
    model = provider_block.get("model")
    base_url = provider_block.get("base_url")
    api_key_env = provider_block.get("api_key_env")
    temperature = float(config.get("temperature", 0.0))
    timeout = float(config.get("timeout_seconds", 30.0))

    if kind == "mock":
        return providers.MockProvider()

    # Map chunkshop kind → llm_judge.build_provider names.
    kind_map = {
        "openai-compatible": "openai-compatible",
        "openai": "openai",
        "anthropic": "anthropic",
        "ollama": "ollama",
        "gemini": "gemini",
        "openrouter": "openrouter",
    }
    if kind not in kind_map:
        raise ValueError(
            f"Unsupported chunkshop judge provider kind: {kind!r}. "
            f"Supported: {sorted(kind_map.keys()) + ['mock']}"
        )

    return providers.build_provider(
        provider=kind_map[kind],
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        command=None,
        timeout=timeout,
        temperature=temperature,
    )
