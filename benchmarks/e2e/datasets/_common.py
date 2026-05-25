"""Shared DTOs and helpers for dataset loaders.

Loaders normalize their source format into this shape so downstream
ingest / retrieve / score code is dataset-agnostic.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

CACHE_ROOT = Path(
    os.environ.get("PGRG_BENCH_CACHE", str(Path.home() / ".cache" / "pg_raggraph_bench"))
)


@dataclass(frozen=True)
class CorpusDoc:
    source_id: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Query:
    qid: str
    question: str
    answers: list[str]
    strata: dict[str, str] = field(default_factory=dict)


@dataclass
class DatasetBundle:
    name: str
    corpus_docs: list[CorpusDoc]
    queries: list[Query]
    license_notice: str

    def summary(self) -> str:
        strata_keys = sorted({k for q in self.queries for k in q.strata})
        return (
            f"{self.name}: {len(self.corpus_docs)} docs, {len(self.queries)} queries, "
            f"strata={strata_keys}"
        )


def cache_dir(dataset: str) -> Path:
    p = CACHE_ROOT / dataset
    p.mkdir(parents=True, exist_ok=True)
    return p


def download(url: str, dest: Path, *, sha256: str | None = None) -> Path:
    """Download ``url`` to ``dest`` if not already present.

    If ``sha256`` is given, verify after download (or re-download on mismatch).
    """
    if dest.exists():
        if sha256 is None or _sha256(dest) == sha256:
            return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:  # noqa: S310 — explicit URL, not user input
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    if sha256 is not None and _sha256(tmp) != sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"sha256 mismatch downloading {url}")
    tmp.replace(dest)
    return dest


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_license(dataset: str, text: str) -> None:
    (cache_dir(dataset) / "LICENSE").write_text(text, encoding="utf-8")


def load_subset_ids(dataset: str, n: int, seed: int) -> list[str] | None:
    """Read a frozen subset file if present; return its qid list."""
    p = Path(__file__).resolve().parent.parent / "subsets" / f"{dataset}-{n}-seed{seed}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())["qids"]


def save_subset_ids(dataset: str, n: int, seed: int, qids: list[str]) -> Path:
    p = Path(__file__).resolve().parent.parent / "subsets" / f"{dataset}-{n}-seed{seed}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"dataset": dataset, "n": n, "seed": seed, "qids": qids}, indent=2))
    return p
