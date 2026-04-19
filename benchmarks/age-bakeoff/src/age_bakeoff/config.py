"""Shared bakeoff configuration — single source of truth for both engines."""
from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BakeoffConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BAKEOFF_",
        env_file=".env",
        extra="ignore",
    )

    answer_model: str = "gpt-5-mini"
    judge_model: str = "gpt-5-mini"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    top_k: int = 10
    hop_budget: int = 2
    cost_budget_usd: float = 25.0
    # pg-raggraph retrieval mode (hybrid|smart|local|global|naive|naive_boost). Only the
    # pgrg engine honours this; AGE has a fixed retrieval strategy.
    retrieval_mode: str = Field(
        default="hybrid",
        validation_alias="PGRG_BAKEOFF_RETRIEVAL_MODE",
    )

    pgrg_dsn: str = Field(
        default="postgresql://postgres:postgres@localhost:5434/age_bakeoff_pgrg",
        validation_alias="PGRG_DSN",
    )
    age_dsn: str = Field(
        default="postgresql://postgres:postgres@localhost:5435/age_bakeoff_age",
        validation_alias="AGE_DSN",
    )

    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")

    @field_validator("openai_api_key")
    @classmethod
    def _require_key(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("OPENAI_API_KEY is required")
        return stripped
