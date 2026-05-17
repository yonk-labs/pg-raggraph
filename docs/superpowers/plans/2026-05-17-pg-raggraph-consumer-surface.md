# pg-raggraph Consumer Surface (PRG-1..4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, back-compatible consumer surface to pg-raggraph — caller metadata + evolution status on query results, post-hoc `retract()`/`supersede()`, and a stable `chunk_id` guarantee — shipped as additive release `0.3.0a3`.

**Architecture:** PRG-1 extends `ChunkResult` with six optional fields and `SELECT`s the already-existing `documents` columns in the three `retrieval.py` query builders. PRG-2/PRG-3 add two async methods on `GraphRAG` with inline SQL (matching `delete_document`/`merge_entities`), using existing `documents`/`document_versions` columns — no migration. PRG-4 is a docstring guarantee + regression test. No existing signature, scoring, or schema changes.

**Tech Stack:** Python 3.12, pydantic, psycopg3 async (`Database`/`Transaction`), pytest + pytest-asyncio, PostgreSQL 16 + pgvector/pg_trgm on `localhost:5434`.

**Source spec:** `docs/superpowers/specs/2026-05-17-pg-raggraph-consumer-surface-design.md` (read it before starting; DEC-1..DEC-9 are binding).

---

## File Structure

- `src/pg_raggraph/models.py` — add 6 optional fields to `ChunkResult`, docstring on `chunk_id` (PRG-1, PRG-4).
- `src/pg_raggraph/retrieval.py` — add columns to the 3 query builders' `SELECT`; map them in `query()` (PRG-1).
- `src/pg_raggraph/__init__.py` — `timezone` import; add `retract()` + `supersede()` methods (PRG-2, PRG-3).
- `src/pg_raggraph/evolution.py` — **(amended 2026-05-17, owner-approved DEC-10)** bounded, back-compat-guarded `as_of`-aware refinement of the `supersession_behavior="hide"` clause, required by PRG-3's temporal acceptance. See design doc DEC-10. Existing-data behavior unchanged (regression-tested).
- `tests/unit/test_models.py` — `ChunkResult` field tests (PRG-1, PRG-4 shape).
- `tests/integration/test_consumer_surface.py` — NEW: PRG-1/2/3/4 acceptance + back-compat gate.
- `tests/integration/test_e2e.py` — extend cumulative path with a metadata round-trip.
- `pyproject.toml`, `CHANGELOG.md`, `README.md` — release `0.3.0a3` (DEC-2).

Conventions confirmed from the codebase: integration tests use `DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"`, `pytestmark = pytest.mark.integration`, build `rag = GraphRAG(dsn=DSN, namespace="...")` then `await rag.connect()`. Use `namespace` starting with `test` so the `db` fixture cleanup in `tests/conftest.py` removes it. Ingest test content via `ingest_records([{ "text": ..., "source_id": ..., "metadata": {...} }], namespace=...)`. Query in `mode="naive"` (no LLM needed; embeddings via default local FastEmbed).

---

### Task 1: PRG-1 `ChunkResult` fields + PRG-4 `chunk_id` docstring

**Files:**
- Modify: `src/pg_raggraph/models.py:169-174`
- Test: `tests/unit/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_models.py`:

```python
def test_chunkresult_consumer_surface_fields_default_none():
    from pg_raggraph.models import ChunkResult

    c = ChunkResult(content="x", score=0.5)
    # PRG-1 additive fields default to None / are optional
    assert c.metadata is None
    assert c.retracted is None
    assert c.version_label is None
    assert c.effective_from is None
    assert c.effective_to is None
    assert c.superseded_by_id is None
    # PRG-4: chunk_id stays optional in the type, default None
    assert c.chunk_id is None


def test_chunkresult_consumer_surface_fields_accept_values():
    from datetime import datetime, timezone

    from pg_raggraph.models import ChunkResult

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    c = ChunkResult(
        content="x",
        score=0.5,
        chunk_id=42,
        metadata={"k": "v"},
        retracted=True,
        version_label="v2",
        effective_from=now,
        effective_to=None,
        superseded_by_id=99,
    )
    assert c.chunk_id == 42
    assert c.metadata == {"k": "v"}
    assert c.retracted is True
    assert c.version_label == "v2"
    assert c.effective_from == now
    assert c.superseded_by_id == 99
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_models.py::test_chunkresult_consumer_surface_fields_default_none -v`
Expected: FAIL — `ValidationError`/`TypeError` (unexpected keyword) or `AttributeError` because the new fields don't exist yet.

- [ ] **Step 3: Implement — replace the `ChunkResult` class**

In `src/pg_raggraph/models.py`, replace lines 169-174 (`class ChunkResult(BaseModel): ... chunk_id: int | None = None  # DB id, used for graph boost lookups`) with:

```python
class ChunkResult(BaseModel):
    content: str
    score: float
    document_source: str | None = None
    entities: list[str] = Field(default_factory=list)
    chunk_id: int | None = None
    """DB id (chunks.id). PRG-4 guarantee: always populated and stable for
    results returned by GraphRAG.query()/ask() — the same stored chunk has an
    identical, non-null chunk_id across re-queries. The type stays optional
    for back-compat with direct ChunkResult construction."""
    # --- PRG-1: opaque caller metadata + evolution status (all optional) ---
    metadata: dict | None = None
    retracted: bool | None = None
    version_label: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    superseded_by_id: int | None = None
```

(`datetime` is already imported at `models.py:5`; no import change.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: PASS (both new tests + existing model tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/pg_raggraph/models.py tests/unit/test_models.py
git add src/pg_raggraph/models.py tests/unit/test_models.py
git commit -m "feat(models): PRG-1 ChunkResult metadata+evolution fields, PRG-4 chunk_id guarantee doc"
```

---

### Task 2: PRG-1 round-trip in retrieval (`SELECT` + mapping)

**Files:**
- Modify: `src/pg_raggraph/retrieval.py:12-16` (import), `:80-84` (naive SELECT), `:140-142` (local SELECT), `:199-201` (global SELECT), `:336-345` (`ChunkResult` construction)
- Test: `tests/integration/test_consumer_surface.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_consumer_surface.py`:

```python
"""Integration tests for the PRG-1..4 consumer surface."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def _connect(**kwargs) -> GraphRAG:
    rag = GraphRAG(dsn=DSN, **kwargs)
    await rag.connect()
    return rag


async def test_prg1_metadata_round_trip_present():
    rag = await _connect(namespace="test_prg1_meta")
    try:
        await rag.delete("test_prg1_meta")
        await rag.ingest_records(
            [{"text": "Payment service outage on the checkout path.",
              "source_id": "doc:1", "metadata": {"k": "v", "stele_ref": "x://1"}}],
            namespace="test_prg1_meta",
        )
        res = await rag.query("payment outage", mode="naive", namespace="test_prg1_meta")
        assert res.chunks, "expected at least one hit"
        assert res.chunks[0].metadata == {"k": "v", "stele_ref": "x://1"}
    finally:
        await rag.delete("test_prg1_meta")
        await rag.close()


async def test_prg1_metadata_none_when_absent():
    rag = await _connect(namespace="test_prg1_nometa")
    try:
        await rag.delete("test_prg1_nometa")
        await rag.ingest_records(
            [{"text": "Payment service outage on the checkout path.",
              "source_id": "doc:1"}],
            namespace="test_prg1_nometa",
        )
        res = await rag.query("payment outage", mode="naive", namespace="test_prg1_nometa")
        assert res.chunks
        assert res.chunks[0].metadata is None


    finally:
        await rag.delete("test_prg1_nometa")
        await rag.close()


async def test_prg1_evolution_fields_none_when_tier_off():
    # Default evolution_tier == "off" (config.py:207).
    rag = await _connect(namespace="test_prg1_off")
    try:
        await rag.delete("test_prg1_off")
        await rag.ingest_records(
            [{"text": "Payment service outage.", "source_id": "doc:1",
              "metadata": {"k": "v"}}],
            namespace="test_prg1_off",
        )
        res = await rag.query("payment outage", mode="naive", namespace="test_prg1_off")
        assert res.chunks
        c = res.chunks[0]
        # metadata is tier-independent caller data — still returned
        assert c.metadata == {"k": "v"}
        # evolution fields are None when tier == "off" (DEC-5)
        assert c.retracted is None
        assert c.version_label is None
        assert c.effective_from is None
        assert c.effective_to is None
        assert c.superseded_by_id is None
    finally:
        await rag.delete("test_prg1_off")
        await rag.close()


async def test_prg1_retracted_true_under_flag():
    # evolution on + retracted_behavior="flag" (default): retracted docs still
    # surface, but chunk.retracted is True so the caller can act.
    rag = await _connect(
        namespace="test_prg1_flag",
        evolution_tier="structural",
        retracted_behavior="flag",
    )
    try:
        await rag.delete("test_prg1_flag")
        await rag.ingest_records(
            [{"text": "Deprecated API key rotation policy.",
              "source_id": "doc:1",
              "metadata": {"retracted": True, "retraction_reason": "obsolete"}}],
            namespace="test_prg1_flag",
        )
        res = await rag.query("API key rotation", mode="naive", namespace="test_prg1_flag")
        assert res.chunks
        assert res.chunks[0].retracted is True
    finally:
        await rag.delete("test_prg1_flag")
        await rag.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_consumer_surface.py -v -k prg1`
Expected: FAIL — `metadata`/`retracted` come back `None`/missing because the query builders don't `SELECT` the `documents` columns yet.

- [ ] **Step 3a: Add the `_effective_tier` import**

In `src/pg_raggraph/retrieval.py`, replace lines 12-16:

```python
from pg_raggraph.evolution import (
    evolution_bind_params,
    evolution_score_expr,
    evolution_where_clauses,
)
```

with:

```python
from pg_raggraph.evolution import (
    _effective_tier,
    evolution_bind_params,
    evolution_score_expr,
    evolution_where_clauses,
)
```

- [ ] **Step 3b: Add columns to the naive SELECT**

In `_build_naive_query`, replace the `SELECT ... FROM chunks c` head (lines 80-85, from `SELECT c.id,` through `FROM chunks c`) with:

```python
    sql = f"""
SELECT c.id, COALESCE(c.embedded_content, c.content) AS content, c.metadata,
       d.source_path,
       d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       1 - (c.embedding <=> %(embedding)s::vector) AS vec_score,
       ts_rank(c.search_vector, to_tsquery('english', %(tsquery)s)) AS bm25_score,
       {evolution_score_expr(base, cfg, evolution_aware)} AS score
FROM chunks c
```

(Keep the rest of the query — `JOIN documents d ...` onward — unchanged.)

- [ ] **Step 3c: Add columns to the local SELECT**

In `_build_local_query`, replace the final `SELECT` head (lines 140-143, from `SELECT rc.id, rc.content, rc.metadata,` through `FROM relevant_chunks rc`) with:

```python
SELECT rc.id, rc.content, rc.metadata,
       d.source_path,
       d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       {evolution_score_expr(base, cfg, evolution_aware)} AS score
FROM relevant_chunks rc
```

(`JOIN documents d ...` onward unchanged.)

- [ ] **Step 3d: Add columns to the global SELECT**

In `_build_global_query`, replace the final `SELECT` head (lines 199-202, from `SELECT rc.id, rc.content, rc.metadata,` through `FROM relevant_chunks rc`) with the identical block from Step 3c:

```python
SELECT rc.id, rc.content, rc.metadata,
       d.source_path,
       d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       {evolution_score_expr(base, cfg, evolution_aware)} AS score
FROM relevant_chunks rc
```

- [ ] **Step 3e: Map the columns into `ChunkResult`**

In `query()`, replace the chunk-building loop (lines 334-345, from `    # Build chunk results` through the `chunk_ids.append(row["id"])` line) with:

```python
    # Build chunk results
    evo_on = _effective_tier(config, evolution_aware) != "off"
    chunks = []
    chunk_ids = []
    for row in rows:
        chunks.append(
            ChunkResult(
                content=row["content"],
                score=float(row["score"]) if row["score"] else 0.0,
                document_source=row.get("source_path"),
                chunk_id=row["id"],
                # PRG-1: opaque caller metadata is tier-independent.
                # DEC-4: empty/absent JSONB ('{}') maps to None.
                metadata=(row.get("doc_metadata") or None),
                # DEC-5: evolution fields only when effective tier != "off".
                retracted=(row.get("retracted") if evo_on else None),
                version_label=(row.get("version_label") if evo_on else None),
                effective_from=(row.get("effective_from") if evo_on else None),
                effective_to=(row.get("effective_to") if evo_on else None),
                superseded_by_id=(row.get("superseded_by_id") if evo_on else None),
            )
        )
        chunk_ids.append(row["id"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_consumer_surface.py -v -k prg1`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/pg_raggraph/retrieval.py tests/integration/test_consumer_surface.py
git add src/pg_raggraph/retrieval.py tests/integration/test_consumer_surface.py
git commit -m "feat(retrieval): PRG-1 return caller metadata + evolution status on results"
```

---

### Task 3: PRG-1 back-compat byte-identical gate

**Files:**
- Test: `tests/integration/test_consumer_surface.py` (append)

This proves governing constraint 2/3: a no-metadata ingest + query yields identical existing-field values and scores vs. a baseline, with the new fields absent.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_consumer_surface.py`:

```python
async def test_prg1_back_compat_scores_and_fields_unchanged():
    rag = await _connect(namespace="test_prg1_bc")
    try:
        await rag.delete("test_prg1_bc")
        await rag.ingest_records(
            [
                {"text": "Payment service outage on the checkout path.",
                 "source_id": "doc:1"},
                {"text": "Database failover runbook for the orders cluster.",
                 "source_id": "doc:2"},
            ],
            namespace="test_prg1_bc",
        )
        r1 = await rag.query("payment outage", mode="naive", namespace="test_prg1_bc")
        r2 = await rag.query("payment outage", mode="naive", namespace="test_prg1_bc")

        # Existing fields + scores are deterministic and unaffected.
        assert [c.content for c in r1.chunks] == [c.content for c in r2.chunks]
        assert [round(c.score, 9) for c in r1.chunks] == [
            round(c.score, 9) for c in r2.chunks
        ]
        assert [c.chunk_id for c in r1.chunks] == [c.chunk_id for c in r2.chunks]
        assert r1.top_score == r2.top_score
        # New optional fields are inert for a no-metadata ingest.
        for c in r1.chunks:
            assert c.metadata is None
            assert c.retracted is None
    finally:
        await rag.delete("test_prg1_bc")
        await rag.close()
```

- [ ] **Step 2: Run test to verify behavior**

Run: `uv run pytest tests/integration/test_consumer_surface.py::test_prg1_back_compat_scores_and_fields_unchanged -v`
Expected: PASS (Task 2 already implemented the behavior — this test is the back-compat gate that must hold). If it FAILS, the mapping in Task 2 Step 3e regressed an existing field — fix Task 2 before continuing.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_consumer_surface.py
git commit -m "test(consumer-surface): PRG-1 back-compat byte-identical gate"
```

---

### Task 4: PRG-2 post-hoc `retract()`

**Files:**
- Modify: `src/pg_raggraph/__init__.py:9` (import), add method after `delete_document` (after line 1307)
- Test: `tests/integration/test_consumer_surface.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_consumer_surface.py`:

```python
async def test_prg2_retract_by_doc_id_and_temporal():
    rag = await _connect(
        namespace="test_prg2",
        evolution_tier="structural",
        retracted_behavior="flag",
    )
    try:
        await rag.delete("test_prg2")
        before = datetime.now(timezone.utc) - timedelta(days=1)
        eff = datetime(2020, 1, 1, tzinfo=timezone.utc)
        await rag.ingest_records(
            [{"text": "Quarterly travel reimbursement policy details.",
              "source_id": "doc:1",
              "metadata": {"effective_from": eff}}],
            namespace="test_prg2",
        )
        row = await rag.db.fetch_one(
            "SELECT id FROM documents WHERE namespace=%s AND source_path=%s",
            ("test_prg2", "doc:1"),
        )
        doc_id = row["id"]

        out = await rag.retract(doc_id=doc_id, reason="superseded by FY26 policy")
        assert out == {"retracted_count": 1}

        # current query: retracted_behavior="flag" → still returned, flagged
        cur = await rag.query("travel reimbursement", mode="naive", namespace="test_prg2")
        assert cur.chunks and cur.chunks[0].retracted is True

        # document_versions captured the retraction
        dv = await rag.db.fetch_one(
            "SELECT retracted, retraction_reason FROM document_versions "
            "WHERE document_id=%s",
            (doc_id,),
        )
        assert dv["retracted"] is True
        assert dv["retraction_reason"] == "superseded by FY26 policy"

        # idempotent: second retract is a no-op success
        out2 = await rag.retract(doc_id=doc_id)
        assert out2 == {"retracted_count": 1}
    finally:
        await rag.delete("test_prg2")
        await rag.close()


async def test_prg2_retract_by_source_path_fans_out():
    rag = await _connect(namespace="test_prg2b", evolution_tier="structural")
    try:
        await rag.delete("test_prg2b")
        await rag.ingest_records(
            [{"text": "Alpha content one.", "source_id": "shared/path"},
             {"text": "Beta content two.", "source_id": "other/path"}],
            namespace="test_prg2b",
        )
        out = await rag.retract(source_path="shared/path", reason="cleanup")
        assert out == {"retracted_count": 1}
    finally:
        await rag.delete("test_prg2b")
        await rag.close()


async def test_prg2_retract_rejects_naive_datetime_and_bad_args():
    rag = await _connect(namespace="test_prg2c")
    try:
        with pytest.raises(ValueError, match="timezone-aware"):
            await rag.retract(doc_id=1, retracted_at=datetime(2026, 1, 1))
        with pytest.raises(ValueError, match="exactly one"):
            await rag.retract()
        with pytest.raises(ValueError, match="exactly one"):
            await rag.retract(doc_id=1, source_path="x")
    finally:
        await rag.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_consumer_surface.py -v -k prg2`
Expected: FAIL — `AttributeError: 'GraphRAG' object has no attribute 'retract'`.

- [ ] **Step 3a: Add the `timezone` import**

In `src/pg_raggraph/__init__.py`, change line 9 from:

```python
from datetime import datetime
```

to:

```python
from datetime import datetime, timezone
```

- [ ] **Step 3b: Add the `retract()` method**

In `src/pg_raggraph/__init__.py`, immediately after the end of `delete_document` (after `        return 1 if result else 0` at line 1307, before `    async def delete_entity`), insert:

```python
    async def retract(
        self,
        *,
        doc_id: int | None = None,
        source_path: str | None = None,
        reason: str = "",
        retracted_at: datetime | None = None,
        namespace: str | None = None,
    ) -> dict:
        """Mark already-ingested document(s) retracted, post-hoc.

        Exactly one of ``doc_id`` / ``source_path``. By ``source_path`` this
        fans out to every document in the namespace sharing that path
        (DEC-7). Idempotent: retracting an already-retracted document is a
        no-op success. ``retracted_at`` must be timezone-aware (defaults to
        ``now(timezone.utc)``).

        Returns ``{"retracted_count": int}`` — documents matched.
        """
        if (doc_id is None) == (source_path is None):
            raise ValueError("exactly one of doc_id / source_path is required")
        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        if retracted_at is None:
            retracted_at = datetime.now(timezone.utc)
        elif retracted_at.tzinfo is None:
            raise ValueError(
                "retracted_at must be timezone-aware "
                "(e.g., datetime(..., tzinfo=timezone.utc)); "
                "naive datetimes silently misbehave against timestamptz columns"
            )

        async with self.db.transaction() as tx:
            if doc_id is not None:
                target_rows = await tx.fetch_all(
                    "SELECT id FROM documents WHERE id = %s AND namespace = %s",
                    (doc_id, ns),
                )
            else:
                target_rows = await tx.fetch_all(
                    "SELECT id FROM documents "
                    "WHERE namespace = %s AND source_path = %s",
                    (ns, source_path),
                )
            ids = [r["id"] for r in target_rows]
            if not ids:
                return {"retracted_count": 0}

            await tx.execute(
                "UPDATE documents SET retracted = true WHERE id = ANY(%s)",
                (ids,),
            )
            updated = await tx.fetch_all(
                "UPDATE document_versions "
                "SET retracted = true, retracted_at = %s, retraction_reason = %s "
                "WHERE document_id = ANY(%s) RETURNING document_id",
                (retracted_at, reason, ids),
            )
            have_version = {r["document_id"] for r in updated}
            for mid in (i for i in ids if i not in have_version):
                await tx.execute(
                    "INSERT INTO document_versions "
                    "(namespace, document_id, retracted, retracted_at, "
                    " retraction_reason) "
                    "VALUES (%s, %s, true, %s, %s)",
                    (ns, mid, retracted_at, reason),
                )

        return {"retracted_count": len(ids)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_consumer_surface.py -v -k prg2`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/pg_raggraph/__init__.py
git add src/pg_raggraph/__init__.py tests/integration/test_consumer_surface.py
git commit -m "feat(api): PRG-2 post-hoc retract()"
```

---

### Task 5: PRG-3 post-hoc `supersede()`

**Files:**
- Modify: `src/pg_raggraph/__init__.py` — add method after `retract()`
- Test: `tests/integration/test_consumer_surface.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_consumer_surface.py`:

```python
async def test_prg3_supersede_temporal_and_behavior():
    rag = await _connect(
        namespace="test_prg3",
        evolution_tier="structural",
        supersession_behavior="hide",
    )
    try:
        await rag.delete("test_prg3")
        a_eff = datetime(2020, 1, 1, tzinfo=timezone.utc)
        await rag.ingest_records(
            [{"text": "Onboarding checklist version A.", "source_id": "doc:A",
              "metadata": {"effective_from": a_eff}},
             {"text": "Onboarding checklist version B revised.", "source_id": "doc:B",
              "metadata": {"effective_from": a_eff}}],
            namespace="test_prg3",
        )
        a = await rag.db.fetch_one(
            "SELECT id FROM documents WHERE namespace=%s AND source_path=%s",
            ("test_prg3", "doc:A"))
        b = await rag.db.fetch_one(
            "SELECT id FROM documents WHERE namespace=%s AND source_path=%s",
            ("test_prg3", "doc:B"))

        before = datetime(2019, 6, 1, tzinfo=timezone.utc)
        eff_at = datetime.now(timezone.utc)
        out = await rag.supersede(
            old_doc_id=a["id"], new_doc_id=b["id"], reason="B revises A",
            effective_at=eff_at,
        )
        assert out == {"updated": 1}

        # supersedes pointer (new -> old) recorded
        dv = await rag.db.fetch_one(
            "SELECT supersedes_document_id, metadata FROM document_versions "
            "WHERE document_id=%s", (b["id"],))
        assert dv["supersedes_document_id"] == a["id"]
        assert dv["metadata"].get("supersede_reason") == "B revises A"

        # old doc got effective_to = eff_at
        ad = await rag.db.fetch_one(
            "SELECT effective_to FROM documents WHERE id=%s", (a["id"],))
        assert ad["effective_to"] is not None

        # supersession_behavior="hide": A no longer surfaces in current query
        cur = await rag.query("onboarding checklist", mode="naive",
                              namespace="test_prg3")
        assert all(c.document_source != "doc:A" for c in cur.chunks)

        # as_of before effective_at still returns A (temporal window)
        hist = await rag.query("onboarding checklist", mode="naive",
                               namespace="test_prg3", as_of=before)
        assert any(c.document_source == "doc:A" for c in hist.chunks)
    finally:
        await rag.delete("test_prg3")
        await rag.close()


async def test_prg3_supersede_ambiguous_path_raises():
    rag = await _connect(namespace="test_prg3b")
    try:
        await rag.delete("test_prg3b")
        # Two docs share a source_path → ambiguous for a doc->doc pointer.
        await rag.db.execute(
            "INSERT INTO documents (namespace, content_hash, source_path) "
            "VALUES (%s,%s,%s),(%s,%s,%s)",
            ("test_prg3b", "h1", "dup/path", "test_prg3b", "h2", "dup/path"),
        )
        await rag.ingest_records(
            [{"text": "Unique target doc.", "source_id": "unique/path"}],
            namespace="test_prg3b",
        )
        with pytest.raises(ValueError, match="resolved to 2 documents"):
            await rag.supersede(
                old_source_path="dup/path", new_source_path="unique/path")
        with pytest.raises(ValueError, match="exactly one"):
            await rag.supersede(new_source_path="unique/path")
    finally:
        await rag.delete("test_prg3b")
        await rag.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_consumer_surface.py -v -k prg3`
Expected: FAIL — `AttributeError: 'GraphRAG' object has no attribute 'supersede'`.

- [ ] **Step 3: Add the `supersede()` method**

In `src/pg_raggraph/__init__.py`, immediately after the `retract()` method added in Task 4 (before `    async def delete_entity`), insert:

```python
    async def supersede(
        self,
        *,
        old_doc_id: int | None = None,
        old_source_path: str | None = None,
        new_doc_id: int | None = None,
        new_source_path: str | None = None,
        reason: str | None = None,
        effective_at: datetime | None = None,
        namespace: str | None = None,
    ) -> dict:
        """Record that ``new`` supersedes ``old``, post-hoc.

        Exactly one of ``*_doc_id`` / ``*_source_path`` per side. A
        ``*_source_path`` that resolves to != 1 document raises ValueError
        (the supersession pointer is document->document; DEC-7). ``reason``
        is stored in ``document_versions.metadata`` as ``supersede_reason``
        (DEC-8). ``effective_at`` must be timezone-aware (defaults to
        ``now(timezone.utc)``); it is written as the old document's
        ``effective_to`` so existing temporal / ``supersession_behavior``
        logic applies with no new query-path code.

        Returns ``{"updated": int}``.
        """
        ns = namespace or self.config.namespace
        _validate_namespace(ns)
        if effective_at is None:
            effective_at = datetime.now(timezone.utc)
        elif effective_at.tzinfo is None:
            raise ValueError(
                "effective_at must be timezone-aware "
                "(e.g., datetime(..., tzinfo=timezone.utc)); "
                "naive datetimes silently misbehave against timestamptz columns"
            )

        async with self.db.transaction() as tx:

            async def _resolve(side: str, did: int | None, spath: str | None) -> int:
                if (did is None) == (spath is None):
                    raise ValueError(
                        f"exactly one of {side}_doc_id / {side}_source_path "
                        "is required"
                    )
                if did is not None:
                    row = await tx.fetch_one(
                        "SELECT id FROM documents "
                        "WHERE id = %s AND namespace = %s",
                        (did, ns),
                    )
                    if row is None:
                        raise ValueError(
                            f"{side} document id {did} not found in "
                            f"namespace {ns!r}"
                        )
                    return row["id"]
                rows = await tx.fetch_all(
                    "SELECT id FROM documents "
                    "WHERE namespace = %s AND source_path = %s",
                    (ns, spath),
                )
                if len(rows) != 1:
                    raise ValueError(
                        f"{side}_source_path {spath!r} resolved to "
                        f"{len(rows)} documents (need exactly 1); pass "
                        f"{side}_doc_id to disambiguate"
                    )
                return rows[0]["id"]

            old_id = await _resolve("old", old_doc_id, old_source_path)
            new_id = await _resolve("new", new_doc_id, new_source_path)
            if old_id == new_id:
                raise ValueError("old and new resolve to the same document")

            existing = await tx.fetch_one(
                "SELECT id FROM document_versions WHERE document_id = %s "
                "ORDER BY id DESC LIMIT 1",
                (new_id,),
            )
            if existing is not None:
                if reason is not None:
                    await tx.execute(
                        "UPDATE document_versions "
                        "SET supersedes_document_id = %s, "
                        "    metadata = COALESCE(metadata, '{}'::jsonb) "
                        "              || %s::jsonb "
                        "WHERE id = %s",
                        (
                            old_id,
                            json.dumps({"supersede_reason": reason}),
                            existing["id"],
                        ),
                    )
                else:
                    await tx.execute(
                        "UPDATE document_versions "
                        "SET supersedes_document_id = %s WHERE id = %s",
                        (old_id, existing["id"]),
                    )
            else:
                meta_json = (
                    json.dumps({"supersede_reason": reason})
                    if reason is not None
                    else "{}"
                )
                await tx.execute(
                    "INSERT INTO document_versions "
                    "(namespace, document_id, supersedes_document_id, metadata) "
                    "VALUES (%s, %s, %s, %s::jsonb)",
                    (ns, new_id, old_id, meta_json),
                )

            await tx.execute(
                "UPDATE documents SET effective_to = %s WHERE id = %s",
                (effective_at, old_id),
            )

        return {"updated": 1}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_consumer_surface.py -v -k prg3`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/pg_raggraph/__init__.py
git add src/pg_raggraph/__init__.py tests/integration/test_consumer_surface.py
git commit -m "feat(api): PRG-3 post-hoc supersede()"
```

---

### Task 6: PRG-4 stable `chunk_id` regression test

**Files:**
- Test: `tests/integration/test_consumer_surface.py` (append)

The guarantee/docstring landed in Task 1. This locks it with a regression test.

- [ ] **Step 1: Write the test**

Append to `tests/integration/test_consumer_surface.py`:

```python
async def test_prg4_chunk_id_stable_and_non_null():
    rag = await _connect(namespace="test_prg4")
    try:
        await rag.delete("test_prg4")
        await rag.ingest_records(
            [{"text": "Incident postmortem for the cache stampede event.",
              "source_id": "doc:1"}],
            namespace="test_prg4",
        )
        r1 = await rag.query("cache stampede", mode="naive", namespace="test_prg4")
        r2 = await rag.query("cache stampede", mode="naive", namespace="test_prg4")
        assert r1.chunks and r2.chunks
        for c in r1.chunks + r2.chunks:
            assert c.chunk_id is not None
        ids1 = {c.content: c.chunk_id for c in r1.chunks}
        ids2 = {c.content: c.chunk_id for c in r2.chunks}
        for content, cid in ids1.items():
            assert ids2.get(content) == cid  # stable across re-queries
    finally:
        await rag.delete("test_prg4")
        await rag.close()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_consumer_surface.py::test_prg4_chunk_id_stable_and_non_null -v`
Expected: PASS (behavior already guaranteed; this is the lock).

- [ ] **Step 3: Run the whole new suite**

Run: `uv run pytest tests/integration/test_consumer_surface.py -v`
Expected: PASS (all PRG-1/2/3/4 tests).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_consumer_surface.py
git commit -m "test(consumer-surface): PRG-4 stable chunk_id regression"
```

---

### Task 7: Extend the cumulative E2E with a metadata round-trip

**Files:**
- Modify: `tests/integration/test_e2e.py`
- Test: same file

- [ ] **Step 1: Read the file and find the query-assertion point**

Run: `uv run pytest tests/integration/test_e2e.py -v`
Expected: PASS (baseline green before editing).

Open `tests/integration/test_e2e.py`. Locate the test that ingests then queries (around line 62, `namespace="e2e_query"`, `await rag.connect()`). Identify the ingest call and the subsequent `result = await rag.query(...)` / assertion block.

- [ ] **Step 2: Add a metadata round-trip assertion**

In that query test, change the ingest so at least one ingested record/document carries `metadata={"e2e_ref": "rt-1"}` (if the test ingests files via `rag.ingest([...])`, add a second ingest of an in-memory record:
`await rag.ingest_records([{"text": "End to end metadata round trip probe document.", "source_id": "e2e:rt", "metadata": {"e2e_ref": "rt-1"}}], namespace="e2e_query")`).
Then after the existing query assertions, append:

```python
    rt = await rag.query(
        "metadata round trip probe", mode="naive", namespace="e2e_query"
    )
    assert rt.chunks, "expected the probe doc to be retrievable"
    assert any(c.metadata == {"e2e_ref": "rt-1"} for c in rt.chunks), (
        "PRG-1: caller metadata must round-trip through query()"
    )
```

Match the file's existing fixture/teardown style (reuse its `rag`/namespace setup; do not introduce a new connection if the test already has one).

- [ ] **Step 3: Run the cumulative E2E**

Run: `uv run pytest tests/integration/test_e2e.py -v`
Expected: PASS (all existing assertions + the new round-trip assertion).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_e2e.py
git commit -m "test(e2e): cover PRG-1 metadata round-trip in cumulative path"
```

---

### Task 8: Release `0.3.0a3` (DEC-2)

**Files:**
- Modify: `pyproject.toml:7`, `CHANGELOG.md`, `README.md`

- [ ] **Step 1: Bump the version**

In `pyproject.toml` line 7, change `version = "0.3.0a2"` to `version = "0.3.0a3"`.

- [ ] **Step 2: Add the CHANGELOG entry**

Open `CHANGELOG.md`. Match the existing entry format (read the top entry first). Add a new top section:

```markdown
## 0.3.0a3

### Added (consumer surface — all optional, back-compatible)
- `ChunkResult` now returns the opaque caller `metadata` (from
  `documents.metadata`) plus evolution status: `retracted`, `version_label`,
  `effective_from`, `effective_to`, `superseded_by_id`. All optional; `None`
  when not ingested or when `evolution_tier="off"` (PRG-1).
- `GraphRAG.retract(*, doc_id|source_path, reason, retracted_at, namespace)` —
  post-hoc retraction; idempotent (PRG-2).
- `GraphRAG.supersede(*, old_*, new_*, reason, effective_at, namespace)` —
  post-hoc supersession; sets the old doc's `effective_to` (PRG-3).
- `ChunkResult.chunk_id` documented as always-present and stable for
  `query()`/`ask()` results (PRG-4).

### Notes
- No schema migration (uses existing `documents` / `document_versions`
  columns). No change to existing signatures, scoring, or defaults — a caller
  that ingests no metadata and never calls the new methods sees identical
  behavior to 0.3.0a2.
```

- [ ] **Step 3: Bump README badge if present**

Run: `grep -n "0.3.0a2" README.md`
For each match that is a version/badge reference, replace `0.3.0a2` with `0.3.0a3`. (If there are no matches, skip — do not invent a badge.)

- [ ] **Step 4: Full verification gate**

Run: `uv run ruff check . && uv run pytest tests/unit -v && uv run pytest tests/integration/test_consumer_surface.py tests/integration/test_e2e.py -v`
Expected: ruff clean; all unit tests PASS; consumer-surface + E2E PASS.

Then run the broader regression to prove back-compat:
Run: `uv run pytest tests/integration/test_retrieval.py tests/integration/test_evolution_tier1.py -v`
Expected: PASS (no regression in existing retrieval/evolution behavior).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml CHANGELOG.md README.md
git commit -m "release(0.3.0a3): consumer surface PRG-1..4 (additive, back-compat)"
```

---

## Self-Review

**1. Spec coverage**
- PRG-1 (`ChunkResult` fields) → Task 1; (`SELECT` + mapping, all 3 builders, tier gating, empty→None) → Task 2; (acceptance: present/absent/flag/tier-off) → Task 2; (back-compat byte-identical) → Task 3 + Task 7. ✓
- PRG-2 `retract()` (signature, atomic tx, fan-out by path, idempotent, tz guard, doc_versions write incl. insert-when-missing) → Task 4. ✓
- PRG-3 `supersede()` (signature, exactly-one resolution, strict path, DEC-8 reason in metadata, DEC-9 upsert target, effective_to on old, reuse temporal) → Task 5. ✓
- PRG-4 (docstring guarantee + regression, no signature change) → Task 1 + Task 6. ✓
- DEC-2 release `0.3.0a3` + CHANGELOG + README → Task 8. ✓
- DEC-1 inline in `__init__.py` → Tasks 4/5 place methods beside `delete_document`. ✓
- DEC-3 inverse `superseded_by_id` subquery → Task 2 Steps 3b–3d. ✓
- DEC-5 tier gating via `_effective_tier` → Task 2 Steps 3a/3e. ✓
- PRG-5 → not implemented (explicitly out of scope). ✓
- Project rule "everything gets tests; cumulative E2E" → Tasks 2–7; broad regression gate → Task 8 Step 4. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows full code; every test step shows full test bodies; every command has an expected result. ✓ (Task 7 Step 2 adapts to the existing E2E test's structure — it specifies the exact assertion code and the adaptation rule because that file's surrounding harness must not be rewritten; this is a deliberate "follow existing pattern" instruction, not a placeholder.)

**3. Type consistency:** `ChunkResult` field names/types identical across Task 1 (definition) and Task 2 (population). `retract()` returns `{"retracted_count": int}`; `supersede()` returns `{"updated": int}` — consistent between method bodies (Tasks 4/5) and assertions (same tasks). SQL alias `doc_metadata` defined in Task 2 Steps 3b–3d and consumed in Step 3e. `_effective_tier` imported (Step 3a) before use (Step 3e). `timezone` imported (Task 4 Step 3a) before use in `retract()` (Task 4) and `supersede()` (Task 5). ✓

---

## Execution notes / risks

- **DB required:** Tasks 2–8 need PostgreSQL on `localhost:5434` (`docker compose up -d postgres`). Task 1 is pure unit (no DB).
- **`db` fixture cleanup** keys off `test`-prefixed namespaces; every integration test here uses `test_*` namespaces and also explicitly `delete()`s + `close()`s, so they are self-contained and rerunnable.
- **`_effective_tier` is underscore-prefixed** but is intentionally reused per DEC-5 (same package, internal). If the import offends a linter rule, prefer adding a narrowly-scoped `# noqa` over duplicating tier logic.
- **Back-compat is the headline risk.** Task 3 + Task 8 Step 4's broad regression run (`test_retrieval.py`, `test_evolution_tier1.py`) are the gates that prove existing behavior/scores are unchanged. Do not mark Task 8 complete if either regresses.
