"""Generic corpus class for external corpora extracted via
``tools.extract_external_corpus``.

One corpus class per registered external corpus. Cache is at
``corpora/external-extractions/{corpus_id}.json``. If the cache doesn't
exist, raises FileNotFoundError — matching the PgSrcCorpus pattern so the
CLI's ``_load_corpora`` skips gracefully with a warning.
"""
from __future__ import annotations

import json
from pathlib import Path

from age_bakeoff.extraction.external_corpora import CORPUS_LOADERS
from age_bakeoff.models import ExtractionOutput

_CACHE_DIR = (
    Path(__file__).resolve().parents[3] / "corpora" / "external-extractions"
)


class ExternalCorpus:
    """Loads a pre-extracted external corpus from the cache."""

    def __init__(self, corpus_id: str) -> None:
        if corpus_id not in CORPUS_LOADERS:
            raise ValueError(
                f"Unknown external corpus {corpus_id!r}; "
                f"available: {sorted(CORPUS_LOADERS)}"
            )
        self.name = corpus_id
        self._cache_path = _CACHE_DIR / f"{corpus_id}.json"

    def load(self) -> ExtractionOutput:
        if not self._cache_path.exists():
            raise FileNotFoundError(
                f"{self.name} extraction cache not found at {self._cache_path}. "
                f"Run: uv run python -m age_bakeoff.tools.extract_external_corpus "
                f"--corpus {self.name}"
            )
        raw = json.loads(self._cache_path.read_text())
        return ExtractionOutput(**raw)


def all_external_corpora() -> dict[str, ExternalCorpus]:
    """Return every external corpus that has a cached extraction on disk.

    Missing caches are silently skipped (matches the PgSrcCorpus pattern).
    """
    out: dict[str, ExternalCorpus] = {}
    for corpus_id in CORPUS_LOADERS:
        try:
            c = ExternalCorpus(corpus_id)
            c.load()  # verify cache exists + parses
            out[corpus_id] = c
        except (FileNotFoundError, ValueError):
            continue
    return out
