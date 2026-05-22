"""Dataset loaders for the e2e benchmark.

Each loader exposes ``load(subset: int, seed: int) -> DatasetBundle``.
The registry maps short names to loader callables for the CLI.
"""

from __future__ import annotations

from collections.abc import Callable

from benchmarks.e2e.datasets._common import DatasetBundle

_REGISTRY: dict[str, Callable[..., DatasetBundle]] = {}


def register(name: str, loader: Callable[..., DatasetBundle]) -> None:
    _REGISTRY[name] = loader


def get(name: str) -> Callable[..., DatasetBundle]:
    if name not in _REGISTRY:
        raise KeyError(f"unknown dataset {name!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def names() -> list[str]:
    return sorted(_REGISTRY)


from benchmarks.e2e.datasets import mhr, musique, twowiki  # noqa: E402,F401
