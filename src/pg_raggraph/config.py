"""Configuration for pg-raggraph."""

from __future__ import annotations

from pydantic_settings import BaseSettings

# Ingestion throttle profiles — pick one based on your hardware and how much
# headroom you want to leave for other processes.
#
# conservative: safe on shared servers / laptops. Leaves CPU free.
# balanced:     reasonable default. Uses half the cores.
# aggressive:   maxes out a dedicated machine.
# max:          saturates everything. For one-off batch jobs only.
#
# Each profile tunes three knobs:
#   doc_concurrency        - documents processed in parallel
#   extract_concurrency    - concurrent LLM extraction calls
#   embed_batch_size       - texts embedded per batch
INGEST_PROFILES = {
    "conservative": {
        "doc_concurrency": 1,
        "extract_concurrency": 4,
        "embed_batch_size": 8,
    },
    "balanced": {
        "doc_concurrency": 2,
        "extract_concurrency": 8,
        "embed_batch_size": 16,
    },
    "aggressive": {
        "doc_concurrency": 4,
        "extract_concurrency": 16,
        "embed_batch_size": 32,
    },
    "max": {
        "doc_concurrency": 8,
        "extract_concurrency": 32,
        "embed_batch_size": 64,
    },
}


class PGRGConfig(BaseSettings):
    """All pg-raggraph settings. Override via env vars prefixed with PGRG_."""

    model_config = {"env_prefix": "PGRG_"}

    # Database
    dsn: str = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
    pool_min: int = 2
    pool_max: int = 10

    # Namespace
    namespace: str = "default"

    # Embedding
    embedding_dim: int = 384
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_provider: str = "local"  # local | openai | ollama

    # LLM (OpenAI-compatible API)
    llm_base_url: str = "http://localhost:11434/v1"  # Ollama default
    llm_model: str = "llama3.2"
    llm_api_key: str = ""  # set for OpenAI, leave empty for Ollama
    extraction_prompt: str = "default"  # default | dev
    # Skip entity/relationship extraction during ingestion.
    # Set true for pure vector RAG mode — no LLM needed for ingest.
    skip_extraction: bool = False

    # Chunking
    # auto     — default; detect markdown/code/prose from source_path + content
    # hierarchy — heading-prefixed chunks (H1-H6), or title-prefix fallback when
    #             no headings exist. Opt-in: wins on corpora with concrete
    #             per-doc titles (case names, article titles). Regresses on
    #             format-string titles (meeting updates, ticket prefixes) — see
    #             benchmarks/age-bakeoff/results/ACME-HIER-REPLICATION.md.
    #             Skips token-budget splitting by design; relies on embedder
    #             truncation for oversized sections (mirrors the benchmarked
    #             behavior byte-for-byte).
    chunk_strategy: str = "auto"
    chunk_max_tokens: int = 512
    chunk_overlap_tokens: int = 50

    # Ingestion parallelism — default profile is "balanced"
    ingest_profile: str = "balanced"  # conservative | balanced | aggressive | max
    # Individual knobs — if set, they override the profile
    extract_concurrency: int = 0  # 0 = use profile default
    embed_batch_size: int = 0  # 0 = use profile default
    doc_concurrency: int = 0  # 0 = use profile default
    # Process priority — 0 = normal, 10 = lower (nicer), 19 = lowest (shared servers)
    nice_level: int = 0

    def model_post_init(self, __context):
        """Apply profile defaults for any unset parallelism knobs."""
        profile = INGEST_PROFILES.get(self.ingest_profile, INGEST_PROFILES["balanced"])
        if self.doc_concurrency == 0:
            self.doc_concurrency = profile["doc_concurrency"]
        if self.extract_concurrency == 0:
            self.extract_concurrency = profile["extract_concurrency"]
        if self.embed_batch_size == 0:
            self.embed_batch_size = profile["embed_batch_size"]

        # Apply nice level if set
        if self.nice_level > 0:
            import os

            try:
                current = os.nice(0)
                target = min(19, current + self.nice_level)
                os.nice(target - current)
            except (OSError, AttributeError):
                pass  # Windows or restricted env

    # Retrieval
    max_hops: int = 2
    top_k: int = 10
    similarity_threshold: float = 0.3

    # Smart mode routing thresholds
    # If top chunk score >= boost_confidence_threshold: return naive result as-is
    # If top chunk score < expand_confidence_threshold: escalate to graph expansion
    # Otherwise: apply cheap graph boost
    boost_confidence_threshold: float = 0.7
    expand_confidence_threshold: float = 0.4
    enable_graph_boost: bool = True
    graph_boost_factor: float = 1.2  # multiplier for chunks connected to seed entities

    # Entity resolution
    resolution_threshold: float = 0.85
    trgm_weight: float = 0.4
    vec_weight: float = 0.6
    min_trgm_score: float = 0.3
