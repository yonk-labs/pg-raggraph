"""Harness configuration.

Defaults align with the design doc; every value is overridable via CLI flag
or env var. Embedder is pinned (the rank-metric winner) on purpose — see
design §2 Out of scope.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Pinned embedder. Operator must ensure the target Postgres DB schema was
# created with this embedding_dim — the schema bakes vector(N) per DB.
PINNED_EMBEDDING_MODEL = os.environ.get("PGRG_BENCH_EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5")
PINNED_EMBEDDING_DIM = int(os.environ.get("PGRG_BENCH_EMBEDDING_DIM", "1024"))

DEFAULT_DSN = os.environ.get(
    "PGRG_BENCH_DSN",
    "postgresql://postgres:postgres@localhost:5437/pg_raggraph_bench",
)


@dataclass(frozen=True)
class ArmSpec:
    name: str
    fact_extractor: str  # "llm" | "lede_spacy" | "none"
    requires_llm: bool


ARMS: dict[str, ArmSpec] = {
    "lede_spacy": ArmSpec(name="lede_spacy", fact_extractor="lede_spacy", requires_llm=False),
    "llm": ArmSpec(name="llm", fact_extractor="llm", requires_llm=True),
}

# Retrieval ladder. Each entry: (rung_label, mode_kwargs).
# mode_kwargs is a dict passed straight to GraphRAG.query(**kwargs).
LADDER: list[tuple[str, dict]] = [
    ("L1_naive", {"mode": "naive"}),
    ("L2_naive_boost", {"mode": "naive_boost"}),
    ("GP_local", {"mode": "local"}),
    ("GP_global", {"mode": "global"}),
    ("GP_hybrid", {"mode": "hybrid"}),
    ("L4_rerank", {"mode": "naive", "rerank": True}),
    ("smart", {"mode": "smart"}),
    ("L0_summary", {"mode": "summary"}),
]


@dataclass
class RunConfig:
    dataset: str
    arms: list[str] = field(default_factory=lambda: ["lede_spacy"])
    subset: int = 500
    seed: int = 42
    modes: list[str] | None = None  # None = use full LADDER; else filter by label
    reingest: bool = False
    skip_ingest: bool = False
    judge: str = "auto"  # auto | openai | local
    dsn: str | None = None
    output_dir: str | None = None
