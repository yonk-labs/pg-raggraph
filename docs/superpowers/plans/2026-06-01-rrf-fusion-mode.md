# RRF Fusion Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, default-off Reciprocal Rank Fusion (RRF) mode (`fusion="rrf"`) alongside the current linear weighted score fusion, scoped to the `naive` and `hybrid` retrieval paths, with a per-call override on `query()`/`ask()`.

**Architecture:** Two new config knobs (`fusion`, `rrf_k`). Naive RRF restructures the four naive SQL builders into a `scored → ranked → fuse` CTE chain (window `rank()` over the existing `vec_score`/`bm25_score`), **re-joining `documents d`** at the outer level so `evolution_score_expr` keeps its `d.`-qualified columns. Hybrid RRF replaces the Python max-score merge with rank-fusion across the local+global result lists. Design decision (locked in the mission brief): RRF ranks the base vec/bm25 legs, then `evolution_score_expr` applies its temporal/supersession/retraction terms on the fused expression — preserving RRF's scale-invariance. The linear path is left **physically untouched** (RRF is an early branch), making "linear byte-identical" trivially true.

**Tech Stack:** Python 3.12+, psycopg async, PostgreSQL 16 + pgvector/pg_trgm, pytest + pytest-asyncio, ruff, uv.

**Mission Brief:** `skill-output/mission-brief/Mission-Brief-rrf-fusion-mode.md` — re-read at each ⛔ Drift Check below.

**Branch:** Create `feat/rrf-fusion` off the current `chunkshop-0.6-integration` HEAD (`0aba1e0`). Do **NOT** branch off the issue's stale base `8efbba14`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/pg_raggraph/config.py` | `fusion` + `rrf_k` knobs | Modify (~line 482) |
| `src/pg_raggraph/retrieval.py` | `_effective_fusion` + `_rrf_fused_base_expr` helpers; RRF branch in 4 naive builders; `_rrf_merge` helper; `fusion` param on `query()`; bind `rrf_k`; hybrid branch | Modify |
| `src/pg_raggraph/__init__.py` | `fusion` param on public `query()` + `ask()`, pass-through | Modify |
| `tests/unit/test_rrf_fusion.py` | helper resolution, fused-expr, naive SQL shape, linear-unchanged guard, `_rrf_merge` reorder | Create |
| `tests/integration/test_rrf_fusion_it.py` | naive RRF reorder + hybrid RRF end-to-end on PG :5434 | Create |
| `benchmarks/musique/` (or `benchmarks/e2e/`) | A/B linear-vs-rrf runner over existing snapshot | Modify/Create small runner |
| `CHANGELOG.md` | additive default-off note | Modify |
| `docs/cookbook/` | short RRF usage note | Create/Modify |

**Design note carried from the brief (do not re-derive):** There is no single "hybrid builder." Hybrid = `_build_local_query` + `_build_global_query` run separately and merged in Python (`retrieval.py:854-882`). The graph leg in local/global is the constant `%(w_graph)s * 1.0`, so it cannot be rank-fused in SQL — the graph signal lives in *which list* a chunk came from, visible only to the Python merge. Hence: naive RRF = SQL; hybrid RRF = Python.

---

## Task 1: Config knobs (`fusion`, `rrf_k`)

**Files:**
- Modify: `src/pg_raggraph/config.py` (after line 482, the `w_graph` field)
- Test: `tests/unit/test_rrf_fusion.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_rrf_fusion.py`:

```python
"""Unit tests for the optional RRF (Reciprocal Rank Fusion) mode (issue #57).

Covers config knobs, helper resolution, the fused-score expression, naive
SQL shape, the linear-unchanged guard, and the Python hybrid merge. End-to-end
ordering is covered by tests/integration/test_rrf_fusion_it.py.
"""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig


def test_fusion_defaults_to_linear():
    assert PGRGConfig().fusion == "linear"


def test_rrf_k_default_is_60():
    assert PGRGConfig().rrf_k == 60


def test_fusion_accepts_rrf():
    cfg = PGRGConfig(fusion="rrf")
    assert cfg.fusion == "rrf"


def test_fusion_rejects_unknown():
    with pytest.raises(ValueError):
        PGRGConfig(fusion="bogus")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -v`
Expected: FAIL — `PGRGConfig` has no `fusion` / `rrf_k` field (or accepts `bogus`).

- [ ] **Step 3: Add the config fields**

In `src/pg_raggraph/config.py`, immediately after line 482 (`w_graph: float = 0.20`), add:

```python

    # Fusion strategy for hybrid retrieval (issue #57). "linear" (default)
    # preserves the weighted-sum behavior byte-for-byte; "rrf" fuses by
    # per-leg rank (Σ wᵢ / (rrf_k + rankᵢ)), which is scale-free across the
    # cosine / ts_rank legs. Applies to naive + hybrid modes only.
    fusion: Literal["linear", "rrf"] = "linear"
    rrf_k: int = 60  # RRF damping constant (standard default)
```

(`Literal` is already imported in config.py — it is used by `evolution_tier` at line 474.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/config.py tests/unit/test_rrf_fusion.py
git commit -m "feat(config): add fusion + rrf_k knobs (issue #57, default-off)"
```

---

## Task 2: `_effective_fusion` + `_rrf_fused_base_expr` helpers

**Files:**
- Modify: `src/pg_raggraph/retrieval.py` (add helpers near `_effective_retrieval_strategy`, line 90)
- Test: `tests/unit/test_rrf_fusion.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_rrf_fusion.py`:

```python
from pg_raggraph.retrieval import _effective_fusion, _rrf_fused_base_expr


def test_effective_fusion_none_falls_back_to_config():
    assert _effective_fusion(PGRGConfig(fusion="rrf"), None) == "rrf"
    assert _effective_fusion(PGRGConfig(), None) == "linear"


def test_effective_fusion_override_wins():
    cfg = PGRGConfig(fusion="linear")
    assert _effective_fusion(cfg, "rrf") == "rrf"
    assert _effective_fusion(cfg, "linear") == "linear"


def test_effective_fusion_invalid_raises():
    with pytest.raises(ValueError, match="Invalid fusion"):
        _effective_fusion(PGRGConfig(), "bogus")


def test_rrf_fused_base_expr_shape():
    expr = _rrf_fused_base_expr()
    # Both legs fused by rank, weighted, damped by rrf_k. Graph term dropped.
    assert "%(w_sem)s" in expr and "vec_rank" in expr
    assert "%(w_bm25)s" in expr and "bm25_rank" in expr
    assert "%(rrf_k)s" in expr
    assert "graph" not in expr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k "fusion or fused" -v`
Expected: FAIL — `ImportError: cannot import name '_effective_fusion'`.

- [ ] **Step 3: Add the helpers**

In `src/pg_raggraph/retrieval.py`, after `_effective_retrieval_strategy` (ends line 103), add:

```python
_FUSION_VALUES = ("linear", "rrf")


def _effective_fusion(cfg: PGRGConfig, override: str | None) -> str:
    """Resolve the fusion mode after applying the per-query override.

    ``None`` falls back to ``cfg.fusion`` (``"linear"`` by default —
    backward-compatible). Validates against the Literal set.
    """
    if override is None:
        return cfg.fusion
    if override not in _FUSION_VALUES:
        raise ValueError(f"Invalid fusion {override!r}. Must be one of: {_FUSION_VALUES}")
    return override


def _rrf_fused_base_expr() -> str:
    """RRF base-score SQL fragment: Σ wᵢ / (rrf_k + rankᵢ) over the vec + bm25
    legs. Replaces the linear weighted-sum ``base`` as the argument to
    ``evolution_score_expr`` so evolution decay applies as an outer term
    (issue #57). The naive path has no graph leg, so the graph term is
    dropped. ``vec_rank``/``bm25_rank`` are produced by the ``ranked`` CTE.
    """
    return (
        "%(w_sem)s / (%(rrf_k)s + vec_rank) + "
        "%(w_bm25)s / (%(rrf_k)s + bm25_rank)"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k "fusion or fused" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/retrieval.py tests/unit/test_rrf_fusion.py
git commit -m "feat(retrieval): add _effective_fusion + _rrf_fused_base_expr helpers"
```

⛔ **Drift Check DC-001:** Re-read the mission brief. Verify SC-001/SC-002 are progressing and the override uses the existing `_effective_*` pattern (it mirrors `_effective_retrieval_strategy` exactly). No builder behavior changed yet. Confirm before continuing.

---

## Task 3: RRF branch in `_build_naive_query` (single-pass reference impl)

**Files:**
- Modify: `src/pg_raggraph/retrieval.py:154-206` (`_build_naive_query`)
- Test: `tests/unit/test_rrf_fusion.py`

This is the reference transformation. The three other naive builders (Tasks 4-6) apply the same pattern to their CTE shapes.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_rrf_fusion.py`:

```python
from pg_raggraph.retrieval import _build_naive_query


def test_naive_linear_sql_unchanged_shape():
    """SC-006: default (linear) path must NOT contain any RRF machinery."""
    sql, _ = _build_naive_query(PGRGConfig())  # fusion defaults to linear
    assert "rank()" not in sql
    assert "WITH scored AS" not in sql
    assert "ORDER BY score DESC" in sql


def test_naive_rrf_emits_ranked_cte():
    """SC-003: RRF path wraps the legs in a ranked CTE and fuses by rank."""
    sql, _ = _build_naive_query(PGRGConfig(), fusion="rrf")
    assert "WITH scored AS" in sql
    assert "rank() OVER (ORDER BY vec_score DESC)" in sql
    assert "rank() OVER (ORDER BY bm25_score DESC)" in sql
    assert "%(rrf_k)s" in sql
    # evolution re-joins documents at the outer level so d.* stays in scope
    assert "JOIN documents d ON d.id = r.document_id" in sql
    assert "ORDER BY score DESC" in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k "naive" -v`
Expected: FAIL — `_build_naive_query()` got an unexpected keyword `fusion` (and no ranked CTE).

- [ ] **Step 3: Add the `fusion` param + RRF early branch**

In `_build_naive_query`, change the signature to add a trailing keyword param, and insert an RRF branch **before** the existing linear `base = (...)` block so the linear code below is left physically unchanged. The function currently starts (line 154):

```python
def _build_naive_query(
    cfg: PGRGConfig,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
    mf_soft_sql: str = "",
    mf_hard_sql: str = "",
) -> tuple[str, dict]:
    base = (
```

Replace the signature's closing line and add the branch so it reads:

```python
    mf_soft_sql: str = "",
    mf_hard_sql: str = "",
    fusion: str = "linear",
) -> tuple[str, dict]:
    if fusion == "rrf":
        return _build_naive_query_rrf(
            cfg, as_of, version_filter, evolution_aware, retracted_behavior,
            supersession_behavior, memory_tier, mf_soft_sql, mf_hard_sql,
        )
    base = (
```

(Everything from `base = (` downward stays byte-identical — that guarantees SC-006.)

Now add the RRF builder immediately after `_build_naive_query` returns (after line 206):

```python
def _build_naive_query_rrf(
    cfg: PGRGConfig,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
    mf_soft_sql: str = "",
    mf_hard_sql: str = "",
) -> tuple[str, dict]:
    """RRF variant of ``_build_naive_query`` (issue #57). The base legs
    (vec_score, bm25_score) are SELECTed in a ``scored`` CTE, rank()-ed in a
    ``ranked`` CTE, then fused by ``_rrf_fused_base_expr()``. The outer SELECT
    re-joins ``documents d`` so ``evolution_score_expr`` keeps its d.* columns
    (temporal_boost_expr reads d.effective_from / d.created_at). The mf_soft
    bias term is intentionally dropped under RRF — soft metadata bias is a
    score-scale nudge that has no meaning once we fuse by rank.
    """
    rrf_base = _rrf_fused_base_expr()
    clauses, extra_params = evolution_where_clauses(
        cfg,
        doc_alias="d",
        as_of=as_of,
        version_filter=version_filter,
        evolution_aware=evolution_aware,
        retracted_behavior=retracted_behavior,
        supersession_behavior=supersession_behavior,
    )
    mt_clause, mt_params = memory_tier_clause(cfg, chunk_alias="c", override=memory_tier)
    if mt_clause:
        clauses.append(mt_clause)
        extra_params = _merge_params(extra_params, mt_params)
    if mf_hard_sql:
        clauses.append(mf_hard_sql)
    extra_where = (" AND " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
WITH scored AS (
    SELECT c.id, COALESCE(c.embedded_content, c.content) AS content, c.metadata,
           c.document_id,
           1 - (c.embedding <=> %(embedding)s::vector) AS vec_score,
           ts_rank(c.search_vector, to_tsquery('english', %(tsquery)s)) AS bm25_score
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.namespace = %(namespace)s{extra_where}
),
ranked AS (
    SELECT scored.*,
           rank() OVER (ORDER BY vec_score DESC) AS vec_rank,
           rank() OVER (ORDER BY bm25_score DESC) AS bm25_rank
    FROM scored
)
SELECT r.id, r.content, r.metadata,
       d.source_path,
       d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       r.vec_score, r.bm25_score,
       {evolution_score_expr(rrf_base, cfg, evolution_aware, retracted_behavior)} AS score
FROM ranked r
JOIN documents d ON d.id = r.document_id
ORDER BY score DESC
LIMIT %(top_k)s
"""
    return sql, extra_params
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k "naive" -v`
Expected: PASS (both `linear_unchanged` and `rrf_emits_ranked_cte`).

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/retrieval.py tests/unit/test_rrf_fusion.py
git commit -m "feat(retrieval): RRF variant of single-pass naive builder (issue #57)"
```

---

## Task 4: RRF branch in `_build_naive_query_twostage`

**Files:**
- Modify: `src/pg_raggraph/retrieval.py:209-290`
- Test: `tests/unit/test_rrf_fusion.py`

- [ ] **Step 1: Write the failing test**

```python
from pg_raggraph.retrieval import _build_naive_query_twostage


def test_twostage_rrf_keeps_candidate_cte_and_ranks():
    sql, _ = _build_naive_query_twostage(PGRGConfig(), fusion="rrf")
    # Stage-1 bare-distance ORDER BY preserved for HNSW eligibility (SC-003).
    assert "ORDER BY c.embedding <=> %(embedding)s::vector" in sql
    assert "LIMIT %(candidate_k)s" in sql
    # Then rank-fused.
    assert "rank() OVER (ORDER BY vec_score DESC)" in sql
    assert "%(rrf_k)s" in sql


def test_twostage_linear_unchanged():
    sql, _ = _build_naive_query_twostage(PGRGConfig())
    assert "rank()" not in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k twostage -v`
Expected: FAIL — unexpected keyword `fusion`.

- [ ] **Step 3: Add `fusion` param + RRF branch**

Add `fusion: str = "linear"` as the trailing param of `_build_naive_query_twostage` (after `mf_hard_sql`), and insert the early branch before its `base = (` line:

```python
    fusion: str = "linear",
) -> tuple[str, dict]:
    """..."""  # keep existing docstring
    if fusion == "rrf":
        return _build_naive_query_twostage_rrf(
            cfg, as_of, version_filter, evolution_aware, retracted_behavior,
            supersession_behavior, memory_tier, mf_soft_sql, mf_hard_sql,
        )
    base = (
```

Then add the RRF builder. It keeps the stage-1 `candidates` CTE verbatim (preserving HNSW eligibility), and replaces the outer single-level SELECT with `scored → ranked → fuse`, re-joining `documents d`:

```python
def _build_naive_query_twostage_rrf(
    cfg: PGRGConfig,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
    mf_soft_sql: str = "",
    mf_hard_sql: str = "",
) -> tuple[str, dict]:
    """RRF variant of the two-stage naive builder. Stage-1 candidate CTE is
    unchanged (bare-distance ORDER BY → HNSW). Stage-2 re-scores via RRF rank
    fusion over the candidate pool, re-joining documents for evolution columns.
    """
    rrf_base = _rrf_fused_base_expr()
    clauses, extra_params = evolution_where_clauses(
        cfg, doc_alias="d", as_of=as_of, version_filter=version_filter,
        evolution_aware=evolution_aware, retracted_behavior=retracted_behavior,
        supersession_behavior=supersession_behavior,
    )
    mt_clause, mt_params = memory_tier_clause(cfg, chunk_alias="c", override=memory_tier)
    if mt_clause:
        clauses.append(mt_clause)
        extra_params = _merge_params(extra_params, mt_params)
    if mf_hard_sql:
        clauses.append(mf_hard_sql)
    extra_where = (" AND " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
WITH candidates AS (
    SELECT c.id, c.embedding, c.search_vector,
           COALESCE(c.embedded_content, c.content) AS content,
           c.metadata, c.document_id
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.namespace = %(namespace)s{extra_where}
    ORDER BY c.embedding <=> %(embedding)s::vector
    LIMIT %(candidate_k)s
),
scored AS (
    SELECT cand.id, cand.content, cand.metadata, cand.document_id,
           1 - (cand.embedding <=> %(embedding)s::vector) AS vec_score,
           ts_rank(cand.search_vector, to_tsquery('english', %(tsquery)s)) AS bm25_score
    FROM candidates cand
),
ranked AS (
    SELECT scored.*,
           rank() OVER (ORDER BY vec_score DESC) AS vec_rank,
           rank() OVER (ORDER BY bm25_score DESC) AS bm25_rank
    FROM scored
)
SELECT r.id, r.content, r.metadata,
       d.source_path,
       d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       r.vec_score, r.bm25_score,
       {evolution_score_expr(rrf_base, cfg, evolution_aware, retracted_behavior)} AS score
FROM ranked r
JOIN documents d ON d.id = r.document_id
ORDER BY score DESC
LIMIT %(top_k)s
"""
    return sql, extra_params
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k twostage -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/retrieval.py tests/unit/test_rrf_fusion.py
git commit -m "feat(retrieval): RRF variant of two-stage naive builder (issue #57)"
```

---

## Task 5: RRF branch in `_build_naive_prefilter`

**Files:**
- Modify: `src/pg_raggraph/retrieval.py:293-363`
- Test: `tests/unit/test_rrf_fusion.py`

- [ ] **Step 1: Write the failing test**

```python
from pg_raggraph.retrieval import _build_naive_prefilter


def test_prefilter_rrf_keeps_filtered_cte_and_ranks():
    sql, _ = _build_naive_prefilter(PGRGConfig(), fusion="rrf")
    assert "WITH filtered AS" in sql
    # pre_filter must still NOT order by vector in the CTE.
    assert "ORDER BY c.embedding" not in sql
    assert "rank() OVER (ORDER BY vec_score DESC)" in sql


def test_prefilter_linear_unchanged():
    sql, _ = _build_naive_prefilter(PGRGConfig())
    assert "rank()" not in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k prefilter -v`
Expected: FAIL — unexpected keyword `fusion`.

- [ ] **Step 3: Add `fusion` param + RRF branch**

Add `fusion: str = "linear"` trailing param to `_build_naive_prefilter` and the early branch before its `base = (` line (calling `_build_naive_prefilter_rrf` with the same arg list as the other RRF dispatchers). Then add:

```python
def _build_naive_prefilter_rrf(
    cfg: PGRGConfig,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
    mf_soft_sql: str = "",
    mf_hard_sql: str = "",
) -> tuple[str, dict]:
    """RRF variant of the pre_filter naive builder. The ``filtered`` CTE
    materializes the predicate subset (no vector ORDER BY), then RRF ranks
    over that subset."""
    rrf_base = _rrf_fused_base_expr()
    clauses, extra_params = evolution_where_clauses(
        cfg, doc_alias="d", as_of=as_of, version_filter=version_filter,
        evolution_aware=evolution_aware, retracted_behavior=retracted_behavior,
        supersession_behavior=supersession_behavior,
    )
    mt_clause, mt_params = memory_tier_clause(cfg, chunk_alias="c", override=memory_tier)
    if mt_clause:
        clauses.append(mt_clause)
        extra_params = _merge_params(extra_params, mt_params)
    if mf_hard_sql:
        clauses.append(mf_hard_sql)
    extra_where = (" AND " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
WITH filtered AS (
    SELECT c.id, c.embedding, c.search_vector,
           COALESCE(c.embedded_content, c.content) AS content,
           c.metadata, c.document_id
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.namespace = %(namespace)s{extra_where}
),
scored AS (
    SELECT cand.id, cand.content, cand.metadata, cand.document_id,
           1 - (cand.embedding <=> %(embedding)s::vector) AS vec_score,
           ts_rank(cand.search_vector, to_tsquery('english', %(tsquery)s)) AS bm25_score
    FROM filtered cand
),
ranked AS (
    SELECT scored.*,
           rank() OVER (ORDER BY vec_score DESC) AS vec_rank,
           rank() OVER (ORDER BY bm25_score DESC) AS bm25_rank
    FROM scored
)
SELECT r.id, r.content, r.metadata,
       d.source_path,
       d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       r.vec_score, r.bm25_score,
       {evolution_score_expr(rrf_base, cfg, evolution_aware, retracted_behavior)} AS score
FROM ranked r
JOIN documents d ON d.id = r.document_id
ORDER BY score DESC
LIMIT %(top_k)s
"""
    return sql, extra_params
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k prefilter -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/retrieval.py tests/unit/test_rrf_fusion.py
git commit -m "feat(retrieval): RRF variant of pre_filter naive builder (issue #57)"
```

---

## Task 6: RRF branch in `_build_naive_vector_first`

**Files:**
- Modify: `src/pg_raggraph/retrieval.py:366-445`
- Test: `tests/unit/test_rrf_fusion.py`

- [ ] **Step 1: Write the failing test**

```python
from pg_raggraph.retrieval import _build_naive_vector_first


def test_vector_first_rrf_keeps_bare_hnsw_cte_and_postfilter():
    sql, _ = _build_naive_vector_first(PGRGConfig(), fusion="rrf")
    # Bare HNSW seed CTE preserved (no namespace join in the candidates CTE).
    assert "LIMIT %(vector_first_k)s" in sql
    assert "rank() OVER (ORDER BY vec_score DESC)" in sql
    # Namespace post-filter must still apply (it moves into the scored CTE).
    assert "WHERE d.namespace = %(namespace)s" in sql


def test_vector_first_linear_unchanged():
    sql, _ = _build_naive_vector_first(PGRGConfig())
    assert "rank()" not in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k vector_first -v`
Expected: FAIL — unexpected keyword `fusion`.

- [ ] **Step 3: Add `fusion` param + RRF branch**

Add `fusion: str = "linear"` trailing param + early branch to `_build_naive_vector_first`. The vector_first post-filter (namespace + predicates) currently lives in the **outer** WHERE; under RRF it must move into the `scored` CTE so ranking happens over the post-filtered set (ranking the off-namespace HNSW seeds would corrupt ranks). Note the `cand` alias for memory_tier matches the existing builder:

```python
def _build_naive_vector_first_rrf(
    cfg: PGRGConfig,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
    mf_soft_sql: str = "",
    mf_hard_sql: str = "",
) -> tuple[str, dict]:
    """RRF variant of the vector_first naive builder. The bare HNSW seed CTE
    is unchanged; the namespace/evolution post-filter moves into the scored
    CTE so RRF ranks only post-filtered rows."""
    rrf_base = _rrf_fused_base_expr()
    clauses, extra_params = evolution_where_clauses(
        cfg, doc_alias="d", as_of=as_of, version_filter=version_filter,
        evolution_aware=evolution_aware, retracted_behavior=retracted_behavior,
        supersession_behavior=supersession_behavior,
    )
    mt_clause, mt_params = memory_tier_clause(cfg, chunk_alias="cand", override=memory_tier)
    if mt_clause:
        clauses.append(mt_clause)
        extra_params = _merge_params(extra_params, mt_params)
    if mf_hard_sql:
        clauses.append(mf_hard_sql)
    extra_where = (" AND " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
WITH candidates AS (
    SELECT c.id, c.embedding, c.search_vector,
           COALESCE(c.embedded_content, c.content) AS content,
           c.metadata, c.document_id
    FROM chunks c
    ORDER BY c.embedding <=> %(embedding)s::vector
    LIMIT %(vector_first_k)s
),
scored AS (
    SELECT cand.id, cand.content, cand.metadata, cand.document_id,
           1 - (cand.embedding <=> %(embedding)s::vector) AS vec_score,
           ts_rank(cand.search_vector, to_tsquery('english', %(tsquery)s)) AS bm25_score
    FROM candidates cand
    JOIN documents d ON d.id = cand.document_id
    WHERE d.namespace = %(namespace)s{extra_where}
),
ranked AS (
    SELECT scored.*,
           rank() OVER (ORDER BY vec_score DESC) AS vec_rank,
           rank() OVER (ORDER BY bm25_score DESC) AS bm25_rank
    FROM scored
)
SELECT r.id, r.content, r.metadata,
       d.source_path,
       d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       r.vec_score, r.bm25_score,
       {evolution_score_expr(rrf_base, cfg, evolution_aware, retracted_behavior)} AS score
FROM ranked r
JOIN documents d ON d.id = r.document_id
ORDER BY score DESC
LIMIT %(top_k)s
"""
    return sql, extra_params
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k vector_first -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/retrieval.py tests/unit/test_rrf_fusion.py
git commit -m "feat(retrieval): RRF variant of vector_first naive builder (issue #57)"
```

---

## Task 7: Thread `fusion` + bind `rrf_k` in `retrieval.query()`

**Files:**
- Modify: `src/pg_raggraph/retrieval.py:633-822` (`query` signature, params dict, the 4 naive build calls)
- Test: `tests/unit/test_rrf_fusion.py` (string guard) + covered end-to-end in Task 9 integration

- [ ] **Step 1: Write the failing test**

```python
import inspect
from pg_raggraph.retrieval import query as retrieval_query


def test_query_exposes_fusion_param():
    sig = inspect.signature(retrieval_query)
    assert "fusion" in sig.parameters
    assert sig.parameters["fusion"].default is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k query_exposes -v`
Expected: FAIL — `fusion` not in signature.

- [ ] **Step 3: Thread the param**

In `retrieval.query()` (line 633), add a keyword-only param after `trace_emit` (line 651):

```python
    trace_emit: Callable[[dict], None] | None = None,
    fusion: str | None = None,
) -> QueryResult:
```

Resolve it once, right after the `valid_modes` check (line 661), before the summary/smart/naive_boost dispatch:

```python
    effective_fusion = _effective_fusion(config, fusion)
```

> **Scope note (Out of Scope per brief):** `summary`, `smart`, and `naive_boost` keep linear in v1. Do NOT pass `fusion` into `_summary_query` / `_smart_query` / `_naive_boost_query`. Only `mode="naive"` and `mode="hybrid"` honor it. Document this in the public docstring (Task 8).

Add `rrf_k` to the `params` dict (after `"w_graph": config.w_graph,`, line 741):

```python
        "w_graph": config.w_graph,
        "rrf_k": config.rrf_k,
```

(Binding `rrf_k` always is safe — the linear SQL never references `%(rrf_k)s`, and psycopg ignores unused mapping keys. The linear **SQL string** is unchanged, so SC-006 holds.)

In the four naive build calls (lines 772, 784, 799, 811), pass `fusion=effective_fusion` as the final argument. Example for the `else` branch at line 811:

```python
        else:
            sql, extra = _build_naive_query(
                config,
                as_of,
                version_filter,
                evolution_aware,
                retracted_behavior,
                supersession_behavior,
                memory_tier,
                mf_soft_sql,
                mf_hard_sql,
                fusion=effective_fusion,
            )
```

Apply the same `fusion=effective_fusion` addition to the `_build_naive_prefilter` (772), `_build_naive_vector_first` (784), and `_build_naive_query_twostage` (799) calls.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k query_exposes -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/retrieval.py tests/unit/test_rrf_fusion.py
git commit -m "feat(retrieval): thread fusion override + bind rrf_k in query()"
```

⛔ **Drift Check DC-002:** Re-read the mission brief. This is the highest-risk point. Verify SC-003 AND SC-006: run `uv run pytest tests/unit/test_rrf_fusion.py -v` — every `*_linear_unchanged` test must pass (linear SQL still has no `rank()`), and every RRF-shape test must pass. Confirm you did NOT thread `fusion` into summary/smart/naive_boost. Confirm before continuing.

---

## Task 8: Hybrid RRF merge (`_rrf_merge` helper + branch)

**Files:**
- Modify: `src/pg_raggraph/retrieval.py:854-882` (hybrid branch)
- Test: `tests/unit/test_rrf_fusion.py`

- [ ] **Step 1: Write the failing test**

This is the SC-007 reorder proof — DB-free, on the merge helper:

```python
from pg_raggraph.retrieval import _rrf_merge


def test_rrf_merge_reorders_vs_max_score():
    """SC-007: a chunk strong in BOTH lists outranks a chunk that is #1 in
    one list only — which max-score dedup would not achieve."""
    # local list ordered by score DESC; B is #1 local, A is #2 local.
    local = [{"id": "B", "score": 0.99}, {"id": "A", "score": 0.80}]
    # global list ordered by score DESC; A is #1 global, C is #2 global.
    global_ = [{"id": "A", "score": 0.70}, {"id": "C", "score": 0.65}]
    fused = _rrf_merge(local, global_, k=60, top_k=3)
    ids = [r["id"] for r in fused]
    # A appears in both lists (rank 2 local + rank 1 global) → highest RRF.
    assert ids[0] == "A"
    # Every returned row carries the fused RRF value as its score.
    assert all("score" in r for r in fused)
    assert fused[0]["score"] > fused[1]["score"]


def test_rrf_merge_respects_top_k():
    local = [{"id": str(i), "score": 1.0 - i / 10} for i in range(5)]
    fused = _rrf_merge(local, [], k=60, top_k=2)
    assert len(fused) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k rrf_merge -v`
Expected: FAIL — `cannot import name '_rrf_merge'`.

- [ ] **Step 3: Add the helper + wire the hybrid branch**

Add the helper near the other module helpers in `retrieval.py`:

```python
def _rrf_merge(
    local_rows: list, global_rows: list, k: int, top_k: int
) -> list:
    """Reciprocal Rank Fusion across two already-ranked result lists
    (issue #57). Each list is assumed ordered best-first, so list position
    is the rank. A chunk's fused score is Σ 1/(k + rank) over the lists it
    appears in (equal weights = textbook RRF). Returns dict rows sorted by
    fused score, trimmed to top_k, with the fused value written to ``score``.
    """
    fused: dict = {}
    for rows in (local_rows, global_rows):
        for rank, row in enumerate(rows, start=1):
            cid = row["id"]
            contrib = 1.0 / (k + rank)
            if cid in fused:
                fused[cid]["_rrf"] += contrib
            else:
                fused[cid] = {**dict(row), "_rrf": contrib}
    ordered = sorted(fused.values(), key=lambda r: r["_rrf"], reverse=True)[:top_k]
    for r in ordered:
        r["score"] = r.pop("_rrf")
    return ordered
```

In the hybrid branch (replace the dedup at lines 876-882), branch on `effective_fusion`:

```python
        local_rows = await db.fetch_all(local_sql, _merge_params(params, local_extra))
        global_rows = await db.fetch_all(global_sql, _merge_params(params, global_extra))
        if effective_fusion == "rrf":
            rows = _rrf_merge(local_rows, global_rows, config.rrf_k, effective_top_k)
        else:
            # Deduplicate by chunk ID, prefer higher score (linear — unchanged).
            seen = {}
            for row in local_rows + global_rows:
                cid = row["id"]
                if cid not in seen or row["score"] > seen[cid]["score"]:
                    seen[cid] = row
            rows = sorted(seen.values(), key=lambda r: r["score"], reverse=True)[
                :effective_top_k
            ]
```

> **Note on row type:** the existing code treats rows as mappings (`row["id"]`, `row["score"]`). `_rrf_merge` calls `dict(row)` so the result is mutable regardless of whether `db.fetch_all` returns `dict` or a row-mapping. If downstream consumers require the original row type, verify against `db.fetch_all`'s return type during integration (Task 9) and adjust the wrapper if needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_rrf_fusion.py -k rrf_merge -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pg_raggraph/retrieval.py tests/unit/test_rrf_fusion.py
git commit -m "feat(retrieval): hybrid RRF rank-fusion merge (issue #57)"
```

⛔ **Drift Check DC-003:** Re-read the mission brief. Verify SC-004/SC-005: hybrid fuses by rank, evolution stays inside each list's ordering (decay outside the base legs). Confirm local/global **standalone** modes were NOT modified (only the hybrid Python merge changed; `_build_local_query`/`_build_global_query` are untouched). Confirm before continuing.

---

## Task 9: Public `query()` + `ask()` pass-through + integration test

**Files:**
- Modify: `src/pg_raggraph/__init__.py:1694-1712` (`query`), `1843-1894` (`ask`)
- Test: `tests/integration/test_rrf_fusion_it.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_rrf_fusion_it.py` (follow the fixture conventions of `tests/integration/test_retrieval.py` — reuse its DB/ingest fixtures):

```python
"""Integration tests for RRF fusion (issue #57). Requires PG on :5434."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_naive_rrf_returns_results_and_differs(rag_with_corpus):
    """SC-002/SC-003: naive RRF runs end-to-end via the public override and
    can produce a different top-k order than linear on the same query."""
    rag = rag_with_corpus
    q = "the multi-hop bridge question"  # a query where vec and bm25 disagree
    linear = await rag.query(q, mode="naive", fusion="linear")
    rrf = await rag.query(q, mode="naive", fusion="rrf")
    assert linear.chunks and rrf.chunks
    # Both return results; ordering may differ (not asserting strict inequality
    # to avoid flakiness on tiny corpora — see the A/B bench for the real delta).


async def test_hybrid_rrf_runs(rag_with_corpus):
    """SC-004: hybrid RRF path executes and returns ranked chunks."""
    rag = rag_with_corpus
    res = await rag.query("entity relationship question", mode="hybrid", fusion="rrf")
    assert res.chunks
    assert all(c.score is not None for c in res.chunks)


async def test_rrf_with_evolution_on(rag_with_corpus_evolution):
    """SC-005: RRF + evolution_tier != 'off' executes (the outer documents
    re-join keeps d.effective_from / d.created_at in scope)."""
    rag = rag_with_corpus_evolution
    res = await rag.query("a dated fact", mode="naive", fusion="rrf")
    assert res.chunks
```

> If `rag_with_corpus` / `rag_with_corpus_evolution` fixtures don't already exist, reuse or adapt the corpus fixture from `tests/integration/test_retrieval.py`. For the evolution case, instantiate `GraphRAG` with `PGRGConfig(evolution_tier="structural")`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_rrf_fusion_it.py -v`
Expected: FAIL — public `query()` has no `fusion` kwarg (`TypeError`).

- [ ] **Step 3: Add `fusion` to public `query()` and `ask()`**

In `__init__.py` `query()` (line 1694), add the param after `trace_emit` (line 1711):

```python
        trace_emit: Callable[[dict], None] | None = None,
        fusion: str | None = None,
    ) -> QueryResult:
```

Add to the docstring (after the `rerank:` block, ~line 1768):

```
            fusion: per-call override of ``config.fusion``. ``"linear"``
                (default) preserves weighted-sum scoring; ``"rrf"`` fuses by
                per-leg rank (scale-free). ``None`` falls back to config.
                Applies to ``naive`` and ``hybrid`` modes only — local/global/
                naive_boost/smart/summary ignore this knob in v1.
```

Pass it through to `retrieval_query` (in the call at line 1791, after `trace_emit=trace_emit,`):

```python
                    trace_emit=trace_emit,
                    fusion=fusion,
```

In `ask()` (line 1843), add `fusion: str | None = None` after its `retrieval_strategy`/`summary_base_mode` params, and forward it to the internal `query()`/retrieval call at line 1885-1894 (`fusion=fusion`). Check `ask()`'s exact pass-through shape and mirror how it forwards `retrieval_strategy`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_rrf_fusion_it.py -v`
Expected: PASS (requires `docker compose up -d postgres`).

- [ ] **Step 5: Run the full unit + integration suite**

Run:
```bash
uv run ruff check .
uv run pytest tests/unit/ -q
uv run pytest tests/integration/ -q
```
Expected: all green (SC-009).

- [ ] **Step 6: Commit**

```bash
git add src/pg_raggraph/__init__.py tests/integration/test_rrf_fusion_it.py
git commit -m "feat: expose fusion override on public query()/ask() (issue #57)"
```

---

## Task 10: A/B benchmark (linear vs RRF) on existing MuSiQue/MHR snapshot

**Files:**
- Create: `benchmarks/rrf-ab/run_rrf_ab.py` (small runner; reuse existing loaders)
- Reference: `benchmarks/e2e/snapshot.py` (restore), `benchmarks/musique/` harness

- [ ] **Step 1: Confirm a snapshot is restorable (no re-ingest)**

Run:
```bash
ls benchmarks/e2e/snapshots/*.manifest.json
```
Check that an existing snapshot's embedder/dim/chunker/extractor match the current config (per the `reference_bench_snapshots` memory). If it matches, restore it rather than re-ingesting:

```bash
uv run python benchmarks/e2e/snapshot.py restore <snapshot-name>
```

If no matching snapshot exists, fall back to the MuSiQue harness ingest (`benchmarks/musique/ingest.py`) — but prefer the snapshot path.

- [ ] **Step 2: Write the A/B runner**

Create `benchmarks/rrf-ab/run_rrf_ab.py` that, for a fixed query set from the restored corpus, runs each query under `fusion="linear"` and `fusion="rrf"` (same `mode`, same corpus), and reports per-mode rank-overlap and a quality proxy (recall@k / MRR against gold where available, matching how `benchmarks/musique/` already computes verdicts). Reuse the existing judge seam (`reference_judge_endpoints` memory) only if an LLM judge is wanted — otherwise report retrieval-overlap deltas, which need no judge.

```python
"""A/B: linear vs RRF fusion on the restored MuSiQue/MHR snapshot (issue #57).

Reuses the existing benchmark loaders; does NOT re-ingest. Reports rank-overlap
and recall@k / MRR deltas per mode (naive, hybrid) under both fusion settings.
"""
# Implementation: load gold questions (benchmarks/musique/questions.json),
# for each q: rag.query(q, mode=m, fusion=f) for f in (linear, rrf), m in
# (naive, hybrid); collect chunk-id orderings; compute Jaccard overlap of
# top-k id sets and recall@k vs gold_doc_id; print a small table.
```

> Keep this runner small and deterministic. The acceptance bar (SC-008) is "a comparison number exists, measurement-driven" — not a specific win threshold. The brief predicts RRF wins/ties on heterogeneous corpora; record whatever it actually shows.

- [ ] **Step 3: Run the benchmark and capture the result**

Run:
```bash
uv run python benchmarks/rrf-ab/run_rrf_ab.py | tee benchmarks/rrf-ab/results-linear-vs-rrf.txt
```
Expected: a table of linear-vs-rrf deltas written to the results file.

- [ ] **Step 4: Commit**

```bash
git add benchmarks/rrf-ab/
git commit -m "bench(rrf): A/B linear vs RRF on MuSiQue/MHR snapshot (issue #57)"
```

---

## Task 11: CHANGELOG + docs + stale-comment fix + final gate

**Files:**
- Modify: `CHANGELOG.md`
- Create/Modify: `docs/cookbook/rrf-fusion.md` (short)
- Modify: `src/pg_raggraph/retrieval.py:186-188` (stale "three builders" comment)

- [ ] **Step 1: Fix the stale sync comment**

The comment at `retrieval.py:186-188` says "all three builders" but there are now more. Update it to reflect reality (it appears in `_build_naive_query`):

```python
    # PRG-1 consumer-surface columns (d.metadata/retracted/version_label/
    # effective_from/effective_to/superseded_by_id) are intentionally repeated
    # across the naive builders (single-pass/two-stage/pre_filter/vector_first)
    # and their RRF variants — keep these SELECT blocks in sync.
```

- [ ] **Step 2: Add the CHANGELOG entry**

In `CHANGELOG.md`, under a new top entry (match the existing `### Added` style):

```markdown
## Unreleased

### Added
- **Optional RRF fusion mode** (`fusion="rrf"`, issue #57) — alongside the
  default linear weighted scoring. Fuses retrieval legs by rank
  (Σ wᵢ / (rrf_k + rankᵢ)) instead of weighted sum of differently-scaled
  scores. Config knobs `fusion` + `rrf_k`; per-call override on
  `query()` / `ask()`. Applies to `naive` + `hybrid` modes. **Additive and
  default-off** — the linear path is byte-identical when `fusion="linear"`.
  A/B runner in `benchmarks/rrf-ab/`.
```

- [ ] **Step 3: Write a short cookbook note**

Create `docs/cookbook/rrf-fusion.md` explaining: what RRF is, why it's scale-free, the two knobs, the per-call override, that it covers naive+hybrid, and that it's default-off. Keep it to ~30 lines, matching the style of other `docs/cookbook/*.md`.

- [ ] **Step 4: Check the MCP-sync house rule**

RRF adds no MCP tool behavior change, so the three-file MCP sync rule should be N/A. Confirm:

```bash
uv run pytest tests/unit/test_instructions_sync.py -v
```
Expected: PASS (unchanged). If it fails, the change touched MCP-surfaced behavior unexpectedly — stop and reconcile `server_instructions.py` / `docs/user-guide.md` / `README.md` per the house rule.

- [ ] **Step 5: Final full gate (SC-009)**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/unit/ -q
uv run pytest tests/integration/ -q
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md docs/cookbook/rrf-fusion.md src/pg_raggraph/retrieval.py
git commit -m "docs(rrf): CHANGELOG + cookbook + fix stale builder-sync comment (issue #57)"
```

⛔ **Drift Check DC-FINAL:** Re-read the mission brief. For EACH SC-001…SC-010, confirm evidence exists:
- SC-001/002 → Task 1, 2, 7 tests pass.
- SC-003 → Task 3-6 shape tests + Task 9 integration.
- SC-004/005 → Task 8 `_rrf_merge` test + Task 9 evolution-on integration.
- SC-006 → every `*_linear_unchanged` test passes (no `rank()` in linear SQL).
- SC-007 → `test_rrf_merge_reorders_vs_max_score` passes.
- SC-008 → `benchmarks/rrf-ab/results-linear-vs-rrf.txt` exists with a real number.
- SC-009 → final ruff + pytest green.
- SC-010 → CHANGELOG + cookbook present.
If any SC lacks evidence, the work is not complete.

---

## Self-Review Notes

- **Spec coverage:** All 10 SCs map to tasks (see DC-FINAL). All 6 acceptance criteria from issue #57 covered: config knobs (T1), per-query override (T7/T9), RRF in naive+hybrid behind flag (T3-6, T8), linear unchanged (T3-6 guards, SC-006), unit reorder test (T8), A/B benchmark (T10), ruff+pytest (T9/T11), docs/CHANGELOG (T11).
- **Out of scope honored:** local/global standalone, naive_boost, smart, summary all keep linear (T7 scope note; T8 touches only the hybrid merge). Graph leg stays a constant. No weight/`tune_scoring_weights` changes.
- **Design decision applied:** RRF ranks base vec/bm25 legs; `evolution_score_expr` wraps the RRF expression with d.* re-joined at the outer level — the locked "rank base legs, decay outside" choice.
- **Known consideration (flagged, not silently handled):** under RRF the `mf_soft` metadata-bias term is dropped (it is a score-scale nudge with no rank meaning); the `mf_hard` WHERE exclusion is preserved. Note this in the cookbook.
- **Type/name consistency:** `_effective_fusion`, `_rrf_fused_base_expr`, `_rrf_merge`, the `*_rrf` builder names, and the `fusion`/`rrf_k` param/field names are used consistently across all tasks.
