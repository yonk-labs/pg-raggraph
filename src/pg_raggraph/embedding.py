"""Embedding providers for pg-raggraph."""

from __future__ import annotations

import functools
import logging
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

from pg_raggraph.config import PGRGConfig

_logger = logging.getLogger("pg_raggraph.embedding")
# fastembed caches models under ~/.cache/fastembed by default. We use the
# cache_dir presence as a "is the model already on disk" signal so we know
# whether to surface a progress hint.
_FASTEMBED_CACHE = Path.home() / ".cache" / "fastembed"


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimension(self) -> int: ...


class FastEmbedProvider:
    """Local embedding using fastembed (ONNX-based, no PyTorch)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", threads: int | None = None):
        # PR-111: surface the first-run model download instead of silently
        # blocking for ~30 s while ~30 MB is fetched. fastembed has a
        # tqdm-based progress bar internally, but it's easy to miss when
        # interleaved with other CLI output. We add explicit INFO bookends
        # so the user knows what's happening even when running with the
        # JSON formatter (PR-210) that strips the tqdm escape codes.
        first_download = not _FASTEMBED_CACHE.exists() or not any(_FASTEMBED_CACHE.iterdir())
        if first_download:
            _logger.info(
                "Downloading embedding model %s on first use (~30 MB, one-time; cached at %s)",
                model_name,
                _FASTEMBED_CACHE,
            )
        t0 = time.perf_counter()
        self._model = _get_fastembed_model(model_name, threads)
        # Infer dimension from a test embedding
        test = list(self._model.embed(["test"]))[0]
        self._dim = len(test)
        if first_download:
            _logger.info(
                "Embedding model ready (loaded in %.1f s, dimension=%d)",
                time.perf_counter() - t0,
                self._dim,
            )

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # fastembed is sync, run in thread for async compatibility
        import asyncio

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._embed_sync, texts)
        return result

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        embeddings = list(self._model.embed(texts))
        return [e.tolist() for e in embeddings]


@functools.lru_cache(maxsize=None)
def _get_fastembed_model(model_name: str, threads: int | None):
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=model_name, threads=threads)


class HttpxEmbeddingProvider:
    """OpenAI-compatible embedding provider via httpx."""

    def __init__(self, base_url: str, model: str, api_key: str = "", dimension: int = 384):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._dim = dimension

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/embeddings",
                headers=headers,
                json={"model": self._model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]


def get_embedding_provider(config: PGRGConfig) -> EmbeddingProvider:
    """Factory to create the right embedding provider from config."""
    if config.embedding_provider == "local":
        return FastEmbedProvider(
            model_name=config.embedding_model,
            threads=config.embedding_threads,
        )
    elif config.embedding_provider in ("openai", "ollama"):
        base_url = config.llm_base_url
        if config.embedding_provider == "openai":
            base_url = "https://api.openai.com/v1"
        return HttpxEmbeddingProvider(
            base_url=base_url,
            model=config.embedding_model,
            api_key=config.llm_api_key,
            dimension=config.embedding_dim,
        )
    elif config.embedding_provider == "http":
        if not config.embedding_base_url:
            raise ValueError("embedding_provider='http' requires embedding_base_url")
        return HttpxEmbeddingProvider(
            base_url=config.embedding_base_url,
            model=config.embedding_model,
            api_key=config.embedding_api_key,
            dimension=config.embedding_dim,
        )
    else:
        raise ValueError(f"Unknown embedding provider: {config.embedding_provider}")
