"""Configuration for pg-raggraph."""

from __future__ import annotations

import logging
import os
from typing import Literal

from pydantic_settings import BaseSettings

_logger = logging.getLogger("pg_raggraph.config")
_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
_default_dsn_warned = False
_pool_max_warned = False
_pool_fleet_warned = False
_POOL_FLEET_CONNECTION_LIMIT = 80
_WORKER_ENV_VARS = ("PGRG_WORKERS", "WEB_CONCURRENCY", "GUNICORN_WORKERS", "UVICORN_WORKERS")

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


def _observed_worker_count() -> int:
    """Best-effort worker count from common deployment env vars."""
    for env_var in _WORKER_ENV_VARS:
        value = os.environ.get(env_var)
        if not value:
            continue
        try:
            workers = int(value)
        except ValueError:
            continue
        if workers > 0:
            return workers
    return 1


class PGRGConfig(BaseSettings):
    """All pg-raggraph settings. Override via env vars prefixed with PGRG_."""

    model_config = {"env_prefix": "PGRG_"}

    # Database
    dsn: str = _DEFAULT_DSN
    read_dsn: str = ""
    pool_min: int = 2
    pool_max: int = 10
    statement_timeout_ms: int = 0
    rls_enabled: bool = False

    # Namespace
    namespace: str = "default"

    # Embedding
    embedding_dim: int = 384
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_provider: str = "local"  # local | openai | ollama | http
    embedding_threads: int = 1
    embedding_base_url: str = ""
    embedding_api_key: str = ""

    # LLM (OpenAI-compatible API)
    llm_base_url: str = "http://localhost:11434/v1"  # Ollama default
    llm_model: str = "llama3.2"
    llm_api_key: str = ""  # set for OpenAI, leave empty for Ollama
    # `default` is the generic prompt; `dev` is the developer-KB-tuned prompt
    # (entity types: person/service/library/file/commit/incident/ADR/etc.).
    # Typed Literal so a typo in PGRG_EXTRACTION_PROMPT raises ValidationError
    # at config init instead of silently falling back to "default".
    extraction_prompt: Literal["default", "dev"] = "default"
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

    # Ingestion parallelism — default profile is "balanced". Typed Literal
    # so a typo in PGRG_INGEST_PROFILE raises ValidationError at init
    # instead of silently falling back to "balanced".
    ingest_profile: Literal["conservative", "balanced", "aggressive", "max"] = "balanced"
    # Individual knobs — if set, they override the profile
    extract_concurrency: int = 0  # 0 = use profile default
    embed_batch_size: int = 0  # 0 = use profile default
    doc_concurrency: int = 0  # 0 = use profile default
    # Process priority — 0 = normal, 10 = lower (nicer), 19 = lowest (shared servers)
    nice_level: int = 0

    def model_post_init(self, __context):
        """Apply profile defaults for any unset parallelism knobs.

        Also enforces the production-safety guard for default credentials
        (PR-211): when ``PGRG_ENV=production`` and the DSN is the dev default,
        refuse to start. In any other env, log a one-time warning so users
        know they're running on the throw-away dev credentials.
        """
        profile = INGEST_PROFILES.get(self.ingest_profile, INGEST_PROFILES["balanced"])
        if self.doc_concurrency == 0:
            self.doc_concurrency = profile["doc_concurrency"]
        if self.extract_concurrency == 0:
            self.extract_concurrency = profile["extract_concurrency"]
        if self.embed_batch_size == 0:
            self.embed_batch_size = profile["embed_batch_size"]

        # Default-DSN guard. The default DSN bakes in well-known credentials
        # ("postgres:postgres") to keep first-run frictionless. Refusing in
        # production is the right loud failure; warning everywhere else keeps
        # the dev experience clean while making the choice visible.
        if self.dsn == _DEFAULT_DSN:
            env = os.environ.get("PGRG_ENV", "").lower()
            if env == "production":
                raise RuntimeError(
                    "Refusing to start with default Postgres credentials in "
                    "PGRG_ENV=production. Set PGRG_DSN to a production-safe "
                    "DSN (with non-default user/password) before launching."
                )
            global _default_dsn_warned
            if not _default_dsn_warned:
                _logger.warning(
                    "Using default DSN with well-known credentials "
                    "(postgresql://postgres:postgres@localhost:5434/...). "
                    "Override with PGRG_DSN before any non-local deployment."
                )
                _default_dsn_warned = True

        if self.pool_max > 10:
            global _pool_max_warned
            if not _pool_max_warned:
                _logger.warning(
                    "Configured pool_max=%d. For multi-tenant deployments, "
                    "prefer pool_max<=10 per process and put PgBouncer in "
                    "front of PostgreSQL for larger fleets. See "
                    "docs/deployment-embedding-scaling.md F6.",
                    self.pool_max,
                )
                _pool_max_warned = True

        workers = _observed_worker_count()
        fleet_connections = self.pool_max * workers
        if fleet_connections > _POOL_FLEET_CONNECTION_LIMIT:
            global _pool_fleet_warned
            if not _pool_fleet_warned:
                _logger.warning(
                    "Configured pool_max=%d across %d observed worker(s) can open "
                    "up to %d PostgreSQL connections. Keep pool_max*workers <= %d "
                    "or put PgBouncer in front of PostgreSQL. See "
                    "docs/deployment-embedding-scaling.md F6.",
                    self.pool_max,
                    workers,
                    fleet_connections,
                    _POOL_FLEET_CONNECTION_LIMIT,
                )
                _pool_fleet_warned = True

        # PR-215: nice_level is no longer applied at config-init time.
        # Importing PGRGConfig must not mutate process priority (the prior
        # behavior surprised callers who imported the package under tests
        # or from a sidecar framework). Application moved into `ingest()`
        # via `apply_nice_level()` below — that's the only path where
        # CPU-yield behavior was actually wanted.

    def apply_nice_level(self) -> None:
        """Apply the configured `nice_level` to the current process.

        Idempotent within reason — repeated calls move the priority by
        `nice_level` again, capped at 19 by the OS. Silently no-ops on
        platforms without `os.nice` (Windows) or in restricted sandboxes.
        Call this once when starting a long-running CPU-heavy operation
        (the ingest pipeline does this automatically).
        """
        if self.nice_level <= 0:
            return
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

    # Two-stage naive retrieval (K1). When True (default), mode="naive"
    # first fetches `retrieval_candidate_k` nearest chunks via a bare
    # `ORDER BY embedding <=> q` (HNSW-eligible), then re-scores that
    # candidate set with the full composite weight expression. This makes
    # the HNSW index `idx_chunk_embed` usable instead of a Seq Scan +
    # top-N sort over the whole namespace. Set False for the single-stage
    # A/B control (byte-identical to the pre-K1 path).
    two_stage_retrieval: bool = True
    retrieval_candidate_k: int = 200
    hnsw_m: int = 16
    hnsw_ef_construction: int = 64
    hnsw_ef_search: int = 40

    # Cross-encoder reranking (off by default; opt-in per-query via rerank=True).
    # When enabled, retrieval fetches top_k * rerank_factor candidates, then a
    # cross-encoder scores each (question, chunk) pair and trims to top_k.
    #
    # Default model: Xenova/ms-marco-MiniLM-L-6-v2 (~80 MB, ~5x faster on CPU
    #   than bge-reranker-base, <2 pp accuracy loss per public benchmarks).
    # Alternative for accuracy-first workloads: "BAAI/bge-reranker-base"
    #   (~1 GB, slower but higher quality on hard pairs).
    #
    # rerank_factor=2 means we fetch top_k*2 candidates then rerank to top_k.
    # Larger values fetch more candidates (better recall, slower); smaller
    # values stay closer to the original ranking.
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_factor: int = 2

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

    # --- Evolving-knowledge RAG (Tier 1+) ---
    # Zero cost when 'off'; ramp up per use case.
    # See docs/superpowers/specs/2026-04-22-evolving-knowledge-rag-design.md.
    evolution_tier: Literal["off", "structural", "fact_aware", "full"] = "off"

    # Scoring weights (only active when evolution_tier != 'off'). Conservative
    # defaults; run rag.tune_scoring_weights() per corpus for best results.
    # Weights are independent scalars; tune_scoring_weights() normalizes
    # per corpus. They do not need to sum to 1.0.
    w_sem: float = 0.50
    w_bm25: float = 0.20
    w_graph: float = 0.20
    w_recent: float = 0.10
    w_supersession: float = 0.10
    temporal_half_life_years: float = 5.0
    lambda_supersession: float = 0.5

    # Retrieval behavior modes
    retracted_behavior: Literal["hide", "flag", "surface_both"] = "flag"
    supersession_behavior: Literal["hide", "prefer_new", "surface_both"] = "surface_both"
    contradiction_detection: bool = True

    # Context assembly (used when Tier 2+ populates facts)
    fact_dedup_threshold: float = 0.8
    diversity_backfill: bool = True

    # Fact extraction (Tier 2+)
    # `lede_spacy` is the supported non-LLM extractor: lede + lede-spacy
    # NER produce (untyped) entities; edges are deterministic
    # sentence-level co-occurrence (RELATED_TO). No LLM, no network.
    # Requires the [lede_spacy] extra + `python -m spacy download
    # en_core_web_sm`. Selecting it builds a graph WITHOUT llm_base_url.
    # NOTE: it does NOT emit SPO triples and does NOT populate the Tier 2
    # `facts` table — that is a tracked follow-up. `llm` = full LLM
    # extraction; `none` = disabled.
    fact_extractor: Literal["llm", "lede_spacy", "none"] = "none"
    fact_similarity_threshold: float = 0.92
    fact_edge_candidate_k: int = 8
