"""Retrieval profile ladder and calibration helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProfileRung:
    """One calibrated rung in the cheap-to-accurate retrieval ladder."""

    index: int
    name: str
    strategy: str
    top_k: int
    note: str = ""
    est_tokens: dict[str, Any] | None = None
    est_accuracy: dict[str, Any] | None = None
    est_latency_ms: float | None = None


@dataclass(frozen=True)
class ProfileSpec:
    """Resolved retrieval profile settings for one query."""

    name: str
    index: int | None
    context_strategy: str
    top_k: int
    raw: bool = False
    rung: ProfileRung | None = None


@dataclass(frozen=True)
class ProfileCalibration:
    """Loaded profile calibration artifact plus fallback metadata."""

    ladder_version: str
    status: str
    rungs: tuple[ProfileRung, ...]
    raw_escape_hatch: dict[str, Any]
    source_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ladder_version": self.ladder_version,
            "status": self.status,
            "raw_escape_hatch": self.raw_escape_hatch,
            "source_path": self.source_path,
            "n_rungs": len(self.rungs),
            "rungs": [
                {
                    "index": rung.index,
                    "name": rung.name,
                    "strategy": rung.strategy,
                    "top_k": rung.top_k,
                    "note": rung.note,
                    "est_tokens": rung.est_tokens,
                    "est_accuracy": rung.est_accuracy,
                    "est_latency_ms": rung.est_latency_ms,
                }
                for rung in self.rungs
            ],
        }


_DEFAULT_RUNG_DATA: tuple[dict[str, Any], ...] = (
    {
        "index": 0,
        "name": "cheap",
        "strategy": "doc_summary_facts@3",
        "match": {"context_strategy": "doc_summary_facts@3", "top_k": 25},
        "note": "doc-summary+facts, top-3 docs - cheapest",
        "est_tokens": {"aggregate": 2110},
        "est_accuracy": {"aggregate": 0.6111},
    },
    {
        "index": 1,
        "name": "cheap_plus",
        "strategy": "doc_summary_facts@5",
        "match": {"context_strategy": "doc_summary_facts@5", "top_k": 25},
        "note": "doc-summary+facts, top-5 docs",
        "est_tokens": {"aggregate": 2375},
        "est_accuracy": {"aggregate": 0.6333},
    },
    {
        "index": 2,
        "name": "lean",
        "strategy": "full_selected_docs@3",
        "match": {"context_strategy": "full_selected_docs@3", "top_k": 25},
        "note": "whole docs, top-3",
        "est_tokens": {"aggregate": 4304},
        "est_accuracy": {"aggregate": 0.6889},
    },
    {
        "index": 3,
        "name": "balanced",
        "strategy": "doc_and_chunk_summary_toc_facts_plus_top5",
        "match": {
            "context_strategy": "doc_and_chunk_summary_toc_facts_plus_top5",
            "top_k": 25,
        },
        "note": "doc+chunk summaries with top-5 raw chunks (default)",
        "est_tokens": {"aggregate": 6672},
        "est_accuracy": {"aggregate": 0.7056},
    },
    {
        "index": 4,
        "name": "rich",
        "strategy": "full_selected_docs@5",
        "match": {"context_strategy": "full_selected_docs@5", "top_k": 25},
        "note": "whole docs, top-5",
        "est_tokens": {"aggregate": 7304},
        "est_accuracy": {"aggregate": 0.7333},
    },
    {
        "index": 5,
        "name": "stacked",
        "strategy": "per_doc5_chunksum_top5",
        "match": {"context_strategy": "per_doc5_chunksum_top5", "top_k": 25},
        "note": "per-doc summaries + retrieved-chunk summary + top-5 raw chunks",
        "est_tokens": {"aggregate": 10495},
        "est_accuracy": {"aggregate": 0.7556},
    },
    {
        "index": 6,
        "name": "accurate",
        "strategy": "full_selected_docs@10",
        "match": {"context_strategy": "full_selected_docs@10", "top_k": 25},
        "note": "whole docs, top-10 - the ceiling",
        "est_tokens": {"aggregate": 13878},
        "est_accuracy": {"aggregate": 0.8},
    },
)

_FALLBACK_CALIBRATION = {
    "ladder_version": "f-informed-1",
    "status": (
        "Packaged fallback for the Phase F-informed retrieval profile ladder. "
        "Use profile='raw' for legacy classic chunk context."
    ),
    "raw_escape_hatch": {"context_strategy": "classic_chunks", "top_k": 25},
    "rungs": list(_DEFAULT_RUNG_DATA),
}


def _default_calibration_path() -> Path:
    return (
        Path(__file__).resolve().parents[2] / "benchmarks" / "matrix" / "profile_calibration.json"
    )


def _rung_from_record(record: dict[str, Any], *, fallback_index: int) -> ProfileRung:
    match = record.get("match") or {}
    strategy = str(record.get("strategy") or match.get("context_strategy") or "")
    if not strategy:
        raise ValueError(f"profile rung {fallback_index} is missing a strategy")
    index = int(record.get("index", fallback_index))
    top_k = int(match.get("top_k", record.get("top_k", 25)))
    return ProfileRung(
        index=index,
        name=str(record.get("name") or f"rung_{index}"),
        strategy=strategy,
        top_k=top_k,
        note=str(record.get("note") or ""),
        est_tokens=record.get("est_tokens"),
        est_accuracy=record.get("est_accuracy"),
        est_latency_ms=record.get("est_latency_ms"),
    )


def _load_raw_calibration(path: Path | None) -> tuple[dict[str, Any], str | None]:
    path = path or _default_calibration_path()
    try:
        return json.loads(path.read_text(encoding="utf-8")), str(path)
    except FileNotFoundError:
        return dict(_FALLBACK_CALIBRATION), None


def load_profile_calibration(path: str | Path | None = None) -> ProfileCalibration:
    """Load profile calibration from disk, falling back to packaged defaults."""

    raw, source_path = _load_raw_calibration(Path(path) if path is not None else None)
    raw_rungs = raw.get("rungs") or []
    if not raw_rungs:
        raise ValueError("profile calibration must contain at least one rung")
    rungs = tuple(
        _rung_from_record(dict(record), fallback_index=i) for i, record in enumerate(raw_rungs)
    )
    rungs = tuple(sorted(rungs, key=lambda rung: rung.index))
    expected = list(range(len(rungs)))
    actual = [rung.index for rung in rungs]
    if actual != expected:
        raise ValueError(f"profile rung indexes must be contiguous {expected}, got {actual}")
    return ProfileCalibration(
        ladder_version=str(raw.get("ladder_version") or "unknown"),
        status=str(raw.get("status") or ""),
        rungs=rungs,
        raw_escape_hatch=dict(
            raw.get("raw_escape_hatch") or _FALLBACK_CALIBRATION["raw_escape_hatch"]
        ),
        source_path=source_path,
    )


def _resolve_float_index(value: float, n_rungs: int) -> int:
    if value < 0 or value > 1:
        raise ValueError("float retrieval profile must be between 0.0 and 1.0")
    return int(round(value * (n_rungs - 1)))


def resolve_profile(
    value: str | int | float | None = None,
    *,
    calibration: ProfileCalibration | None = None,
    default: str | int | float = "balanced",
) -> ProfileSpec:
    """Resolve a profile name, rung number, or 0..1 slider value.

    ``None`` resolves through ``default``. ``"raw"`` is intentionally outside
    the ordered ladder so UIs can expose it as a legacy escape hatch without
    breaking the cheap-to-accurate slider semantics.
    """

    cal = calibration or load_profile_calibration()
    if value is None:
        value = default

    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            value = default
            normalized = str(value).strip().lower()
        if normalized == "raw":
            strategy = str(cal.raw_escape_hatch.get("context_strategy", "classic_chunks"))
            top_k = int(cal.raw_escape_hatch.get("top_k", 25))
            return ProfileSpec(
                name="raw",
                index=None,
                context_strategy=strategy,
                top_k=top_k,
                raw=True,
            )
        if normalized.isdigit():
            value = int(normalized)
        elif _looks_like_float(normalized):
            value = float(normalized)
        else:
            by_name = {rung.name.lower(): rung for rung in cal.rungs}
            by_strategy = {rung.strategy.lower(): rung for rung in cal.rungs}
            rung = by_name.get(normalized) or by_strategy.get(normalized)
            if rung is None:
                valid = ", ".join([r.name for r in cal.rungs] + ["raw"])
                raise ValueError(f"unknown retrieval profile {value!r}; valid profiles: {valid}")
            return ProfileSpec(
                name=rung.name,
                index=rung.index,
                context_strategy=rung.strategy,
                top_k=rung.top_k,
                rung=rung,
            )

    if isinstance(value, bool):
        raise ValueError("boolean retrieval profile values are not supported")
    if isinstance(value, int):
        if value < 0 or value >= len(cal.rungs):
            raise ValueError(f"integer retrieval profile must be in range 0..{len(cal.rungs) - 1}")
        rung = cal.rungs[value]
        return ProfileSpec(
            name=rung.name,
            index=rung.index,
            context_strategy=rung.strategy,
            top_k=rung.top_k,
            rung=rung,
        )
    if isinstance(value, float):
        rung = cal.rungs[_resolve_float_index(value, len(cal.rungs))]
        return ProfileSpec(
            name=rung.name,
            index=rung.index,
            context_strategy=rung.strategy,
            top_k=rung.top_k,
            rung=rung,
        )
    raise ValueError(
        "retrieval profile must be a name, integer rung, float slider, 'raw', or None"
    )


def _looks_like_float(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return "." in value


def default_profile_calibration() -> ProfileCalibration:
    """Return the active calibration artifact."""

    return load_profile_calibration()
