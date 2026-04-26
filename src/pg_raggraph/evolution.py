"""Evolution-aware scoring SQL fragments and helpers.

Centralizes the new SQL terms introduced at Tier 1 so retrieval.py
templates stay readable. Each fragment is NULL-safe — when evolution
columns are NULL, the term collapses to a neutral value and the overall
retrieval score reduces to today's three-leg hybrid.
"""

from __future__ import annotations

import itertools
from datetime import datetime
from typing import Any

from pg_raggraph.config import PGRGConfig


def _effective_tier(cfg: PGRGConfig, evolution_aware: bool | None) -> str:
    """Resolve tier after applying the per-query evolution_aware override."""
    if evolution_aware is False:
        return "off"
    return cfg.evolution_tier


def temporal_boost_expr(doc_alias: str = "d") -> str:
    """SQL fragment: exp(-ln(2) * age_years / half_life). Neutral when
    effective_from is NULL (falls back to created_at then now() → 0 years
    old → 1.0 boost). Parameterized via bind params :half_life_years in the
    outer query."""
    return (
        "exp(-0.6931471805599453 * "
        "EXTRACT(EPOCH FROM (now() - "
        f"COALESCE({doc_alias}.effective_from, {doc_alias}.created_at, now())"
        ")) / (365.25 * 86400 * %(half_life_years)s))"
    )


def retraction_filter_expr(doc_alias: str = "d") -> str:
    """SQL fragment: 1 if doc not retracted, 0 if retracted. NULL retracted
    treated as false (postgres default)."""
    return f"(CASE WHEN {doc_alias}.retracted THEN 0 ELSE 1 END)"


def supersession_penalty_expr(doc_alias: str = "d") -> str:
    """Document-level supersession penalty. A document is superseded if it
    appears in document_versions.supersedes_document_id. Neutral (1.0) when
    no supersession exists. Tier 1 implements at document granularity;
    Tier 3 layers fact-level supersession on top."""
    return (
        "(CASE WHEN EXISTS (SELECT 1 FROM document_versions dv "
        f"                  WHERE dv.supersedes_document_id = {doc_alias}.id) "
        "      THEN (1 - %(lambda_supersession)s) "
        "      ELSE 1.0 END)"
    )


def evolution_score_expr(
    base_score_sql: str,
    cfg: PGRGConfig,
    evolution_aware: bool | None = None,
) -> str:
    """Wrap a base score expression with temporal + supersession terms,
    plus an optional hard retraction multiplier. Gate: only applied when
    the effective tier (after `evolution_aware` override) is not 'off'.

    The `retraction_filter_expr` multiplier is only applied under
    `retracted_behavior == "hide"` — there as defense-in-depth alongside
    the WHERE clause. Under `"flag"` and `"surface_both"`, retracted docs
    keep their natural rank so the caller can decide what to do.
    """
    tier = _effective_tier(cfg, evolution_aware)
    if tier == "off":
        return base_score_sql
    body = (
        f"  {base_score_sql}"
        f"  + %(w_recent)s * {temporal_boost_expr()}"
        f"  + %(w_supersession)s  * {supersession_penalty_expr()}"
    )
    if cfg.retracted_behavior == "hide":
        return f"({retraction_filter_expr()} * ({body}))"
    return f"({body})"


def evolution_where_clauses(
    cfg: PGRGConfig,
    doc_alias: str = "d",
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
) -> tuple[list[str], dict]:
    """Returns (where_clauses, bind_params_for_clauses) based on evolution
    behavior modes plus per-query overrides. Caller joins clauses with
    ' AND ' when composing. Empty list when the effective tier is 'off'.

    Current fragments:
      - retracted_behavior='hide' → filter out retracted documents.
      - supersession_behavior='hide' → filter out documents that have been
        superseded by a newer document (per document_versions pointer).
      - as_of=DATE → filter to documents whose effective window covers the
        given timestamp.
      - version_filter='X' → restrict to documents with version_label='X'.

    Other modes ('flag', 'prefer_new', 'surface_both') return no filter —
    'flag' annotates results; 'prefer_new' relies on the SQL scoring penalty
    in evolution_score_expr; 'surface_both' is deferred to Tier 3.
    """
    tier = _effective_tier(cfg, evolution_aware)
    if tier == "off":
        return [], {}
    clauses: list[str] = []
    params: dict = {}
    if cfg.retracted_behavior == "hide":
        clauses.append(f"NOT {doc_alias}.retracted")
    if cfg.supersession_behavior == "hide":
        clauses.append(
            f"NOT EXISTS (SELECT 1 FROM document_versions dv "
            f"            WHERE dv.supersedes_document_id = {doc_alias}.id)"
        )
    if as_of is not None:
        if as_of.tzinfo is None:
            raise ValueError(
                "as_of must be timezone-aware "
                "(e.g., datetime(..., tzinfo=timezone.utc)); "
                "naive datetimes silently misbehave against timestamptz columns"
            )
        clauses.append(
            f"(({doc_alias}.effective_from IS NULL "
            f"  OR {doc_alias}.effective_from <= %(as_of)s) "
            f" AND ({doc_alias}.effective_to IS NULL "
            f"      OR {doc_alias}.effective_to > %(as_of)s))"
        )
        params["as_of"] = as_of
    if version_filter is not None:
        clauses.append(f"{doc_alias}.version_label = %(version_filter)s")
        params["version_filter"] = version_filter
    return clauses, params


def evolution_bind_params(cfg: PGRGConfig) -> dict:
    """Bind-param dict to merge into retrieval query params."""
    return {
        "w_recent": cfg.w_recent,
        "w_supersession": cfg.w_supersession,
        "half_life_years": cfg.temporal_half_life_years,
        "lambda_supersession": cfg.lambda_supersession,
    }


async def tune_scoring_weights(
    rag,
    *,
    namespace: str,
    gold: list[dict],
    grid: dict[str, list[float]],
    mode: str = "naive",
    write_back: bool = True,
) -> dict[str, Any]:
    """Grid-search scoring weights against a gold QA set.

    Parameters
    ----------
    rag : GraphRAG
        Connected GraphRAG instance.
    namespace : str
        Corpus namespace to query.
    gold : list[dict]
        Each dict has keys 'question' and 'expected_substring' (case-
        insensitive substring match on the top-K retrieved chunk contents).
        Minimal shape for Tier 1 — Tier 3 swaps in an LLM-judge version.
    grid : dict[str, list[float]]
        Weight-name to list-of-values. Cartesian product is evaluated.
        Supported weight names: w_sem, w_bm25, w_graph, w_recent, w_supersession.
    mode : str
        Retrieval mode (naive | local | global | hybrid | smart).
    write_back : bool
        If True, rag.config is updated to the best cell.

    Returns
    -------
    dict
        {"best": {"weights": {...}, "score": N}, "cells": [{"weights":.., "score":..}, ...]}
    """
    weight_names = list(grid.keys())
    # PGRGConfig isn't frozen and doesn't validate_assignment, so a typo'd
    # weight name would silently create a new attribute and leave the real
    # weight unchanged. Fail loudly at the boundary instead.
    known_fields = set(PGRGConfig.model_fields.keys())
    unknown = [n for n in weight_names if n not in known_fields]
    if unknown:
        raise ValueError(
            f"Unknown weight names in grid: {unknown}. "
            f"Must be PGRGConfig field names (e.g., w_sem, w_bm25, w_graph, "
            f"w_recent, w_supersession)."
        )

    value_lists = [grid[n] for n in weight_names]
    cells: list[dict] = []

    # Snapshot existing config so we can restore on exception or write_back=False.
    original = {n: getattr(rag.config, n) for n in weight_names}

    try:
        for combo in itertools.product(*value_lists):
            for name, val in zip(weight_names, combo):
                setattr(rag.config, name, val)

            score = 0
            for item in gold:
                result = await rag.query(item["question"], namespace=namespace, mode=mode)
                joined = " ".join(c.content.lower() for c in result.chunks)
                if item["expected_substring"].lower() in joined:
                    score += 1

            cells.append(
                {
                    "weights": {n: v for n, v in zip(weight_names, combo)},
                    "score": score,
                }
            )

        best = max(cells, key=lambda c: c["score"])

        if write_back:
            for name, val in best["weights"].items():
                setattr(rag.config, name, val)
        else:
            for name, val in original.items():
                setattr(rag.config, name, val)
    except BaseException:
        # On any failure mid-grid, restore the snapshot so the caller's
        # config isn't left holding a partial combo.
        for name, val in original.items():
            setattr(rag.config, name, val)
        raise

    return {"best": best, "cells": cells}
