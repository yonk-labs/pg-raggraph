"""Evolution-aware scoring SQL fragments and helpers.

Centralizes the new SQL terms introduced at Tier 1 so retrieval.py
templates stay readable. Each fragment is NULL-safe — when evolution
columns are NULL, the term collapses to a neutral value and the overall
retrieval score reduces to today's three-leg hybrid.
"""

from __future__ import annotations

from pg_raggraph.config import PGRGConfig


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


def evolution_score_expr(base_score_sql: str, cfg: PGRGConfig) -> str:
    """Wrap a base score expression with retraction filter + temporal +
    supersession terms. Gate: only applied when evolution_tier != 'off'."""
    if cfg.evolution_tier == "off":
        return base_score_sql
    return (
        f"({retraction_filter_expr()} * ("
        f"  {base_score_sql}"
        f"  + %(w_recent)s * {temporal_boost_expr()}"
        f"  + %(w_supersession)s  * {supersession_penalty_expr()}"
        f"))"
    )


def evolution_where_clauses(cfg: PGRGConfig, doc_alias: str = "d") -> list[str]:
    """Returns a list of WHERE-clause fragments to apply based on evolution
    behavior modes. Caller joins with ' AND ' when composing. Empty list
    when evolution_tier='off'.

    Current fragments:
      - retracted_behavior='hide' → filter out retracted documents.
      - supersession_behavior='hide' → filter out documents that have been
        superseded by a newer document (per document_versions pointer).

    Other modes ('flag', 'prefer_new', 'surface_both') return no filter —
    'flag' annotates results; 'prefer_new' relies on the SQL scoring penalty
    in evolution_score_expr; 'surface_both' is deferred to Tier 3.
    """
    if cfg.evolution_tier == "off":
        return []
    clauses: list[str] = []
    if cfg.retracted_behavior == "hide":
        clauses.append(f"NOT {doc_alias}.retracted")
    if cfg.supersession_behavior == "hide":
        clauses.append(
            f"NOT EXISTS (SELECT 1 FROM document_versions dv "
            f"            WHERE dv.supersedes_document_id = {doc_alias}.id)"
        )
    return clauses


def evolution_bind_params(cfg: PGRGConfig) -> dict:
    """Bind-param dict to merge into retrieval query params."""
    return {
        "w_recent": cfg.w_recent,
        "w_supersession": cfg.w_supersession,
        "half_life_years": cfg.temporal_half_life_years,
        "lambda_supersession": cfg.lambda_supersession,
    }
