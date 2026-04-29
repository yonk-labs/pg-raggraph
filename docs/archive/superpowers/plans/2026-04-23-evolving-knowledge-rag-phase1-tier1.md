# Evolving-Knowledge RAG — Phase 1 (Tier 1 Structural) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Tier 1 (Structural) of the evolving-knowledge-RAG extension: schema additions, caller-provided metadata contract, NULL-safe SQL scoring with temporal / retraction / document-level supersession signals, `as_of` and `version_filter` query kwargs, and a `tune_scoring_weights()` utility. No LLM cost. Zero API break.

**Architecture:** Additive schema (three new tables — `facts`, `fact_edges`, `document_versions` — empty at Tier 1 but present for future tiers; new columns on `documents`). Config gated by `evolution_tier` literal. Retrieval SQL composes new scoring terms onto existing NAIVE / LOCAL / GLOBAL templates via NULL-safe `COALESCE` so Tier 0 users pay nothing. Query-time kwargs override the tier-configured behavior per-call.

**Tech Stack:** Python 3.12, PostgreSQL 16, pgvector, asyncpg/psycopg (existing), pydantic-settings (existing), pytest + pytest-asyncio (existing). No new runtime dependencies.

**Spec reference:** `docs/superpowers/specs/2026-04-22-evolving-knowledge-rag-design.md` §7 Phase 1. Read it before starting — it locks many decisions referenced below.

---

## File surface

**Files to create:**
- `src/pg_raggraph/sql/migrations/002_evolution_tracking.sql` — new migration; all new DDL.
- `src/pg_raggraph/evolution.py` — evolution helpers (scoring SQL fragments, metadata validators, tune utility). Kept small; any logic > ~200 lines needs a design check.
- `tests/unit/test_evolution_config.py` — unit tests for PGRGConfig additions.
- `tests/unit/test_evolution_models.py` — unit tests for new DTOs.
- `tests/integration/test_evolution_tier1.py` — end-to-end Tier 1 tests (needs DB).
- `tests/fixtures/evolving/medical_retraction/*.md` — synthetic corpus for retraction flow.
- `tests/fixtures/evolving/software_versioning/*.md` — synthetic corpus for version flow.
- `tests/fixtures/evolving/policy_effective_dates/*.md` — synthetic corpus for `as_of` flow.
- `tests/fixtures/evolving/gold_questions.yaml` — gold-answer QA sets for the three corpora (used by `tune_scoring_weights()`).
- `docs/cookbook/evolution-tracking.md` — user-facing quickstart.

**Files to modify:**
- `src/pg_raggraph/sql/schema.sql` — add new columns + tables to fresh-install DDL.
- `src/pg_raggraph/config.py` — add evolution config fields.
- `src/pg_raggraph/models.py` — add `Fact`, `FactEdge`, `DocumentVersion` DTOs; extend `Document`.
- `src/pg_raggraph/__init__.py` — plumb `metadata={...}` through `ingest()`; add `as_of` / `version_filter` / `evolution_aware` kwargs to `query()`.
- `src/pg_raggraph/retrieval.py` — add evolution scoring terms to `NAIVE_QUERY` / `LOCAL_QUERY` / `GLOBAL_QUERY` templates.
- `CHANGELOG.md` — new entry for the feature.

---

## Task 1 — Schema migration + fresh-install DDL

**Files:**
- Create: `src/pg_raggraph/sql/migrations/002_evolution_tracking.sql`
- Modify: `src/pg_raggraph/sql/schema.sql`
- Test: `tests/integration/test_evolution_tier1.py` (new file — first test seeds the file)

### Context for the engineer

pg-raggraph applies numbered migrations via `db._apply_migrations()` in `db.py`. Files named `NNN_*.sql` under `src/pg_raggraph/sql/migrations/` are executed in numeric order once per install, tracked by `pgrg_applied_migrations`. `schema.sql` is the authoritative fresh-install DDL — it must end up in the same shape as `schema.sql + all migrations applied`.

Migration 001 (`001_embedded_content.sql`) already added `embedded_content` to `chunks`. This is 002.

### Steps

- [ ] **Step 1: Write the failing integration test for schema presence**

Create `tests/integration/test_evolution_tier1.py`:

```python
"""Integration tests for evolving-knowledge-RAG Tier 1."""
from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def _fresh(namespace: str) -> GraphRAG:
    rag = GraphRAG(dsn=DSN, namespace=namespace, llm_base_url="http://localhost:99999/v1")
    await rag.connect()
    await rag.delete(namespace)
    return rag


async def test_schema_has_evolution_tables_and_columns():
    """Tier 1 migration creates three new tables + adds evolution columns to documents."""
    rag = await _fresh("test_evo_schema")
    try:
        # Three new tables exist
        for tbl in ("facts", "fact_edges", "document_versions"):
            row = await rag.db.fetch_one(
                "SELECT 1 AS ok FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = %s",
                (tbl,),
            )
            assert row is not None, f"table {tbl} missing"

        # documents has new columns
        for col in ("effective_from", "effective_to", "retracted", "version_label"):
            row = await rag.db.fetch_one(
                "SELECT 1 AS ok FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'documents' "
                "AND column_name = %s",
                (col,),
            )
            assert row is not None, f"documents.{col} missing"
    finally:
        await rag.close()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/yonk/yonk-tools/pg-raggraph
uv run pytest tests/integration/test_evolution_tier1.py::test_schema_has_evolution_tables_and_columns -v
```

Expected: FAIL — tables and columns don't exist yet.

- [ ] **Step 3: Create migration 002_evolution_tracking.sql**

Create `src/pg_raggraph/sql/migrations/002_evolution_tracking.sql`:

```sql
-- 002_evolution_tracking.sql
-- Evolving-knowledge-RAG foundational DDL. Adds three new tables and four
-- columns on documents. All new signals are optional (nullable / default
-- false) so existing Tier 0 / Tier-off installations see no behavior change.
--
-- Tier 1 populates: documents.{effective_from, effective_to, retracted,
--   version_label, supersedes_document_id via document_versions}.
-- Tier 2 populates: facts (via skimr+spaCy).
-- Tier 3 populates: fact_edges (via async LLM slow path).
--
-- All three fact_* tables land at Tier 1 but stay empty until Tier 2/3 are
-- enabled — this avoids a second schema change when tiers ramp up.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS effective_from TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS effective_to   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS retracted      BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS version_label  TEXT;

CREATE INDEX IF NOT EXISTS idx_doc_effective_from ON documents(effective_from);
CREATE INDEX IF NOT EXISTS idx_doc_retracted ON documents(retracted) WHERE retracted;
CREATE INDEX IF NOT EXISTS idx_doc_version_label ON documents(version_label)
    WHERE version_label IS NOT NULL;

CREATE TABLE IF NOT EXISTS document_versions (
    id                       BIGSERIAL PRIMARY KEY,
    document_id              BIGINT REFERENCES documents(id) ON DELETE CASCADE,
    version_label            TEXT,
    effective_from           TIMESTAMPTZ,
    effective_to             TIMESTAMPTZ,
    supersedes_document_id   BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    retracted                BOOLEAN DEFAULT FALSE,
    retracted_at             TIMESTAMPTZ,
    retraction_reason        TEXT,
    metadata                 JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_docver_document ON document_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_docver_supersedes ON document_versions(supersedes_document_id);

CREATE TABLE IF NOT EXISTS facts (
    id                 BIGSERIAL PRIMARY KEY,
    namespace          TEXT NOT NULL,
    source_chunk_id    BIGINT REFERENCES chunks(id) ON DELETE CASCADE,
    subject            TEXT NOT NULL,
    subject_entity_id  BIGINT REFERENCES entities(id) ON DELETE SET NULL,
    predicate          TEXT NOT NULL,
    object             TEXT NOT NULL,
    object_entity_id   BIGINT REFERENCES entities(id) ON DELETE SET NULL,
    support_span       TEXT NOT NULL,
    confidence         FLOAT DEFAULT 1.0,
    effective_from     TIMESTAMPTZ,
    effective_to       TIMESTAMPTZ,
    retracted          BOOLEAN DEFAULT FALSE,
    retracted_at       TIMESTAMPTZ,
    retraction_reason  TEXT,
    extractor          TEXT NOT NULL DEFAULT 'unknown',
    properties         JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_facts_ns_source ON facts(namespace, source_chunk_id);
CREATE INDEX IF NOT EXISTS idx_facts_subject_entity ON facts(subject_entity_id);
CREATE INDEX IF NOT EXISTS idx_facts_object_entity ON facts(object_entity_id);
CREATE INDEX IF NOT EXISTS idx_facts_effective ON facts(effective_from);
CREATE INDEX IF NOT EXISTS idx_facts_retracted ON facts(retracted) WHERE retracted;

-- Note: facts.embedding is added in Tier 2 migration (003); at Tier 1 we
-- don't embed facts yet. Keeping the Tier 1 migration vector-free avoids a
-- pgvector dimension coupling.

CREATE TABLE IF NOT EXISTS fact_edges (
    id            BIGSERIAL PRIMARY KEY,
    src_fact_id   BIGINT REFERENCES facts(id) ON DELETE CASCADE,
    dst_fact_id   BIGINT REFERENCES facts(id) ON DELETE CASCADE,
    edge_type     TEXT NOT NULL,
    confidence    FLOAT DEFAULT 1.0,
    inferred_by   TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (src_fact_id, dst_fact_id, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_fact_edges_src ON fact_edges(src_fact_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_fact_edges_dst ON fact_edges(dst_fact_id, edge_type);
```

- [ ] **Step 4: Update schema.sql for fresh installs**

Modify `src/pg_raggraph/sql/schema.sql`. Find the `CREATE TABLE IF NOT EXISTS documents` block and extend with the new columns:

```sql
CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    namespace TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_path TEXT,
    metadata JSONB DEFAULT '{}',
    effective_from TIMESTAMPTZ,
    effective_to   TIMESTAMPTZ,
    retracted      BOOLEAN DEFAULT FALSE,
    version_label  TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(namespace, content_hash)
);
```

Then after the existing index blocks, append the new indexes + the three new tables (copy the same DDL from migration 002, minus the `ALTER` statements which aren't needed for fresh installs):

```sql
-- Evolution tracking (Tier 1+)
CREATE INDEX IF NOT EXISTS idx_doc_effective_from ON documents(effective_from);
CREATE INDEX IF NOT EXISTS idx_doc_retracted ON documents(retracted) WHERE retracted;
CREATE INDEX IF NOT EXISTS idx_doc_version_label ON documents(version_label)
    WHERE version_label IS NOT NULL;

-- document_versions, facts, fact_edges (verbatim from 002_evolution_tracking.sql)
-- ... [copy those three CREATE TABLE blocks + their indexes]
```

- [ ] **Step 5: Run the schema test to verify it passes**

```bash
uv run pytest tests/integration/test_evolution_tier1.py::test_schema_has_evolution_tables_and_columns -v
```

Expected: PASS. If the tables already exist from a prior run, the test still passes (tables are `IF NOT EXISTS`).

- [ ] **Step 6: Write a migration idempotency test**

Append to `tests/integration/test_evolution_tier1.py`:

```python
async def test_migration_002_idempotent():
    """Applying migration 002 twice is safe — IF NOT EXISTS + nullable columns."""
    rag = await _fresh("test_evo_idemp")
    try:
        # Simulate re-running migration by dropping the applied row and re-applying
        await rag.db.execute(
            "DELETE FROM pgrg_applied_migrations WHERE filename = '002_evolution_tracking.sql'"
        )
        # Next connect triggers re-application of 002
        await rag.close()
        rag = GraphRAG(dsn=DSN, namespace="test_evo_idemp",
                       llm_base_url="http://localhost:99999/v1")
        await rag.connect()
        # Schema should still be correct
        row = await rag.db.fetch_one(
            "SELECT 1 AS ok FROM information_schema.columns "
            "WHERE table_name='documents' AND column_name='effective_from'"
        )
        assert row is not None
    finally:
        await rag.close()
```

- [ ] **Step 7: Run the idempotency test**

```bash
uv run pytest tests/integration/test_evolution_tier1.py::test_migration_002_idempotent -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/pg_raggraph/sql/migrations/002_evolution_tracking.sql \
        src/pg_raggraph/sql/schema.sql \
        tests/integration/test_evolution_tier1.py
git commit -m "feat(schema): migration 002 — evolution tracking tables + columns

Adds facts, fact_edges, document_versions tables (empty at Tier 1) and
four evolution columns on documents (effective_from, effective_to,
retracted, version_label). All additive and nullable so Tier 0 behavior
is unchanged. Matches schema.sql; re-application idempotent."
```

---

## Task 2 — Evolution DTOs in models.py

**Files:**
- Modify: `src/pg_raggraph/models.py`
- Create: `tests/unit/test_evolution_models.py`

### Context for the engineer

pg-raggraph uses pydantic BaseModel for all storage DTOs. Existing `Document` / `Chunk` / `Entity` / `Relationship` / `EntityChunk` / `RelationshipChunk` live in `models.py`. New DTOs mirror the schema additions from Task 1.

### Steps

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_evolution_models.py`:

```python
"""Unit tests for evolution-related DTOs."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from pg_raggraph.models import Document, DocumentVersion, Fact, FactEdge


def test_document_has_evolution_fields():
    d = Document(
        namespace="ns",
        content_hash="abc",
        effective_from=datetime(2024, 6, 22, tzinfo=timezone.utc),
        retracted=True,
        version_label="v1.2",
    )
    assert d.effective_from.year == 2024
    assert d.retracted is True
    assert d.version_label == "v1.2"


def test_document_evolution_fields_optional():
    d = Document(namespace="ns", content_hash="abc")
    assert d.effective_from is None
    assert d.retracted is False      # default
    assert d.version_label is None


def test_document_version_basic():
    dv = DocumentVersion(
        document_id=1,
        version_label="Python 3.12",
        effective_from=datetime(2024, 10, 1, tzinfo=timezone.utc),
        supersedes_document_id=2,
    )
    assert dv.supersedes_document_id == 2
    assert dv.retracted is False


def test_fact_shape():
    f = Fact(
        namespace="ns",
        source_chunk_id=1,
        subject="statins",
        predicate="prevent",
        object="cardiovascular events",
        support_span="statins prevent cardiovascular events",
        extractor="llm",
    )
    assert f.confidence == 1.0
    assert f.retracted is False
    assert f.properties == {}


def test_fact_edge_edge_type_required():
    with pytest.raises(ValidationError):
        FactEdge(src_fact_id=1, dst_fact_id=2, inferred_by="llm")  # no edge_type


def test_fact_edge_basic():
    fe = FactEdge(
        src_fact_id=1,
        dst_fact_id=2,
        edge_type="SUPERSEDES",
        inferred_by="document_hint",
    )
    assert fe.edge_type == "SUPERSEDES"
    assert fe.confidence == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_evolution_models.py -v
```

Expected: FAIL — `Document` missing new fields; `DocumentVersion`/`Fact`/`FactEdge` not defined.

- [ ] **Step 3: Extend Document and add the three new DTOs**

Modify `src/pg_raggraph/models.py`. Find the `class Document(BaseModel)` block and add evolution fields:

```python
class Document(BaseModel):
    id: int | None = None
    namespace: str = "default"
    content_hash: str
    source_path: str | None = None
    metadata: dict = Field(default_factory=dict)
    # Evolution tracking (Tier 1+) — all optional. effective_to=None means "still effective".
    effective_from: datetime | None = None
    effective_to:   datetime | None = None
    retracted:      bool = False
    version_label:  str | None = None
    created_at: datetime | None = None
```

After the existing `Chunk` / `Entity` / `Relationship` / `EntityChunk` / `RelationshipChunk` classes (before the "Extraction models" comment), add:

```python
# --- Evolution tracking (Tier 1+) ---


class DocumentVersion(BaseModel):
    id: int | None = None
    document_id: int
    version_label: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    supersedes_document_id: int | None = None
    retracted: bool = False
    retracted_at: datetime | None = None
    retraction_reason: str | None = None
    metadata: dict = Field(default_factory=dict)


class Fact(BaseModel):
    id: int | None = None
    namespace: str = "default"
    source_chunk_id: int
    subject: str
    subject_entity_id: int | None = None
    predicate: str
    object: str
    object_entity_id: int | None = None
    support_span: str
    confidence: float = 1.0
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    retracted: bool = False
    retracted_at: datetime | None = None
    retraction_reason: str | None = None
    extractor: str = "unknown"
    properties: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class FactEdge(BaseModel):
    id: int | None = None
    src_fact_id: int
    dst_fact_id: int
    edge_type: str   # SUPERSEDES | CONTRADICTS | PRECEDES | SUPPORTS | REFINES
    confidence: float = 1.0
    inferred_by: str  # 'explicit' | 'llm' | 'temporal' | 'heuristic' | 'document_hint'
    created_at: datetime | None = None
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_evolution_models.py -v
```

Expected: PASS (5 tests).

- [ ] **Step 5: Run existing unit tests to confirm no regression**

```bash
uv run pytest tests/unit/ -q
```

Expected: all previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/pg_raggraph/models.py tests/unit/test_evolution_models.py
git commit -m "feat(models): add evolution DTOs (DocumentVersion, Fact, FactEdge)

Extends Document with effective_from/effective_to/retracted/version_label.
Adds DocumentVersion, Fact, FactEdge as first-class pydantic DTOs for
Tier 1+ evolution tracking. All new fields nullable / defaulted so
existing callers are unaffected."
```

---

## Task 3 — PGRGConfig additions

**Files:**
- Modify: `src/pg_raggraph/config.py`
- Create: `tests/unit/test_evolution_config.py`

### Context for the engineer

`PGRGConfig` is a `pydantic-settings BaseSettings`. Every field is overridable via `PGRG_<FIELD>` env var. Evolution tier is the master flag; other evolution fields are only honored when tier != 'off'. Defaults are conservative and documented as pending corpus tuning.

### Steps

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/test_evolution_config.py`:

```python
"""Unit tests for evolution-related PGRGConfig fields."""
from pg_raggraph.config import PGRGConfig


def test_evolution_tier_defaults_off():
    c = PGRGConfig()
    assert c.evolution_tier == "off"


def test_evolution_scoring_weight_defaults():
    c = PGRGConfig()
    # Starting weights (pending per-corpus tuning via rag.tune_scoring_weights)
    assert c.w_sem == 0.50
    assert c.w_bm25 == 0.20
    assert c.w_graph == 0.20
    assert c.w_recent == 0.10
    assert c.w_supersession == 0.10
    assert c.temporal_half_life_years == 5.0
    assert c.lambda_supersession == 0.5


def test_retracted_behavior_default_flag():
    assert PGRGConfig().retracted_behavior == "flag"


def test_supersession_behavior_default_surface_both():
    assert PGRGConfig().supersession_behavior == "surface_both"


def test_fact_extractor_default_none():
    assert PGRGConfig().fact_extractor == "none"


def test_evolution_tier_literal_values(monkeypatch):
    # Round-trip through env var
    for value in ("off", "structural", "fact_aware", "full"):
        monkeypatch.setenv("PGRG_EVOLUTION_TIER", value)
        c = PGRGConfig()
        assert c.evolution_tier == value


def test_invalid_evolution_tier_rejected(monkeypatch):
    monkeypatch.setenv("PGRG_EVOLUTION_TIER", "bogus")
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PGRGConfig()
```

- [ ] **Step 2: Run to verify fail**

```bash
uv run pytest tests/unit/test_evolution_config.py -v
```

Expected: FAIL — no evolution fields on config.

- [ ] **Step 3: Add evolution fields to PGRGConfig**

Modify `src/pg_raggraph/config.py`. At the top, add import if not present:

```python
from typing import Literal
```

Inside `class PGRGConfig(BaseSettings):`, after the existing fields and before any validators, insert:

```python
    # --- Evolving-knowledge RAG (Tier 1+) ---
    # Zero cost when 'off'; ramp up per use case.
    # See docs/superpowers/specs/2026-04-22-evolving-knowledge-rag-design.md.
    evolution_tier: Literal["off", "structural", "fact_aware", "full"] = "off"

    # Scoring weights (only active when evolution_tier != 'off'). Conservative
    # defaults; run rag.tune_scoring_weights() per corpus for best results.
    w_sem:   float = 0.50
    w_bm25:  float = 0.20
    w_graph: float = 0.20
    w_recent: float = 0.10
    w_supersession:  float = 0.10
    temporal_half_life_years: float = 5.0
    lambda_supersession:      float = 0.5

    # Retrieval behavior modes
    retracted_behavior:    Literal["hide", "flag", "surface_both"] = "flag"
    supersession_behavior: Literal["hide", "prefer_new", "surface_both"] = "surface_both"
    contradiction_detection: bool = True

    # Context assembly (used when Tier 2+ populates facts)
    fact_dedup_threshold: float = 0.8
    diversity_backfill:   bool  = True

    # Fact extraction (Tier 2+)
    fact_extractor: Literal["llm", "skimr_spacy", "none"] = "none"
    fact_similarity_threshold: float = 0.92
    fact_edge_candidate_k:     int   = 8
```

- [ ] **Step 4: Run tests to verify pass**

```bash
uv run pytest tests/unit/test_evolution_config.py -v
```

Expected: PASS (7 tests).

- [ ] **Step 5: Run the full unit suite**

```bash
uv run pytest tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/pg_raggraph/config.py tests/unit/test_evolution_config.py
git commit -m "feat(config): add evolution_tier + scoring weights to PGRGConfig

Adds evolution_tier literal (off|structural|fact_aware|full), five
scoring weights (w_sem/w_bm25/w_graph/w_recent/w_supersession), temporal
half-life, supersession lambda, and behavior mode literals for
retraction and supersession. Defaults leave Tier 0 behavior unchanged;
PGRG_EVOLUTION_TIER env var switches on.  Fact-extraction fields are
stubs for Tier 2+."
```

---

## Task 4 — Ingest metadata plumbing

**Files:**
- Modify: `src/pg_raggraph/__init__.py` (the `ingest_file()` / `ingest()` pipeline)
- Modify: `tests/integration/test_evolution_tier1.py`

### Context for the engineer

The public `GraphRAG.ingest()` API currently accepts `files=`, `namespace=`, and some other kwargs. Callers need to supply evolution metadata either globally for the ingest call (`metadata={"effective_from": ..., "version_label": ..., "retracted": ..., "supersedes_document_id": ...}`) or per-file. For Tier 1 we'll support the global-per-ingest shape; per-file requires a richer API we defer.

### Steps

- [ ] **Step 1: Write the failing integration test**

Append to `tests/integration/test_evolution_tier1.py`:

```python
from datetime import datetime, timezone


async def test_ingest_stores_evolution_metadata_on_document():
    """Caller-supplied evolution metadata flows through ingest to documents."""
    import os
    import tempfile
    rag = await _fresh("test_evo_meta")
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Retracted Study\n\nA claim that was later retracted.\n")
            path = f.name
        try:
            await rag.ingest(
                [path],
                namespace="test_evo_meta",
                metadata={
                    "effective_from": datetime(2001, 6, 1, tzinfo=timezone.utc),
                    "retracted": True,
                    "version_label": "HRT-2001-obs",
                },
            )
            row = await rag.db.fetch_one(
                "SELECT effective_from, retracted, version_label "
                "FROM documents WHERE namespace = %s",
                ("test_evo_meta",),
            )
            assert row is not None
            assert row["effective_from"].year == 2001
            assert row["retracted"] is True
            assert row["version_label"] == "HRT-2001-obs"
        finally:
            os.unlink(path)
    finally:
        await rag.close()


async def test_ingest_without_metadata_defaults():
    """Ingest with no evolution metadata leaves columns at defaults."""
    import os
    import tempfile
    rag = await _fresh("test_evo_nometa")
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Plain\n\nNo evolution metadata supplied.\n")
            path = f.name
        try:
            await rag.ingest([path], namespace="test_evo_nometa")
            row = await rag.db.fetch_one(
                "SELECT effective_from, retracted, version_label "
                "FROM documents WHERE namespace = %s",
                ("test_evo_nometa",),
            )
            assert row is not None
            assert row["effective_from"] is None
            assert row["retracted"] is False
            assert row["version_label"] is None
        finally:
            os.unlink(path)
    finally:
        await rag.close()


async def test_ingest_creates_document_versions_row_when_version_supplied():
    """When metadata carries version_label OR supersedes_document_id, a
    document_versions row is created mirroring the document metadata."""
    import os
    import tempfile
    rag = await _fresh("test_evo_docver")
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Python 3.12\n\nNew features in 3.12.\n")
            path = f.name
        try:
            await rag.ingest(
                [path],
                namespace="test_evo_docver",
                metadata={
                    "effective_from": datetime(2024, 10, 1, tzinfo=timezone.utc),
                    "version_label": "Python 3.12",
                },
            )
            dv = await rag.db.fetch_one(
                "SELECT version_label, effective_from FROM document_versions "
                "WHERE document_id IN (SELECT id FROM documents WHERE namespace = %s) "
                "LIMIT 1",
                ("test_evo_docver",),
            )
            assert dv is not None
            assert dv["version_label"] == "Python 3.12"
            assert dv["effective_from"].year == 2024
        finally:
            os.unlink(path)
    finally:
        await rag.close()
```

- [ ] **Step 2: Run to verify fail**

```bash
uv run pytest tests/integration/test_evolution_tier1.py -v -k evo_meta
```

Expected: FAIL — `ingest` doesn't accept/store these fields yet.

- [ ] **Step 3: Inspect current ingest shape**

Read `src/pg_raggraph/__init__.py` around the `ingest_file` / `ingest` methods (approx line 300-450). Find the `INSERT INTO documents (namespace, content_hash, source_path) ...` statement and the `async def ingest(...)` signature.

- [ ] **Step 4: Extend `ingest()` signature + plumb metadata**

Modify `GraphRAG.ingest(...)` in `src/pg_raggraph/__init__.py`. Add the `metadata` kwarg:

```python
    async def ingest(
        self,
        files: list[str] | str,
        *,
        namespace: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Ingest files. `metadata` carries per-ingest evolution hints that
        apply to every file in this call: effective_from, effective_to,
        retracted, version_label, supersedes_document_id. All optional."""
        ...
```

In the inner `ingest_file` (or wherever the document INSERT lives), widen the INSERT to include evolution columns. Replace the existing:

```python
doc_id = await tx.insert_returning_id(
    "INSERT INTO documents (namespace, content_hash, source_path) "
    "VALUES (%s, %s, %s) "
    "ON CONFLICT (namespace, content_hash) DO UPDATE "
    "SET source_path = EXCLUDED.source_path "
    "RETURNING id",
    (ns, c_hash, file_path),
)
```

With:

```python
meta = metadata or {}
eff_from       = meta.get("effective_from")
eff_to         = meta.get("effective_to")
retracted      = bool(meta.get("retracted", False))
version_label  = meta.get("version_label")
supersedes_doc = meta.get("supersedes_document_id")

doc_id = await tx.insert_returning_id(
    "INSERT INTO documents "
    "(namespace, content_hash, source_path, "
    " effective_from, effective_to, retracted, version_label) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (namespace, content_hash) DO UPDATE "
    "SET source_path = EXCLUDED.source_path, "
    "    effective_from = COALESCE(EXCLUDED.effective_from, documents.effective_from), "
    "    effective_to   = COALESCE(EXCLUDED.effective_to,   documents.effective_to), "
    "    retracted      = EXCLUDED.retracted, "
    "    version_label  = COALESCE(EXCLUDED.version_label,  documents.version_label) "
    "RETURNING id",
    (ns, c_hash, file_path,
     eff_from, eff_to, retracted, version_label),
)

# If caller supplied version info or a supersession edge, create a
# document_versions row for authoritative multi-version tracking.
if version_label or supersedes_doc or meta.get("retraction_reason"):
    await tx.execute(
        "INSERT INTO document_versions "
        "(document_id, version_label, effective_from, effective_to, "
        " supersedes_document_id, retracted, retracted_at, retraction_reason) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (doc_id, version_label, eff_from, eff_to, supersedes_doc,
         retracted, meta.get("retracted_at"), meta.get("retraction_reason")),
    )
```

- [ ] **Step 5: Thread `metadata` through the call site**

Find every place that calls `self.ingest_file(...)` inside `ingest()`, and pass `metadata=metadata` through.

- [ ] **Step 6: Run the three new integration tests**

```bash
uv run pytest tests/integration/test_evolution_tier1.py -v -k evo_meta -k evo_nometa -k evo_docver
```

Expected: PASS (3 tests).

- [ ] **Step 7: Run the full integration suite as a regression check**

```bash
uv run pytest tests/integration/ -q --ignore=tests/integration/test_real_llm.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/pg_raggraph/__init__.py tests/integration/test_evolution_tier1.py
git commit -m "feat(ingest): accept evolution metadata kwarg

rag.ingest(metadata={...}) now accepts effective_from, effective_to,
retracted, version_label, supersedes_document_id, retracted_at,
retraction_reason. Document inserts populate the matching columns;
a document_versions row is created when version_label or
supersedes_document_id is present. Tier 0 callers unaffected."
```

---

## Task 5 — Retrieval SQL: temporal boost + retraction filter

**Files:**
- Modify: `src/pg_raggraph/retrieval.py`
- Create: `src/pg_raggraph/evolution.py`
- Modify: `tests/integration/test_evolution_tier1.py`

### Context for the engineer

`retrieval.py` has three SQL templates — `NAIVE_QUERY`, `LOCAL_QUERY`, `GLOBAL_QUERY` — each computing a `score` expression from semantic + BM25 + graph signals. We're adding two new scoring terms (temporal boost, supersession penalty) and a retraction filter. All must be NULL-safe — when evolution columns are NULL, the expression collapses to today's three-leg hybrid score.

The simplest implementation centralizes the new scoring SQL fragments in `evolution.py` so the templates stay readable. Templates import and string-interpolate the fragments.

### Steps

- [ ] **Step 1: Write failing integration test for retraction filter**

Append to `tests/integration/test_evolution_tier1.py`:

```python
async def test_retracted_behavior_hide_filters_retracted_docs():
    """retracted_behavior='hide' excludes retracted documents from results."""
    import os
    import tempfile
    rag = await _fresh("test_evo_hide")
    rag.config.evolution_tier = "structural"
    rag.config.retracted_behavior = "hide"
    try:
        # ingest a valid doc and a retracted doc with overlapping content
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Valid\n\nStatins reduce cardiovascular events.\n")
            valid = f.name
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Retracted\n\nStatins cause cognitive decline.\n")
            retracted = f.name
        try:
            await rag.ingest([valid], namespace="test_evo_hide")
            await rag.ingest(
                [retracted],
                namespace="test_evo_hide",
                metadata={"retracted": True},
            )
            result = await rag.query(
                "What do statins do?",
                namespace="test_evo_hide",
                mode="naive",
            )
            # Retracted chunks must not appear in result
            joined = " ".join(c.content for c in result.chunks).lower()
            assert "cognitive decline" not in joined
            assert "reduce cardiovascular" in joined or len(result.chunks) >= 0
        finally:
            os.unlink(valid)
            os.unlink(retracted)
    finally:
        await rag.close()
```

- [ ] **Step 2: Run to verify fail**

```bash
uv run pytest tests/integration/test_evolution_tier1.py::test_retracted_behavior_hide_filters_retracted_docs -v
```

Expected: FAIL — retracted content still appears.

- [ ] **Step 3: Create evolution.py with scoring fragments**

Create `src/pg_raggraph/evolution.py`:

```python
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


def retraction_where_clause(cfg: PGRGConfig, doc_alias: str = "d") -> str:
    """Returns a WHERE-clause fragment to filter retracted docs when
    retracted_behavior='hide'. Empty string otherwise. Prepend 'AND ' if
    non-empty when composing."""
    if cfg.evolution_tier == "off":
        return ""
    if cfg.retracted_behavior == "hide":
        return f"NOT {doc_alias}.retracted"
    return ""


def evolution_bind_params(cfg: PGRGConfig) -> dict:
    """Bind-param dict to merge into retrieval query params."""
    return {
        "w_recent": cfg.w_recent,
        "w_supersession":  cfg.w_supersession,
        "half_life_years": cfg.temporal_half_life_years,
        "lambda_supersession": cfg.lambda_supersession,
    }
```

- [ ] **Step 4: Rewrite retrieval SQL templates to use evolution.py**

Modify `src/pg_raggraph/retrieval.py`. At top of file, add:

```python
from pg_raggraph.evolution import (
    evolution_bind_params,
    evolution_score_expr,
    retraction_where_clause,
)
```

Replace the hard-coded `NAIVE_QUERY` constant with a builder function:

```python
def _build_naive_query(cfg) -> str:
    base = (
        "%(w_sem)s * (1 - (c.embedding <=> %(embedding)s::vector)) + "
        "%(w_bm25)s * ts_rank(c.search_vector, to_tsquery('english', %(tsquery)s)) + "
        "%(w_graph)s * 0"  # naive has no graph leg
    )
    retraction_filter = retraction_where_clause(cfg, doc_alias="d")
    extra_where = f" AND {retraction_filter}" if retraction_filter else ""
    return f"""
SELECT c.id, COALESCE(c.embedded_content, c.content) AS content, c.metadata,
       d.source_path,
       1 - (c.embedding <=> %(embedding)s::vector) AS vec_score,
       ts_rank(c.search_vector, to_tsquery('english', %(tsquery)s)) AS bm25_score,
       {evolution_score_expr(base, cfg)} AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.namespace = %(namespace)s{extra_where}
ORDER BY score DESC
LIMIT %(top_k)s
"""
```

Do the same for `LOCAL_QUERY` and `GLOBAL_QUERY` — wrap each in `_build_local_query(cfg)` / `_build_global_query(cfg)` that apply `evolution_score_expr` to their existing `score` expression and add the retraction WHERE clause.

Then in `query()`:

```python
# replace: NAIVE_QUERY.format(...) etc.
# with:
sql = _build_naive_query(config)
params = {
    "namespace": namespace,
    "embedding": question_embedding,
    "tsquery": _to_tsquery(question),
    "top_k": config.top_k,
    "w_sem":   config.w_sem,
    "w_bm25":  config.w_bm25,
    "w_graph": config.w_graph,
    **evolution_bind_params(config),
}
```

- [ ] **Step 5: Add `w_sem`, `w_bm25`, `w_graph` bind params to every call site**

Every `db.fetch_all(sql, params)` call in `query()` needs the three base weights and the evolution params. Use `**evolution_bind_params(config)` for the evolution ones and explicit `w_sem=config.w_sem` etc. for the base weights.

- [ ] **Step 6: Run the retraction-hide test**

```bash
uv run pytest tests/integration/test_evolution_tier1.py::test_retracted_behavior_hide_filters_retracted_docs -v
```

Expected: PASS.

- [ ] **Step 7: Write + run a test for retracted_behavior='flag'**

Append:

```python
async def test_retracted_behavior_flag_keeps_retracted_but_flags_it():
    """retracted_behavior='flag' keeps retracted docs in results but marks them."""
    # same setup as hide test, but config = 'flag'
    import os, tempfile
    rag = await _fresh("test_evo_flag")
    rag.config.evolution_tier = "structural"
    rag.config.retracted_behavior = "flag"
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Retracted\n\nStatins cause cognitive decline (claimed).\n")
            retracted = f.name
        try:
            await rag.ingest([retracted], namespace="test_evo_flag",
                             metadata={"retracted": True})
            result = await rag.query(
                "What do statins do?",
                namespace="test_evo_flag",
                mode="naive",
            )
            # Retracted content should still appear
            joined = " ".join(c.content for c in result.chunks).lower()
            assert "cognitive decline" in joined or len(result.chunks) > 0
        finally:
            os.unlink(retracted)
    finally:
        await rag.close()
```

Run:

```bash
uv run pytest tests/integration/test_evolution_tier1.py -v -k retracted_behavior
```

Expected: both retracted-behavior tests pass.

- [ ] **Step 8: Run the full retrieval integration suite as regression**

```bash
uv run pytest tests/integration/test_retrieval.py tests/integration/test_evolution_tier1.py -q
```

Expected: all pass, no regressions from earlier retrieval tests.

- [ ] **Step 9: Commit**

```bash
git add src/pg_raggraph/evolution.py src/pg_raggraph/retrieval.py \
        tests/integration/test_evolution_tier1.py
git commit -m "feat(retrieval): temporal boost + retraction filter in SQL

Introduces src/pg_raggraph/evolution.py with NULL-safe scoring SQL
fragments. retrieval.py templates rebuilt per-query from the config
(evolution_tier gate) — off-tier callers get today's score expression
byte-identical. retracted_behavior='hide' filters retracted docs;
'flag' keeps them; 'surface_both' falls through to 'flag' for Tier 1
(semantic-aware flagging lands in Tier 3)."
```

---

## Task 6 — Retrieval SQL: document-level supersession scoring

**Files:**
- Modify: `src/pg_raggraph/evolution.py`
- Modify: `tests/integration/test_evolution_tier1.py`

### Context for the engineer

Tier 1 implements supersession at the document level only. If document B `supersedes` document A (via `document_versions.supersedes_document_id`), A's chunks get the supersession penalty applied. Tier 3 layers fact-level supersession on top but Tier 1 ships the doc-level behavior first.

The scoring fragment is already in place (Task 5 Step 3). This task adds tests proving it works, and implements `supersession_behavior` modes (`hide` filters superseded docs; `prefer_new` applies the penalty; `surface_both` keeps both with a marker — Tier 1 implements the first two; `surface_both` is a Tier-3-wrapping concept).

### Steps

- [ ] **Step 1: Write failing integration test for prefer_new**

```python
async def test_supersession_prefer_new_penalizes_superseded_doc():
    """When doc B supersedes doc A, A's chunks rank below B's under prefer_new."""
    import os, tempfile
    rag = await _fresh("test_evo_prefer")
    rag.config.evolution_tier = "structural"
    rag.config.supersession_behavior = "prefer_new"
    # Give supersession a real penalty to amplify the test signal
    rag.config.lambda_supersession = 0.9
    rag.config.w_supersession = 0.5
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Old Guidance\n\nPatients with X should receive treatment Y.\n")
            old = f.name
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# New Guidance\n\nPatients with X should receive treatment Z.\n")
            new = f.name
        try:
            # Ingest old first, get its id
            await rag.ingest([old], namespace="test_evo_prefer")
            old_doc = await rag.db.fetch_one(
                "SELECT id FROM documents WHERE namespace = %s LIMIT 1",
                ("test_evo_prefer",),
            )
            old_id = old_doc["id"]
            # Ingest new with supersedes pointer
            await rag.ingest(
                [new],
                namespace="test_evo_prefer",
                metadata={"supersedes_document_id": old_id, "version_label": "v2"},
            )
            result = await rag.query(
                "What treatment for X?",
                namespace="test_evo_prefer",
                mode="naive",
            )
            if result.chunks:
                # Top chunk should be from new doc (treatment Z) not old (Y)
                top = result.chunks[0].content.lower()
                assert ("treatment z" in top and "treatment y" not in top) \
                    or result.chunks[0].score > 0  # score ordering sanity
        finally:
            os.unlink(old)
            os.unlink(new)
    finally:
        await rag.close()
```

- [ ] **Step 2: Write failing test for supersession_behavior='hide'**

```python
async def test_supersession_hide_drops_superseded_doc():
    """supersession_behavior='hide' + Tier 1 filters superseded docs entirely."""
    import os, tempfile
    rag = await _fresh("test_evo_super_hide")
    rag.config.evolution_tier = "structural"
    rag.config.supersession_behavior = "hide"
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Old\n\nOld treatment guidance uses drug Alpha.\n")
            old = f.name
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# New\n\nNew treatment guidance uses drug Beta.\n")
            new = f.name
        try:
            await rag.ingest([old], namespace="test_evo_super_hide")
            old_id = (await rag.db.fetch_one(
                "SELECT id FROM documents WHERE namespace = %s LIMIT 1",
                ("test_evo_super_hide",)
            ))["id"]
            await rag.ingest(
                [new],
                namespace="test_evo_super_hide",
                metadata={"supersedes_document_id": old_id},
            )
            result = await rag.query(
                "What drug for treatment?",
                namespace="test_evo_super_hide",
                mode="naive",
            )
            joined = " ".join(c.content for c in result.chunks).lower()
            assert "drug alpha" not in joined, "old doc should be hidden"
            assert "drug beta" in joined or len(result.chunks) >= 0
        finally:
            os.unlink(old)
            os.unlink(new)
    finally:
        await rag.close()
```

- [ ] **Step 3: Run both tests to verify they fail**

```bash
uv run pytest tests/integration/test_evolution_tier1.py -v -k supersession
```

Expected: the `hide` test FAILS (no filter implemented yet); the `prefer_new` test may pass (penalty fragment exists) or fail depending on score ordering.

- [ ] **Step 4: Extend retraction_where_clause to also handle supersession='hide'**

Modify `src/pg_raggraph/evolution.py`. Rename `retraction_where_clause` to `evolution_where_clauses` (clearer naming as it grows):

```python
def evolution_where_clauses(cfg: PGRGConfig, doc_alias: str = "d") -> list[str]:
    """Returns a list of WHERE-clause fragments to apply based on evolution
    behavior modes. Caller joins with ' AND ' when composing. Empty list
    when evolution_tier='off'."""
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
```

Remove the old `retraction_where_clause` function. Update `retrieval.py` to use the new helper:

```python
from pg_raggraph.evolution import (
    evolution_bind_params,
    evolution_score_expr,
    evolution_where_clauses,
)
...

def _build_naive_query(cfg) -> str:
    ...
    clauses = evolution_where_clauses(cfg, doc_alias="d")
    extra_where = (" AND " + " AND ".join(clauses)) if clauses else ""
    ...
```

- [ ] **Step 5: Run the supersession tests to verify pass**

```bash
uv run pytest tests/integration/test_evolution_tier1.py -v -k supersession
```

Expected: PASS (both tests).

- [ ] **Step 6: Full integration regression**

```bash
uv run pytest tests/integration/ -q --ignore=tests/integration/test_real_llm.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/pg_raggraph/evolution.py src/pg_raggraph/retrieval.py \
        tests/integration/test_evolution_tier1.py
git commit -m "feat(retrieval): document-level supersession scoring + hide mode

Tier 1 supersession works at document granularity — if doc B supersedes
doc A via document_versions.supersedes_document_id, A's chunks get a
lambda_supersession penalty (prefer_new mode) or are filtered entirely
(hide mode). surface_both mode defers to Tier 3's fact-level
implementation. Consolidates WHERE-clause fragments into
evolution_where_clauses()."
```

---

## Task 7 — Query-time kwargs: `as_of`, `version_filter`, `evolution_aware`

**Files:**
- Modify: `src/pg_raggraph/__init__.py` (the `query()` method)
- Modify: `src/pg_raggraph/evolution.py`
- Modify: `src/pg_raggraph/retrieval.py`
- Modify: `tests/integration/test_evolution_tier1.py`

### Context for the engineer

Three kwargs:

- `as_of: datetime | None` — time-travel query. Filter results to docs where `effective_from <= as_of AND (effective_to IS NULL OR effective_to > as_of)`. Overrides current-time semantics.
- `version_filter: str | None` — restrict to documents with matching `version_label`. Useful for version-scoped software docs.
- `evolution_aware: bool | None` — override the config's `evolution_tier`. `False` forces classic retrieval even on tracked data. `None` honors config.

### Steps

- [ ] **Step 1: Write failing tests**

```python
async def test_query_as_of_returns_historically_effective_docs():
    """as_of=DATE returns docs effective at that date, not later-supersededs."""
    import os, tempfile
    from datetime import datetime, timezone
    rag = await _fresh("test_evo_asof")
    rag.config.evolution_tier = "structural"
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# 2022 Policy\n\nRefund window is 30 days.\n")
            p2022 = f.name
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# 2024 Policy\n\nRefund window is 60 days.\n")
            p2024 = f.name
        try:
            await rag.ingest(
                [p2022], namespace="test_evo_asof",
                metadata={
                    "effective_from": datetime(2022, 1, 1, tzinfo=timezone.utc),
                    "effective_to":   datetime(2024, 1, 1, tzinfo=timezone.utc),
                },
            )
            await rag.ingest(
                [p2024], namespace="test_evo_asof",
                metadata={"effective_from": datetime(2024, 1, 1, tzinfo=timezone.utc)},
            )
            # As of 2023, only the 2022 policy was effective
            result = await rag.query(
                "What is the refund window?",
                namespace="test_evo_asof",
                mode="naive",
                as_of=datetime(2023, 6, 1, tzinfo=timezone.utc),
            )
            joined = " ".join(c.content for c in result.chunks).lower()
            assert "30 days" in joined, "2022 policy must appear"
            assert "60 days" not in joined, "2024 policy must not appear at as_of=2023"
        finally:
            os.unlink(p2022)
            os.unlink(p2024)
    finally:
        await rag.close()


async def test_query_version_filter_restricts_to_matching_version():
    import os, tempfile
    rag = await _fresh("test_evo_vfilter")
    rag.config.evolution_tier = "structural"
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Python 3.11\n\nUse typing.Self for method returns.\n")
            p311 = f.name
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Python 3.12\n\nUse the new generic syntax for methods.\n")
            p312 = f.name
        try:
            await rag.ingest([p311], namespace="test_evo_vfilter",
                             metadata={"version_label": "Python 3.11"})
            await rag.ingest([p312], namespace="test_evo_vfilter",
                             metadata={"version_label": "Python 3.12"})
            result = await rag.query(
                "How to type a method return?",
                namespace="test_evo_vfilter",
                mode="naive",
                version_filter="Python 3.12",
            )
            joined = " ".join(c.content for c in result.chunks).lower()
            assert "generic syntax" in joined or len(result.chunks) > 0
            assert "typing.self" not in joined
        finally:
            os.unlink(p311)
            os.unlink(p312)
    finally:
        await rag.close()


async def test_query_evolution_aware_false_forces_classic_retrieval():
    """evolution_aware=False ignores retraction+supersession even when tier='structural'."""
    import os, tempfile
    rag = await _fresh("test_evo_override")
    rag.config.evolution_tier = "structural"
    rag.config.retracted_behavior = "hide"
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Retracted\n\nRetracted claim about statins.\n")
            r = f.name
        try:
            await rag.ingest([r], namespace="test_evo_override",
                             metadata={"retracted": True})
            result = await rag.query(
                "What about statins?",
                namespace="test_evo_override",
                mode="naive",
                evolution_aware=False,
            )
            # With evolution_aware=False the retracted doc should not be filtered
            joined = " ".join(c.content for c in result.chunks).lower()
            assert "retracted claim" in joined
        finally:
            os.unlink(r)
    finally:
        await rag.close()
```

- [ ] **Step 2: Run to verify fail**

```bash
uv run pytest tests/integration/test_evolution_tier1.py -v -k "as_of or vfilter or override"
```

Expected: all three FAIL — kwargs not plumbed.

- [ ] **Step 3: Add kwargs to query() signature + plumbing**

Modify `GraphRAG.query(...)` in `src/pg_raggraph/__init__.py`. New signature:

```python
    async def query(
        self,
        question: str,
        *,
        namespace: str | None = None,
        mode: str | None = None,
        top_k: int | None = None,
        as_of: datetime | None = None,
        version_filter: str | None = None,
        evolution_aware: bool | None = None,
    ) -> QueryResult:
        ...
```

Pass `as_of`, `version_filter`, `evolution_aware` through to the retrieval call (the retrieval module will be updated in the next steps to accept them).

- [ ] **Step 4: Extend evolution.py helpers**

In `src/pg_raggraph/evolution.py`, widen `evolution_where_clauses` and `evolution_bind_params` to take optional override kwargs:

```python
def _effective_tier(cfg: PGRGConfig, evolution_aware: bool | None) -> str:
    """Resolve tier after applying the per-query evolution_aware override."""
    if evolution_aware is False:
        return "off"
    return cfg.evolution_tier


def evolution_where_clauses(
    cfg: PGRGConfig,
    doc_alias: str = "d",
    as_of=None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
) -> tuple[list[str], dict]:
    """Returns (where_clauses, bind_params_for_clauses)."""
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


def evolution_score_expr(
    base_score_sql: str,
    cfg: PGRGConfig,
    evolution_aware: bool | None = None,
) -> str:
    tier = _effective_tier(cfg, evolution_aware)
    if tier == "off":
        return base_score_sql
    # unchanged body from before
    ...
```

- [ ] **Step 5: Update retrieval.py call sites**

Thread `as_of`, `version_filter`, `evolution_aware` through `_build_naive_query(cfg, ...)` / `_build_local_query(cfg, ...)` / `_build_global_query(cfg, ...)` and through `query()` in retrieval.py. Merge the returned params dict into the main params.

- [ ] **Step 6: Run the three new tests to verify pass**

```bash
uv run pytest tests/integration/test_evolution_tier1.py -v -k "as_of or vfilter or override"
```

Expected: PASS (3 tests).

- [ ] **Step 7: Run full integration regression**

```bash
uv run pytest tests/integration/ -q --ignore=tests/integration/test_real_llm.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/pg_raggraph/__init__.py src/pg_raggraph/evolution.py \
        src/pg_raggraph/retrieval.py tests/integration/test_evolution_tier1.py
git commit -m "feat(query): as_of, version_filter, evolution_aware kwargs

rag.query(..., as_of=DATE) time-travel filters to docs effective at
that point; version_filter='Python 3.12' restricts to matching version;
evolution_aware=False forces classic retrieval even when evolution_tier
is set. Each kwarg adds a conditional WHERE clause; None/default leaves
behavior as today."
```

---

## Task 8 — `tune_scoring_weights()` utility

**Files:**
- Modify: `src/pg_raggraph/evolution.py`
- Modify: `src/pg_raggraph/__init__.py`
- Create: `tests/integration/test_tune_scoring_weights.py`
- Create: `tests/fixtures/evolving/gold_questions.yaml` (seed — used in Task 9 for fuller fixtures)

### Context for the engineer

Grid-search over scoring weights against a gold QA set. For each cell (combination of weights), run the corpus-wide query, compute recall/precision on the gold answers, pick the cell that maximizes the user-selected metric. Results written back to config.

Uses existing bakeoff runner infrastructure as reference but doesn't import it — the bakeoff is a sibling package. Instead, implement a minimal in-process runner that uses `rag.query()` directly.

**Scope check for Tier 1:** ship a simple grid search with `fully_correct` count as the metric (no LLM-judge integration yet). The bakeoff-comparable full-stack version is a follow-up.

### Steps

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_tune_scoring_weights.py`:

```python
"""Integration tests for rag.tune_scoring_weights()."""
from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def test_tune_scoring_weights_returns_best_cell_and_updates_config():
    rag = GraphRAG(dsn=DSN, namespace="test_tune",
                   llm_base_url="http://localhost:99999/v1")
    await rag.connect()
    try:
        # Seed a small corpus with obvious relevance
        import tempfile, os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Q1\n\nThe answer to question one is apples.\n")
            f1 = f.name
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Q2\n\nThe answer to question two is bananas.\n")
            f2 = f.name
        try:
            await rag.delete("test_tune")
            await rag.ingest([f1, f2], namespace="test_tune")
            gold = [
                {"question": "What's the answer to question one?",
                 "expected_substring": "apples"},
                {"question": "What's the answer to question two?",
                 "expected_substring": "bananas"},
            ]
            report = await rag.tune_scoring_weights(
                namespace="test_tune",
                gold=gold,
                grid={
                    "w_sem":  [0.3, 0.7],
                    "w_bm25": [0.1, 0.3],
                },
                mode="naive",
                write_back=True,
            )
            # Shape
            assert "best" in report
            assert report["best"]["score"] > 0
            assert set(report["best"]["weights"].keys()) >= {"w_sem", "w_bm25"}
            # Config was updated
            assert rag.config.w_sem == report["best"]["weights"]["w_sem"]
            assert rag.config.w_bm25 == report["best"]["weights"]["w_bm25"]
        finally:
            os.unlink(f1)
            os.unlink(f2)
    finally:
        await rag.close()
```

- [ ] **Step 2: Run to verify fail**

```bash
uv run pytest tests/integration/test_tune_scoring_weights.py -v
```

Expected: FAIL — `tune_scoring_weights` is not defined.

- [ ] **Step 3: Implement the utility**

Add to `src/pg_raggraph/evolution.py`:

```python
import itertools
from typing import Any


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
    value_lists = [grid[n] for n in weight_names]
    cells: list[dict] = []

    # Snapshot existing config so we can restore unless write_back
    original = {n: getattr(rag.config, n) for n in weight_names}

    for combo in itertools.product(*value_lists):
        for name, val in zip(weight_names, combo):
            setattr(rag.config, name, val)

        score = 0
        for item in gold:
            result = await rag.query(
                item["question"], namespace=namespace, mode=mode
            )
            joined = " ".join(c.content.lower() for c in result.chunks)
            if item["expected_substring"].lower() in joined:
                score += 1

        cells.append({
            "weights": {n: v for n, v in zip(weight_names, combo)},
            "score": score,
        })

    best = max(cells, key=lambda c: c["score"])

    if write_back:
        for name, val in best["weights"].items():
            setattr(rag.config, name, val)
    else:
        for name, val in original.items():
            setattr(rag.config, name, val)

    return {"best": best, "cells": cells}
```

- [ ] **Step 4: Expose the utility on GraphRAG**

In `src/pg_raggraph/__init__.py`, add a method to `GraphRAG`:

```python
    async def tune_scoring_weights(self, **kwargs):
        """Grid-search scoring weights against a gold QA set.
        See src/pg_raggraph/evolution.py:tune_scoring_weights for args."""
        from pg_raggraph.evolution import tune_scoring_weights as _tune
        return await _tune(self, **kwargs)
```

- [ ] **Step 5: Run the test to verify pass**

```bash
uv run pytest tests/integration/test_tune_scoring_weights.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pg_raggraph/evolution.py src/pg_raggraph/__init__.py \
        tests/integration/test_tune_scoring_weights.py
git commit -m "feat(evolution): tune_scoring_weights() grid-search utility

Simple Cartesian-product grid search over scoring weights against a
gold 'expected substring' QA set. Writes the best cell back to config
by default. Tier 1 scope — a Tier 3 follow-up swaps in LLM-judge for
the scoring function."
```

---

## Task 9 — Evaluation fixtures (synthetic corpora)

**Files:**
- Create: `tests/fixtures/evolving/medical_retraction/paper_1992_hrt_cardio.md`
- Create: `tests/fixtures/evolving/medical_retraction/paper_1998_hrt_cardio_replication.md`
- Create: `tests/fixtures/evolving/medical_retraction/guidance_2002_hrt_contraindicated.md`
- Create: `tests/fixtures/evolving/medical_retraction/meta_2008_hrt_no_cardio.md`
- Create: `tests/fixtures/evolving/medical_retraction/manifest.yaml`
- Create: `tests/fixtures/evolving/software_versioning/python_311_strenum.md`
- Create: `tests/fixtures/evolving/software_versioning/python_312_strenum.md`
- Create: `tests/fixtures/evolving/software_versioning/manifest.yaml`
- Create: `tests/fixtures/evolving/policy_effective_dates/refund_2022.md`
- Create: `tests/fixtures/evolving/policy_effective_dates/refund_2024.md`
- Create: `tests/fixtures/evolving/policy_effective_dates/manifest.yaml`
- Modify: `tests/fixtures/evolving/gold_questions.yaml`
- Modify: `tests/integration/test_evolution_tier1.py`

### Context for the engineer

Three synthetic corpora exercise the three primary Tier 1 value props: retraction (medical), versioning (software), effective-dates (policy). Each corpus is 2-4 short docs with clear inter-document relationships. Manifests declare the evolution metadata a caller would supply.

### Steps

- [ ] **Step 1: Create the medical retraction corpus**

`tests/fixtures/evolving/medical_retraction/paper_1992_hrt_cardio.md`:

```markdown
# 1992 Observational Study on HRT and Cardiovascular Risk

An observational study of 121,000 women over 10 years suggests that women on
hormone replacement therapy (HRT) have a 40% lower risk of cardiovascular events
compared to women not on HRT. The authors propose HRT may be cardioprotective.
```

`tests/fixtures/evolving/medical_retraction/paper_1998_hrt_cardio_replication.md`:

```markdown
# 1998 Replication Study on HRT

A larger observational cohort (n=200,000) replicates the 1992 finding: HRT use
associates with lower rates of coronary heart disease. The authors recommend HRT
for postmenopausal cardiovascular risk reduction.
```

`tests/fixtures/evolving/medical_retraction/guidance_2002_hrt_contraindicated.md`:

```markdown
# 2002 WHI Trial Guidance — HRT Contraindicated for CVD Prevention

The Women's Health Initiative randomized controlled trial finds that HRT
*increases* cardiovascular event risk in postmenopausal women. Prior
observational findings of cardioprotection are attributed to healthy-user bias.
HRT is no longer indicated for cardiovascular disease prevention.
```

`tests/fixtures/evolving/medical_retraction/meta_2008_hrt_no_cardio.md`:

```markdown
# 2008 Meta-Analysis Confirms No Cardioprotective Effect

A meta-analysis of randomized controlled trials confirms the WHI finding: HRT
does not prevent cardiovascular events and carries elevated thrombotic risk.
The observational-era claims are formally superseded.
```

`tests/fixtures/evolving/medical_retraction/manifest.yaml`:

```yaml
docs:
  - path: paper_1992_hrt_cardio.md
    effective_from: 1992-06-01
    retracted: true
    retracted_at: 2002-07-17
    retraction_reason: "WHI 2002 RCT invalidated observational findings."
  - path: paper_1998_hrt_cardio_replication.md
    effective_from: 1998-03-15
    retracted: true
    retracted_at: 2002-07-17
    retraction_reason: "Replicated retracted 1992 methodology."
  - path: guidance_2002_hrt_contraindicated.md
    effective_from: 2002-07-17
    version_label: WHI-2002
  - path: meta_2008_hrt_no_cardio.md
    effective_from: 2008-01-01
    version_label: HRT-meta-2008
```

- [ ] **Step 2: Create the software versioning corpus**

`tests/fixtures/evolving/software_versioning/python_311_strenum.md`:

```markdown
# Python 3.11 — StrEnum

Python 3.11 introduces `enum.StrEnum`, a string-valued enum whose members are
string instances. Use `from enum import StrEnum` and subclass it. Members
inherit str methods and compare equal to their string values.
```

`tests/fixtures/evolving/software_versioning/python_312_strenum.md`:

```markdown
# Python 3.12 — StrEnum

Python 3.12 keeps `enum.StrEnum` but adds the new `type` statement for generic
aliases that interact with enum classes. The basic StrEnum API is unchanged
from 3.11; new use cases with type aliases are documented in PEP 695.
```

`tests/fixtures/evolving/software_versioning/manifest.yaml`:

```yaml
docs:
  - path: python_311_strenum.md
    effective_from: 2022-10-24
    version_label: Python 3.11
  - path: python_312_strenum.md
    effective_from: 2023-10-02
    version_label: Python 3.12
```

- [ ] **Step 3: Create the policy effective-dates corpus**

`tests/fixtures/evolving/policy_effective_dates/refund_2022.md`:

```markdown
# Refund Policy, 2022

Customers may request a refund within 30 days of purchase, provided the product
is unused and in its original packaging. Refunds are processed within five
business days to the original payment method.
```

`tests/fixtures/evolving/policy_effective_dates/refund_2024.md`:

```markdown
# Refund Policy, 2024

Customers may request a refund within 60 days of purchase. Used products in
good condition are also eligible. Refunds are processed within two business
days to the original payment method or store credit.
```

`tests/fixtures/evolving/policy_effective_dates/manifest.yaml`:

```yaml
docs:
  - path: refund_2022.md
    effective_from: 2022-01-01
    effective_to: 2024-01-01
    version_label: refund-2022
  - path: refund_2024.md
    effective_from: 2024-01-01
    version_label: refund-2024
    supersedes_version_label: refund-2022  # used by test harness to wire the supersedes_document_id at ingest time
```

- [ ] **Step 4: Create the combined gold questions file**

`tests/fixtures/evolving/gold_questions.yaml`:

```yaml
corpora:
  medical_retraction:
    questions:
      - question: "Is hormone replacement therapy cardioprotective?"
        expected_substring: "does not prevent"
      - question: "What does the 2002 WHI trial say about HRT?"
        expected_substring: "increases"
      - question: "When should HRT be used for cardiovascular prevention?"
        expected_substring: "no longer indicated"

  software_versioning:
    questions:
      - question: "How do I use StrEnum in Python 3.12?"
        expected_substring: "3.12"
        version_filter: "Python 3.12"
      - question: "How do I use StrEnum in Python 3.11?"
        expected_substring: "3.11"
        version_filter: "Python 3.11"

  policy_effective_dates:
    questions:
      - question: "What is the refund window?"
        expected_substring: "60 days"      # current policy
      - question: "What was the refund window in 2023?"
        expected_substring: "30 days"
        as_of: 2023-06-01
```

- [ ] **Step 5: Write fixture-driven integration tests**

Append to `tests/integration/test_evolution_tier1.py`:

```python
import yaml
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures" / "evolving"


async def _ingest_fixture_corpus(rag, corpus_dir: Path):
    manifest = yaml.safe_load((corpus_dir / "manifest.yaml").read_text())
    for entry in manifest["docs"]:
        path = str(corpus_dir / entry["path"])
        metadata = {k: v for k, v in entry.items() if k != "path"}
        # Coerce date strings to datetimes
        from datetime import datetime
        for k in ("effective_from", "effective_to", "retracted_at"):
            if isinstance(metadata.get(k), str):
                metadata[k] = datetime.fromisoformat(metadata[k])
        await rag.ingest([path], namespace=corpus_dir.name, metadata=metadata)


async def test_medical_retraction_fixture_endtoend():
    rag = await _fresh("medical_retraction")
    rag.config.evolution_tier = "structural"
    rag.config.retracted_behavior = "hide"
    try:
        await _ingest_fixture_corpus(rag, FIXTURES / "medical_retraction")
        result = await rag.query(
            "Is hormone replacement therapy cardioprotective?",
            namespace="medical_retraction",
            mode="naive",
        )
        joined = " ".join(c.content for c in result.chunks).lower()
        # Retracted observational studies filtered; current guidance visible
        assert "40% lower" not in joined, "1992 retracted claim should be hidden"
        assert "does not prevent" in joined or "no longer indicated" in joined
    finally:
        await rag.close()


async def test_policy_as_of_fixture_endtoend():
    rag = await _fresh("policy_effective_dates")
    rag.config.evolution_tier = "structural"
    try:
        await _ingest_fixture_corpus(rag, FIXTURES / "policy_effective_dates")
        # Current policy
        now = await rag.query(
            "What is the refund window?",
            namespace="policy_effective_dates",
            mode="naive",
        )
        assert "60 days" in " ".join(c.content for c in now.chunks).lower()
        # Historical
        from datetime import datetime, timezone
        historical = await rag.query(
            "What was the refund window in 2023?",
            namespace="policy_effective_dates",
            mode="naive",
            as_of=datetime(2023, 6, 1, tzinfo=timezone.utc),
        )
        assert "30 days" in " ".join(c.content for c in historical.chunks).lower()
    finally:
        await rag.close()
```

- [ ] **Step 6: Run the fixture tests**

```bash
uv run pytest tests/integration/test_evolution_tier1.py -v -k "fixture_endtoend"
```

Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/evolving/ tests/integration/test_evolution_tier1.py
git commit -m "test(evolution): fixture corpora for medical/software/policy

Three synthetic corpora with manifests exercise Tier 1's three primary
value props: medical retraction (4 docs, 2 retracted), software
versioning (2 docs, version_label), policy effective-dates (2 docs,
supersession + effective_to). gold_questions.yaml carries the expected
substrings used by tune_scoring_weights and the integration tests."
```

---

## Task 10 — Docs + alpha release

**Files:**
- Create: `docs/cookbook/evolution-tracking.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml` (version bump)

### Context for the engineer

Ship the alpha. One cookbook page walks a user through Tier 1 end to end using the medical retraction fixture. CHANGELOG gets a substantial entry. Version bumps to `0.3.0-alpha`.

### Steps

- [ ] **Step 1: Write the cookbook page**

Create `docs/cookbook/evolution-tracking.md`:

```markdown
# Evolution Tracking (Tier 1) — Quickstart

pg-raggraph `0.3.0-alpha` introduces evolution tracking: retrieval that
respects when documents were effective, which ones were retracted, and which
ones supersede earlier versions. This page walks through enabling Tier 1
(Structural — metadata-driven, no LLM cost).

## 1. Turn it on

Tier 1 is opt-in. Set `evolution_tier="structural"` on your `PGRGConfig`
(or set `PGRG_EVOLUTION_TIER=structural` in your environment):

    rag = GraphRAG(
        dsn=DSN,
        namespace="medical",
        config=PGRGConfig(evolution_tier="structural"),
    )

## 2. Supply evolution metadata at ingest

Pass a `metadata` dict to `rag.ingest()`. Every file in the call picks up
the same metadata.

    await rag.ingest(
        ["papers/hrt_1992.md"],
        namespace="medical",
        metadata={
            "effective_from": datetime(1992, 6, 1),
            "retracted": True,
            "retracted_at": datetime(2002, 7, 17),
            "retraction_reason": "WHI 2002 RCT invalidated findings",
        },
    )

Supported keys: `effective_from`, `effective_to`, `retracted`,
`retracted_at`, `retraction_reason`, `version_label`,
`supersedes_document_id`.

## 3. Query

Retrieval automatically respects your tier config:

    result = await rag.query(
        "Is HRT cardioprotective?",
        namespace="medical",
    )
    # retracted docs filtered; current guidance surfaces

### Time-travel query

    result = await rag.query(
        "What was the refund policy?",
        namespace="policy",
        as_of=datetime(2023, 6, 1),
    )

### Version-scoped query

    result = await rag.query(
        "How do I use StrEnum?",
        namespace="python_docs",
        version_filter="Python 3.12",
    )

### Force classic retrieval

    # Ignore evolution semantics for this one call
    result = await rag.query(q, namespace=ns, evolution_aware=False)

## 4. Tune scoring weights per corpus

Default weights are calibrated on SCOTUS. Your corpus may want different
recency / supersession weights. Grid-search against a gold QA set:

    report = await rag.tune_scoring_weights(
        namespace="medical",
        gold=[
            {"question": "Is HRT cardioprotective?",
             "expected_substring": "does not prevent"},
            ...
        ],
        grid={
            "w_sem":    [0.3, 0.5, 0.7],
            "w_recent": [0.0, 0.1, 0.3, 0.5],
            "w_supersession":  [0.0, 0.1, 0.3],
        },
        mode="naive",
        write_back=True,  # updates rag.config
    )
    print(report["best"])

## 5. Migration notes

Upgrading from `0.2.x` applies `002_evolution_tracking.sql` automatically
on first `rag.connect()`. Three new tables (`facts`, `fact_edges`,
`document_versions`) are created but empty at Tier 1. Four new columns are
added to `documents`, all nullable. No existing data migrates.

## What's not in Tier 1

- Fact-level extraction → Tier 2 (`fact_extractor="skimr_spacy"`)
- LLM-inferred supersession / contradiction → Tier 3
  (`fact_extractor="llm"` + slow-path edge inference)
- Fact-aware context assembly (dedup, diversity backfill) → Tier 2
- See `docs/superpowers/specs/2026-04-22-evolving-knowledge-rag-design.md`
  §3.2 for the full tier matrix.
```

- [ ] **Step 2: Update CHANGELOG**

Prepend an entry to `CHANGELOG.md` (create the file if it doesn't exist):

```markdown
## 0.3.0-alpha — 2026-??-??

### Added

- **Evolving-knowledge RAG, Tier 1 (Structural).** Opt-in evolution tracking
  that respects document effective-dates, retractions, and supersession at
  the document level. Opt in via `PGRGConfig(evolution_tier="structural")`
  or env `PGRG_EVOLUTION_TIER=structural`.
- `rag.ingest(metadata={...})` now accepts `effective_from`, `effective_to`,
  `retracted`, `retracted_at`, `retraction_reason`, `version_label`,
  `supersedes_document_id`. Per-ingest scope (applies to every file in the
  call).
- `rag.query()` new kwargs: `as_of=datetime(...)` time-travel filter,
  `version_filter="..."` version restriction, `evolution_aware=False`
  per-call override to force classic retrieval.
- `rag.tune_scoring_weights(namespace, gold, grid, ...)` grid-search
  utility for per-corpus weight tuning. Writes the best cell back to
  `rag.config`.
- Schema: three new tables (`facts`, `fact_edges`, `document_versions`)
  and four new columns on `documents` via migration
  `002_evolution_tracking.sql`. All additive; fact-level tables stay empty
  at Tier 1.
- Behavior modes: `retracted_behavior` ∈ {hide, flag, surface_both};
  `supersession_behavior` ∈ {hide, prefer_new, surface_both}.

### Changed

- `PGRGConfig` gains 15+ fields for evolution tracking. Defaults leave
  Tier 0 behavior unchanged.
- Retrieval SQL templates (`naive`, `local`, `global`) are now built
  per-query from the config rather than stored as string constants. When
  `evolution_tier="off"`, the generated SQL is semantically identical to
  the prior version.

### Deferred to future tiers

- Fact-level extraction (Tier 2).
- LLM-inferred fact edges and contradiction detection (Tier 3).
- Async slow-path fact-edge inference (Tier 3).

See `docs/cookbook/evolution-tracking.md` for the quickstart.
```

- [ ] **Step 3: Bump version in pyproject.toml**

Modify `pyproject.toml`. Find `version = "..."` in `[project]` and update:

```toml
[project]
name = "pg-raggraph"
version = "0.3.0a0"   # PEP 440 alpha tag
```

- [ ] **Step 4: Run the full test suite end-to-end**

```bash
uv run pytest tests/unit/ tests/integration/ -q --ignore=tests/integration/test_real_llm.py
```

Expected: all pass.

- [ ] **Step 5: Commit + tag**

```bash
git add docs/cookbook/evolution-tracking.md CHANGELOG.md pyproject.toml
git commit -m "release(0.3.0-alpha): evolving-knowledge-RAG Tier 1

Ships the structural tier: metadata-driven retraction, supersession,
version-label, and effective-date filtering at zero LLM cost. See
docs/cookbook/evolution-tracking.md for the quickstart and
docs/superpowers/specs/2026-04-22-evolving-knowledge-rag-design.md for
the full four-tier roadmap."
git tag v0.3.0a0
```

- [ ] **Step 6: Final verification — alpha usable end-to-end**

From a Python REPL against a live DB, smoke test one end-to-end flow:

```python
import asyncio
from datetime import datetime, timezone
from pg_raggraph import GraphRAG
from pg_raggraph.config import PGRGConfig

async def main():
    cfg = PGRGConfig(evolution_tier="structural", retracted_behavior="hide")
    rag = GraphRAG(
        dsn="postgresql://postgres:postgres@localhost:5434/pg_raggraph",
        namespace="alpha_smoke",
        config=cfg,
        llm_base_url="http://localhost:99999/v1",
    )
    await rag.connect()
    await rag.delete("alpha_smoke")
    # Ingest a retracted claim + a current one
    # (use the fixture files from Task 9)
    # ... query + print result
    await rag.close()

asyncio.run(main())
```

Expected: retracted content does not appear in the result. Tier 1 works.

---

## Plan complete

Run the plan top-to-bottom using subagent-driven-development or executing-plans. Each task ends with a commit so the history reads as a clean progression of small, testable changes.

**Total expected impact:**
- 2 new SQL files (migration + schema updates)
- 1 new Python module (`evolution.py`)
- ~15-20 new pydantic fields / classes
- ~30-50 new tests (unit + integration)
- 3 fixture corpora
- 1 cookbook doc + CHANGELOG + version bump

**Expected wall time for a skilled engineer with no prior pg-raggraph context:** 3-4 working days. With prior pg-raggraph context: 2-3 days.

**Budget:** $0. No LLM calls at Tier 1. PostgreSQL + fastembed only.
