"""AsyncOpenAI client factory for the bakeoff's three LLM roles.

Each role can point at a different OpenAI-compatible endpoint + model via
env vars. Defaults to OpenAI (api.openai.com). Set a role's ``_BASE_URL``
to a local vLLM / Ollama / TGI endpoint to run that role locally for $0.

Env vars:
    BAKEOFF_ANSWER_BASE_URL      — endpoint for answer generation
    BAKEOFF_ANSWER_MODEL         — model name for answer generation
    BAKEOFF_JUDGE_BASE_URL       — endpoint for LLM-judge scoring
    BAKEOFF_JUDGE_MODEL          — model name for judge
    BAKEOFF_EXTRACTION_BASE_URL  — endpoint for entity/relationship extraction
    BAKEOFF_EXTRACTION_MODEL     — model name for extraction

Any unset *_BASE_URL falls back to OPENAI_BASE_URL or api.openai.com.
"""
from __future__ import annotations

import os
from typing import Literal

from openai import AsyncOpenAI

Role = Literal["answer", "judge", "extraction"]


def _base_url_for(role: Role) -> str | None:
    env_name = f"BAKEOFF_{role.upper()}_BASE_URL"
    return os.environ.get(env_name) or os.environ.get("OPENAI_BASE_URL")


def model_for(role: Role, default: str = "gpt-5-mini") -> str:
    env_name = f"BAKEOFF_{role.upper()}_MODEL"
    return os.environ.get(env_name) or default


def client_for(role: Role) -> AsyncOpenAI:
    base = _base_url_for(role)
    kwargs: dict = {}
    if base:
        kwargs["base_url"] = base
        # Local endpoints (vLLM, Ollama) often accept any non-empty API key;
        # the SDK requires one to initialize.
        kwargs["api_key"] = os.environ.get("OPENAI_API_KEY") or "local"
    return AsyncOpenAI(**kwargs)
