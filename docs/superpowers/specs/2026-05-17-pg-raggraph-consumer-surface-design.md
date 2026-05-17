---
title: pg-raggraph Consumer Surface (PRG-1..4) — Implementation Design
created: 2026-05-17
status: approved design — ready for implementation planning
source-requirements: stele-phase4/docs/superpowers/specs/2026-05-17-pg-raggraph-requirements.md
grounded-in: pg-raggraph 0.3.0a2 source (models.py, retrieval.py, evolution.py, __init__.py, db.py, sql/)
target-release: 0.3.0a3 (additive alpha bump)
---

# pg-raggraph Consumer Surface — Implementation Design

## Purpose

Add a thin, optional, back-compatible **consumer-facing read/write surface** on
top of pg-raggraph's already-built evolution engine. The hard engine (temporal
`as_of`, `version_filter`, `retracted_behavior`, `document_versions`, evolution
columns, async lifecycle) exists and is unchanged. This work exposes four
additions: PRG-1 (metadata + evolution round-trip on results), PRG-2 post-hoc
`retract()`, PRG-3 post-hoc `supersede()`, PRG-4 stable `chunk_id` guarantee.
PRG-5 (chain "current view") is **explicitly out of scope**.

## Non-negotiable governing constraints

1. **Product-neutral.** No consumer concept (no `stele://`, no typed
   `source_ref`). `metadata` is an opaque `dict` pass-through of
   `documents.metadata`.
2. **100% optional.** A caller that ingests no metadata and never calls the new
   methods sees byte-identical behavior to 0.3.0a2. New result fields default
   to `None`.
3. **Back-compatible.** No breaking change to signatures, return shapes
   (additive optional fields only), schema (uses existing columns — no
   migration), or defaults.
4. **Additive release.** Ships as `0.3.0a3`; the consumer pins the exact
   version.

## Confirmed design decisions (owner-approved 2026-05-17)

- **DEC-1 Code organization.** `retract()` / `supersede()` are methods on
  `GraphRAG` with SQL **inline in `__init__.py`**, matching the closest
  existing siblings (`delete_document`, `merge_entities`, `prune_orphans`).
  `evolution.py` stays scoped to read-path SQL fragments + grid search.
- **DEC-2 Release in scope.** Version bump `0.3.0a2 → 0.3.0a3`, CHANGELOG
  entry, and README badge land on the same branch — the "Definition of ready"
  requires a pinnable version.
- **DEC-3 `superseded_by_id` is the inverse lookup.** For document `d`,
  `superseded_by_id` = the `document_versions` row where
  `supersedes_document_id = d.id`, returning that row's `document_id` ("the
  doc that replaced me"). This pairs with `supersede()` writing the new→old
  pointer.
- **DEC-4 PRG-1 metadata mapping.** `documents.metadata` DB default is `'{}'`
  (never NULL); when empty/falsy, `ChunkResult.metadata` is mapped to `None`
  (acceptance requires "no metadata → `.metadata is None`").
- **DEC-5 Tier gating.** `metadata` is always passed through (tier-independent
  caller data). The five evolution fields are `None` when the effective tier
  (after the `evolution_aware` override) is `"off"` — reuse
  `evolution._effective_tier`.
- **DEC-6 metadata is pure pass-through.** Evolution fields are separate
  `ChunkResult` attributes, never merged into the `metadata` dict (the spec's
  class snippet is authoritative).
- **DEC-7 Multi-match resolution.** `retract()` by `source_path` fans out to
  **all** documents in the namespace sharing that path and returns the count
  (retraction is per-doc and idempotent). `supersede()` by `*_source_path`
  requires the path to resolve to **exactly one** document on each side; a
  >1-match path raises `ValueError` (the supersession pointer is doc→doc and
  many↔many is meaningless).
- **DEC-8 `supersede()` `reason` storage.** `document_versions` has no generic
  supersession-reason column (`retraction_reason` is semantically wrong for a
  supersession). When `reason` is given it is stored in
  `document_versions.metadata` JSONB as `{"supersede_reason": reason}` —
  schema-additive, semantically clean. `retract()`'s `reason` maps cleanly to
  the existing `document_versions.retraction_reason` column.
- **DEC-9 `supersede()` upsert target.** "Upsert" resolves a single
  deterministic row, **excluding retraction-audit rows**:
  `SELECT id FROM document_versions WHERE document_id=<new>
  AND retracted = false ORDER BY id DESC LIMIT 1`; if found, `UPDATE` that
  row; else `INSERT` a fresh row. Idempotent — re-running writes the same
  pointer to the same row. The `retracted = false` filter (not merely an
  `ORDER BY`) means a document whose *only* `document_versions` rows are
  retraction-audit rows (written by a prior `retract()` on the new doc) gets
  a **fresh, clean** supersession row rather than having the
  `supersedes_document_id` pointer commingled onto a retraction record.
- **DEC-9a `supersede()` eager arg validation.** The "exactly one of
  `*_doc_id` / `*_source_path` per side" constraint is checked **before the
  transaction** for *both* sides (fail-fast on a malformed call with zero DB
  work), consistent with `retract()`'s pre-transaction validation. DB
  resolution (id-not-found, source_path→≠1) still happens inside the
  transaction. Net: an arg-shape error never depends on DB state or which
  side resolves first.
- **DEC-10 `as_of`-aware `supersession_behavior="hide"` (engine refinement,
  owner-approved amendment 2026-05-17).** Discovered during PRG-3
  implementation: the existing `evolution_where_clauses` `supersession_behavior
  ="hide"` clause is a *non-temporal* existence filter (`NOT EXISTS
  document_versions WHERE supersedes_document_id = d.id`), so it hid superseded
  docs in **all** queries — including historical `as_of` ones — which makes
  PRG-3's two acceptance properties ("current honors hide" + "`as_of=<before>`
  still returns the old doc") unsatisfiable against the unmodified engine. This
  is a genuine internal inconsistency in the original PRG-3 acceptance. **Owner
  decision: a small, deliberate, in-scope refinement to `evolution.py`** — when
  `as_of` is provided under `supersession_behavior="hide"`, rely on the
  `effective_to > as_of` temporal window for docs that **have** an
  `effective_to` (set by `supersede()`), but **preserve the legacy
  existence-hide** for docs superseded the old ingest-time way (supersedes
  pointer with `effective_to IS NULL`). Net clause: keep a row if it is not
  superseded **OR** it has an `effective_to`; hide only when superseded **AND**
  `effective_to IS NULL`. This makes new `supersede()` data temporally correct.
  **Precise back-compat boundary:** for the dominant legacy case — superseded
  the old ingest-time way *without* an `effective_to` (`effective_to IS NULL`)
  — behavior is **byte-identical** to before (still hidden in current *and*
  `as_of` queries); this is the regression that a blanket skip would have
  introduced, and it is closed and regression-tested
  (`test_prg3_legacy_supersede_without_effective_to_stays_hidden`). The **one
  deliberate, narrow refinement**: legacy data that carries *both* a supersedes
  pointer *and* an ingest-time `effective_to` will, under `as_of` queries, now
  be governed by the temporal window instead of the blunt existence-hide
  (current/non-`as_of` queries are unchanged — still hidden). That is the
  intended, more-correct behavior (a caller who set `effective_to` asked for
  temporal windowing) and is regression-tested
  (`test_prg3_legacy_supersede_with_effective_to_uses_window`). This
  supersedes the original PRG-3 "no new query-path branching" wording.

---

## PRG-1 — Return caller metadata + evolution status on query results *(critical, S)*

### models.py

Extend `ChunkResult` with six additive optional fields:

```python
class ChunkResult(BaseModel):
    content: str
    score: float
    document_source: str | None = None
    entities: list[str] = Field(default_factory=list)
    chunk_id: int | None = None
    # --- PRG-1 additive, all optional ---
    metadata: dict | None = None
    retracted: bool | None = None
    version_label: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    superseded_by_id: int | None = None
```

### retrieval.py

The three builders already `JOIN documents d` and select `d.source_path`. Add
to the `SELECT` list of `_build_naive_query`, `_build_local_query`,
`_build_global_query`:

- `d.metadata AS doc_metadata`
- `d.retracted`, `d.version_label`, `d.effective_from`, `d.effective_to`
- inverse supersession (DEC-3):
  `(SELECT dv.document_id FROM document_versions dv
    WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
   AS superseded_by_id`

No new bind parameters → the `_merge_params` collision guard is unaffected.

In `query()` where `ChunkResult(...)` is constructed (~line 337): populate the
new fields from the row. Mapping rules:

- `metadata`: `row["doc_metadata"] or None` (DEC-4 — empty dict → `None`).
- evolution fields: set from the row **only when** the effective tier is not
  `"off"`; otherwise `None` (DEC-5). Compute effective tier via
  `evolution._effective_tier(config, evolution_aware)`.

Coverage analysis (no extra code needed):
- `hybrid` merges raw local+global DB rows then builds `ChunkResult` once.
- `naive_boost` / `smart` delegate to `query()`.
- `_graph_boost` / `_merge_and_dedupe` mutate `score`/order only; they never
  reconstruct or drop `ChunkResult` fields.

### Acceptance (from source spec)

- Ingest doc with `metadata={"k":"v"}`; a `query()` hit returns
  `chunk.metadata == {"k":"v"}`.
- Ingest with no metadata → hit `.metadata is None`; all existing fields and
  scores byte-identical to pre-change.
- Retracted doc under `retracted_behavior="flag"` → `chunk.retracted is True`.
- `evolution_tier="off"` → all five evolution fields `None`; zero behavior
  change.

---

## PRG-2 — Post-hoc `retract()` *(high, S)*

Method on `GraphRAG`, inline SQL (DEC-1):

```python
async def retract(
    self,
    *,
    doc_id: int | None = None,
    source_path: str | None = None,
    reason: str = "",
    retracted_at: datetime | None = None,
    namespace: str | None = None,
) -> dict:  # {"retracted_count": int}
```

Behavior, in a single `self.db.transaction()`:

1. Require exactly one of `doc_id` / `source_path` (else `ValueError`).
   `ns = namespace or self.config.namespace`; `_validate_namespace(ns)`.
2. `retracted_at`: if provided and naive (`tzinfo is None`) → `ValueError`
   with the same message style as `as_of` in `evolution.py`. Default
   `datetime.now(timezone.utc)`.
3. Resolve target ids: by `doc_id` → `[doc_id]`; by `source_path` → all ids
   from `SELECT id FROM documents WHERE namespace=%s AND source_path=%s`
   (DEC-7 fan-out).
4. `UPDATE documents SET retracted=true WHERE id = ANY(%s)` — idempotent;
   re-retracting is a no-op success.
5. `document_versions`:
   `UPDATE document_versions SET retracted=true, retracted_at=%s,
   retraction_reason=%s WHERE document_id = ANY(%s)`; for any matched doc id
   that has **no** `document_versions` row, `INSERT` one
   `(namespace, document_id, retracted=true, retracted_at, retraction_reason)`.
   This keeps idempotency (no version-row explosion on repeat calls) while
   satisfying "write `document_versions.{retracted,retracted_at,
   retraction_reason}`".
6. Return `{"retracted_count": <number of documents whose row was updated>}`.

### Acceptance

- Ingest a normal doc; `retract(doc_id=...)`; `as_of=<before>` query still
  returns it; `as_of=<after>` / current query honors `retracted_behavior`.
- Idempotent: retracting an already-retracted doc is a no-op success
  (`retracted_count` reflects matched docs, no error).
- Naive `retracted_at` → `ValueError`.

---

## PRG-3 — Post-hoc `supersede()` *(high, S)*

Method on `GraphRAG`, inline SQL (DEC-1):

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
) -> dict:  # {"updated": int}
```

Behavior, in a single `self.db.transaction()`:

1. `ns = namespace or self.config.namespace`; `_validate_namespace(ns)`.
2. Resolve `old` from exactly one of `old_doc_id`/`old_source_path`, `new`
   from exactly one of `new_doc_id`/`new_source_path` (else `ValueError`).
   A `*_source_path` that resolves to ≠1 document → `ValueError` (DEC-7
   strict). `old != new` (else `ValueError`).
3. `effective_at`: naive → `ValueError`; default `datetime.now(timezone.utc)`.
4. Upsert the **new** doc's `document_versions` row (DEC-9 target rule):
   if a row exists, `UPDATE` it `SET supersedes_document_id = old`
   (and `metadata = metadata || '{"supersede_reason": <reason>}'::jsonb`
   when `reason` given, per DEC-8); else `INSERT (namespace, document_id=new,
   supersedes_document_id=old, metadata=<{"supersede_reason": reason}> or
   '{}')`. No `effective_*` is written on the version row — temporal
   windowing lives on `documents` (step 5); the version row only carries the
   pointer.
5. `UPDATE documents SET effective_to = %s WHERE id = old` (`effective_at`) —
   the existing temporal window SQL then governs historical visibility. Under
   `supersession_behavior="hide"` the engine applies the **DEC-10**
   `as_of`-aware clause so `as_of=<before>` correctly surfaces the
   not-yet-superseded old doc while current queries still hide it.
6. Return `{"updated": <rows changed>}`.

### Acceptance

- Ingest A then B; `supersede(old=A,new=B)`; current query honors
  `supersession_behavior`; `as_of=<before effective_at>` still returns A
  (via DEC-10 — A carries an `effective_to` from `supersede()`).
- Legacy data (supersedes pointer, `effective_to IS NULL`) stays hidden under
  `supersession_behavior="hide"` in `as_of` queries — back-compat preserved
  and regression-tested (DEC-10).
- Reuses existing `effective_to` / `supersedes_document_id` semantics; the only
  engine change is the bounded, back-compat-guarded DEC-10 clause.

---

## PRG-4 — Stable, always-present `chunk_id` *(low, XS)*

No signature change — `ChunkResult.chunk_id` stays `int | None` (spec
explicit). Every construction site in `retrieval.py` already passes
`chunk_id=row["id"]` (the `chunks.id` BIGSERIAL PK, stable across re-queries).

Deliverable:
- Add a docstring guarantee on `ChunkResult.chunk_id` ("always populated for
  results returned by `query()`/`ask()`; stable across re-queries for the same
  stored chunk").
- Regression test: the same chunk returned by two separate queries has an
  identical, non-null `chunk_id`.

---

## Cross-cutting

### Release (DEC-2)

- `pyproject.toml`: `0.3.0a2 → 0.3.0a3`.
- `CHANGELOG.md`: entry covering PRG-1..4 (additive, optional, back-compat).
- `README.md`: version badge bump if present.

### Testing (project rule: everything gets tests; cumulative E2E)

- **Unit** (`tests/unit/test_models.py`): new `ChunkResult` fields exist,
  default `None`, accept values; existing fields unchanged.
- **Integration** (real PG :5434, pattern from
  `tests/integration/test_evolution_tier1.py`; new file
  `tests/integration/test_consumer_surface.py`): one test per acceptance
  bullet across PRG-1/2/3, including:
  - metadata round-trip present / absent (`.metadata is None`);
  - byte-identical existing fields+scores for a no-metadata ingest vs. a
    captured pre-change baseline (PRG-1 bullet 2 back-compat proof);
  - `evolution_tier="off"` → evolution fields `None`;
  - `retract()` temporal + idempotency + naive-tz `ValueError`;
  - `supersede()` temporal + `supersession_behavior` + ambiguous-path
    `ValueError`;
  - PRG-4 stable `chunk_id` regression.
- **Cumulative E2E** (`tests/integration/test_e2e.py`): extend the existing
  schema→ingest→query path to exercise a metadata round-trip so the new
  surface is covered by the always-run cumulative test.

### Back-compat verification gate

A dedicated test asserts: ingest without metadata + `query()` → identical
existing-field values and scores vs. a baseline captured before the change.
This is the explicit proof of governing constraint 2/3.

### Files touched

`src/pg_raggraph/models.py`, `src/pg_raggraph/retrieval.py`,
`src/pg_raggraph/__init__.py`, `pyproject.toml`, `CHANGELOG.md`,
`README.md`, `tests/unit/test_models.py`,
`tests/integration/test_consumer_surface.py` (new),
`tests/integration/test_e2e.py`.

### Delivery shape

One feature branch; one commit per PRG (PRG-1, PRG-2, PRG-3, PRG-4) plus one
release commit (bump + CHANGELOG + README). Matches the repo's existing
feature-branch workflow. Tree compiles and tests pass between commits
(thin vertical slices).

## Out of scope

- **PRG-5** (supersession-chain "current view" query mode) — explicitly
  deferred per source spec.
- Any schema migration — all required columns/tables already exist in
  `sql/schema.sql` and migration `002_evolution_tracking.sql`.
- Any change to existing query scoring or smart-router behavior.
- Evolution engine internals — **with one owner-approved exception (DEC-10)**:
  the bounded, back-compat-guarded `as_of`-aware refinement of the
  `supersession_behavior="hide"` clause in `evolution_where_clauses`. No other
  evolution-engine behavior changes; existing data behavior is unchanged
  (regression-tested).

## Definition of ready for the consumer

PRG-1, PRG-2, PRG-3, PRG-4 landed and tested in `0.3.0a3`; PRG-5 explicitly
deferred; back-compat verification gate passing.
