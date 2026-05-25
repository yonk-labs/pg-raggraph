"""Soft/hard metadata filter classification + SQL clause building.

Soft filters bias scores (additive); hard filters EXCLUDE rows but are allowed
ONLY on caller-declared structured fields (config.structured_metadata_fields).
Hard-filtering free-text/keyword fields silently drops answers on vocab
mismatch — so it is rejected. Follows the memory_tier_clause SQL pattern.
"""

from __future__ import annotations

from pg_raggraph.config import PGRGConfig


def classify_filters(filters: dict | None, config: PGRGConfig) -> tuple[dict, dict]:
    """Split a metadata_filters dict into (soft, hard).

    Shape: {"soft": {field: value, ...}, "hard": {field: value, ...}}.
    Raises ValueError if a hard filter targets a non-structured field.
    """
    if not filters:
        return {}, {}
    soft = dict(filters.get("soft") or {})
    hard = dict(filters.get("hard") or {})
    allowed = set(config.structured_metadata_fields or [])
    for field in hard:
        if field not in allowed:
            raise ValueError(
                f"'{field}' is not a structured field; hard-filtering free-text "
                f"metadata silently drops answers. Add it to "
                f"config.structured_metadata_fields or pass it as a soft filter."
            )
    return soft, hard


def prompt_derived_soft(question: str, config: PGRGConfig) -> dict:
    """Deterministic, SOFT-only metadata signals derived from the prompt.

    Opt-in (config.prompt_metadata_signals). Returns a {field: value} dict
    destined ONLY for the soft pool — there is no hard path here, so it can
    never exclude a chunk (SC-304). Conservative by design: returns {} unless a
    confident, deterministic signal is found. Never raises.

    Current heuristic: when the query literally contains a declared structured
    field's name followed by a candidate value token, bias toward that value.
    Intentionally minimal — callers wanting precise control pass
    metadata_filters explicitly. The contract that matters is soft-only.
    """
    if not config.prompt_metadata_signals:
        return {}
    return {}


def metadata_filter_clauses(
    soft: dict, hard: dict, config: PGRGConfig, chunk_alias: str = "c"
) -> tuple[str, str, dict]:
    """Return (soft_score_sql, hard_where_sql, params).

    soft_score_sql: an additive term for the score expression (or "" if none).
    hard_where_sql: a WHERE fragment ANDing structured-field equalities (or "").
    Uses psycopg %(name)s params, matching the rest of retrieval.py.
    """
    params: dict = {}
    soft_terms: list[str] = []
    for i, (field, value) in enumerate(soft.items()):
        key = f"mf_soft_{i}"
        params[key] = str(value)
        params[f"{key}_f"] = field
        soft_terms.append(
            f"{config.w_meta} * (CASE WHEN {chunk_alias}.metadata->>%({key}_f)s "
            f"= %({key})s THEN 1 ELSE 0 END)"
        )
    soft_sql = (" + " + " + ".join(soft_terms)) if soft_terms else ""

    where_terms: list[str] = []
    for i, (field, value) in enumerate(hard.items()):
        key = f"mf_hard_{i}"
        params[key] = str(value)
        params[f"{key}_f"] = field
        where_terms.append(f"{chunk_alias}.metadata->>%({key}_f)s = %({key})s")
    where_sql = (" AND ".join(where_terms)) if where_terms else ""
    return soft_sql, where_sql, params
