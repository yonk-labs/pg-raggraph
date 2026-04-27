# Evolving-Knowledge RAG — Design Spec

**Status:** draft v1
**Date:** 2026-04-22
**Owner:** pg-raggraph
**Inspired by:** Jiang et al., *MAGMA: A Multi-Graph based Agentic Memory Architecture for AI Agents* (arXiv:2601.03236, ACL 2026)

## Summary

pg-raggraph today assumes static corpora. Real knowledge evolves — medical guidance gets retracted, software APIs change version, legal precedent gets overturned, internal policies supersede each other, agents accumulate memory that contradicts itself. Current RAG systems treat all content as semantically equivalent, producing stale and contradictory answers.

This spec extends pg-raggraph's core with **fact-level evolution tracking**: atomic factual claims as first-class graph nodes, typed edges between facts (supersession, contradiction, refinement, temporal ordering), retrieval that scores temporal recency and penalizes superseded content, and context assembly that surfaces "here is what is currently true, and here is what changed." All of it is flag-gated, tier-configurable, and gracefully handles partial metadata.

The architecture is inspired by MAGMA but extends beyond agent memory to **any evolving knowledge base** — which is most real-world KBs.

---

## 1. Use Cases & Value Props

### 1.1 Six concrete scenarios

Each scenario: the pain today, the new behavior, which tier delivers.

#### 1.1.1 Medical literature with retractions & guideline shifts (flagship)

**Today.** "Is hormone replacement therapy cardioprotective?" retrieves 1990s observational-study chunks with high cosine similarity. LLM synthesizes "yes" — the 2002 WHI retraction never surfaces. Clinically dangerous.

**With evolution tracking.** PubMed-ingesting pipeline sets `retracted=True, retraction_reason="WHI 2002 invalidated findings"` at ingest. Retrieval filters or flags retracted content. Under `supersession_behavior='surface_both'`, the answer LLM sees `<retracted: 2002-07-17>` tags and generates: "Earlier observational data suggested cardioprotection; the 2002 WHI trial contradicted those findings. Current guidance: HRT is not indicated for CV prevention."

**Tier:** 1 (structural, metadata-driven — no LLM needed when retraction dates come from PubMed).

#### 1.1.2 Software documentation across versions

**Today.** User ingests Python 3.10/3.11/3.12 docs. "How do I use `StrEnum`?" returns version-mixed chunks; LLM picks arbitrarily. Forum chunks for 3.8 with high lexical similarity crowd real docs out.

**With evolution tracking.** Each doc ingested with `version_label="Python 3.12"`, `supersedes_document_id` pointing at 3.11. Query filters to version (`version_filter="Python 3.12"`) or surfaces the upgrade path ("in 3.11 this was different — here's what changed").

**Tier:** 1 — version labels come from filenames, git tags, or `package.json`.

#### 1.1.3 Legal precedent tracking

**Today.** "What's the standing doctrine in environmental law?" retrieves pre-*Sackett v. EPA* (2023) commentary. Citing overturned precedent in a brief is malpractice.

**With evolution tracking.** *Sackett* ingested with `supersedes_document_id` → *Rapanos*. Facts from *Rapanos* receive `SUPERSEDES` edges from *Sackett*'s facts. Retrieval under `surface_both` surfaces current holding with a supersession trail.

**Tier:** 1 manual (legal tagging / Westlaw-style feeds) or 3 auto-inferred.

#### 1.1.4 Internal policy & compliance

**Today.** Company wiki has "refund policy" revised four times over five years. Mash-up answers. Auditors asking "what was our policy on 2023-01-01?" get garbage.

**With evolution tracking.** Each policy carries `effective_from`, `effective_to`, `supersedes_document_id`. Default query returns current policy. `rag.query(q, as_of=datetime(2023,1,1))` returns historical state. Audit trail falls out of the schema.

**Tier:** 1 — every enterprise CMS already has effective dates.

#### 1.1.5 Scientific consensus evolution

**Today.** "What's the current understanding of gut microbiome's role in depression?" averages a decade of shifting claims with no uncertainty surfaced.

**With evolution tracking.** Tier 3 `CONTRADICTS` edges surface conflicting studies. `QueryResult.contradictions` pairs them up. Answer: "Evidence is mixed — 2018 meta-analysis supports; 2022 replication failed; 2024 review concludes effect is modest and population-dependent."

**Tier:** 3 — requires LLM-inferred fact edges.

#### 1.1.6 Agent long-term memory

**Today.** Agent session memory: user said "I'm vegetarian" in session 1, "I eat fish now" in session 4. Agent retrieves both, gets confused.

**With evolution tracking.** Each memory ingested with `effective_from`. Session 4 marked `supersedes` session 1. Retrieval returns current preference by default; `as_of` gets historical. MAGMA's original target.

**Tier:** 1 (agent framework supplies supersession) or 3 (auto-infer at scale).

### 1.2 Use case × tier matrix

| | Tier 1 | Tier 2 | Tier 3 |
|---|:---:|:---:|:---:|
| Medical retractions | flagship | + richer | + auto-detect |
| Software versioning | flagship | + | + |
| Legal precedent | manual | + | auto-infer |
| Policy compliance | flagship | + | (overkill) |
| Scientific consensus | partial | partial | flagship |
| Agent memory | framework-provided | + | scale-up |

Tier 1 covers 5 of 6 use cases at zero LLM cost. Tier 3 unlocks auto-inference and the agent-memory surface at scale.

### 1.3 Value props by segment

- **Medical & pharma.** *The first RAG that won't cite retracted studies.* Retraction feeds + guideline versioning in as metadata. Answers stop being clinically dangerous.
- **Developer tools & docs platforms.** *Version-correct answers without maintaining separate indexes per release.* One index, all versions, no crosstalk.
- **Legal tech.** *Precedent tracking that knows when a case was overturned.* No hallucinated citations to dead law.
- **Enterprise compliance & GRC.** *Audit-ready RAG.* Every answer tied to the version effective at the time. `as_of` queries for compliance review.
- **Research & analyst tools.** *Knowledge evolution as a retrieval signal.* Surfaces "the consensus shifted" rather than averaging across eras.
- **Agent frameworks.** *Long-horizon memory with supersession awareness.* Agents that learn without fighting their own history.
- **Crosscutting.** *The first RAG that knows time exists.*

### 1.4 Honest caveats

- **Static corpora** get nothing from this. Tier 0 is correct for them.
- **Hard-real-time agents** can't wait for Tier 3 slow-path LLM edge inference. Tier 1/2 are real-time-safe.
- **No ground truth for scoring weights.** Tier 3 contradiction detection surfaces conflicts; it doesn't resolve them.
- **Schema migration cost.** Existing DBs get one migration file. Small but real.

---

## 2. Architecture & Data Model

### 2.1 Mental model

```
    documents ──┬── chunks ────── entities ──── relationships
                │       │            │                │
                │       └──── facts ─┘                │
                │              │                      │
                │              └── fact_edges ────────┘
                │                   (SUPERSEDES,
                │                    CONTRADICTS,
                │                    PRECEDES,
                │                    SUPPORTS,
                │                    REFINES)
                │
                └── document_versions
                      (effective_from/to,
                       supersedes_doc,
                       retracted)
```

Chunks remain the retrieval primary. **Facts** are a new node type — atomic claims extracted from chunks. Facts connect via five typed edge kinds. Each fact FK's back to its source chunk for audit/provenance. Entities stay as they are; facts point at entities for subject/object when resolvable.

Retrieval API returns `list[ChunkResult]` as today. Each `ChunkResult` carries a new `facts: list[FactRef]` sidecar. **No existing API breaks.** (Shape 2 decision.)

### 2.2 New tables

#### `facts` — atomic claims

```sql
CREATE TABLE facts (
    id                 BIGSERIAL PRIMARY KEY,
    namespace          TEXT NOT NULL,
    source_chunk_id    BIGINT REFERENCES chunks(id) ON DELETE CASCADE,
    subject            TEXT NOT NULL,
    subject_entity_id  BIGINT REFERENCES entities(id) ON DELETE SET NULL,
    predicate          TEXT NOT NULL,        -- 'causes', 'treats', 'replaces', ...
    object             TEXT NOT NULL,
    object_entity_id   BIGINT REFERENCES entities(id) ON DELETE SET NULL,
    support_span       TEXT NOT NULL,        -- verbatim quote for citation
    confidence         FLOAT DEFAULT 1.0,
    effective_from     TIMESTAMPTZ,
    effective_to       TIMESTAMPTZ,          -- null = still effective
    retracted          BOOLEAN DEFAULT FALSE,
    retracted_at       TIMESTAMPTZ,
    retraction_reason  TEXT,
    embedding          vector({dim}),        -- facts are themselves embedded
    extractor          TEXT NOT NULL,        -- 'llm' | 'skimr_spacy'
    properties         JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_facts_ns_source ON facts(namespace, source_chunk_id);
CREATE INDEX idx_facts_subject_entity ON facts(subject_entity_id);
CREATE INDEX idx_facts_object_entity ON facts(object_entity_id);
CREATE INDEX idx_facts_effective ON facts(effective_from);
CREATE INDEX idx_facts_retracted ON facts(retracted) WHERE retracted;
CREATE INDEX idx_facts_embedding ON facts USING hnsw (embedding vector_cosine_ops);
```

#### `fact_edges` — typed relations between facts

```sql
CREATE TABLE fact_edges (
    id            BIGSERIAL PRIMARY KEY,
    src_fact_id   BIGINT REFERENCES facts(id) ON DELETE CASCADE,
    dst_fact_id   BIGINT REFERENCES facts(id) ON DELETE CASCADE,
    edge_type     TEXT NOT NULL,
        -- SUPERSEDES: src replaces dst (dst is invalid going forward)
        -- CONTRADICTS: src and dst claim incompatible things (neither superseded yet)
        -- PRECEDES: src temporally before dst (weaker than SUPERSEDES)
        -- SUPPORTS: src provides evidence for dst
        -- REFINES: src is a more specific version of dst
    confidence    FLOAT DEFAULT 1.0,
    inferred_by   TEXT NOT NULL,
        -- 'explicit' | 'llm' | 'temporal' | 'heuristic' | 'document_hint'
    created_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (src_fact_id, dst_fact_id, edge_type)
);

CREATE INDEX idx_fact_edges_src ON fact_edges(src_fact_id, edge_type);
CREATE INDEX idx_fact_edges_dst ON fact_edges(dst_fact_id, edge_type);
```

#### `document_versions` — explicit version tracking

```sql
CREATE TABLE document_versions (
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

CREATE INDEX idx_docver_document ON document_versions(document_id);
CREATE INDEX idx_docver_supersedes ON document_versions(supersedes_document_id);
```

### 2.3 Additive changes to existing tables

`documents` gets lightweight evolution metadata for the common case (the new `document_versions` table is authoritative when a document has multiple versions):

```sql
ALTER TABLE documents
    ADD COLUMN effective_from TIMESTAMPTZ,
    ADD COLUMN effective_to   TIMESTAMPTZ,
    ADD COLUMN retracted      BOOLEAN DEFAULT FALSE,
    ADD COLUMN version_label  TEXT;
```

`entities` stays unchanged in v1.

### 2.4 Why separate tables from `relationships`?

Relationships are entity↔entity. Facts are claims with provenance, temporal validity, retraction state, and their own lifecycle. Reusing `relationships` would force an `is_fact` discriminator + nullable entity FKs + a fact-specific `rel_type` namespace — the tells of a premature abstraction. Separate tables keep both models clean.

### 2.5 Why embed facts?

Two reasons. (1) Fact-level semantic dedup — three chunks say "statins prevent cardiovascular events" in different words; collapse via embedding, not string match. (2) Future escape hatch — if we later elevate facts to first-class retrieval units, they're already embedded and queryable.

---

## 3. Ingestion Pipeline & Extractor Protocol

### 3.1 Extractor protocol

Same pattern as `EmbeddingProvider` / `LLMProvider` — a `Protocol` with multiple implementations, selected via config.

```python
# src/pg_raggraph/fact_extraction.py

class FactExtractor(Protocol):
    async def extract(
        self,
        chunk_text: str,
        chunk_metadata: dict,
    ) -> list[ExtractedFact]: ...

    @property
    def name(self) -> str: ...     # stored in facts.extractor for audit


class ExtractedFact(BaseModel):
    subject: str
    predicate: str
    object: str
    support_span: str              # verbatim quote from chunk
    confidence: float = 1.0
    subject_entity_hint: str | None = None
    object_entity_hint: str | None = None
```

Two shipped implementations:

- **`LlmFactExtractor`** — structured-output prompt (`response_format={"type": "json_object"}`). Default for Tier 3. Combined with existing entity/relationship extraction in one LLM call to avoid doubling cost.
- **`SkimrSpacyExtractor`** — skimr picks top-K salient sentences, spaCy parses each into SPO triples via dependency parsing. No LLM. Degrades gracefully on domain-specific text; free and deterministic. Used in Tier 2.

### 3.2 Tier model

Four operational tiers; each an incremental step up in cost and capability.

| Tier | Ingest cost | Query cost | What it gives you |
|---|---|---|---|
| **0. Off** (default) | $0 | $0 | Current pg-raggraph — no evolution anything |
| **1. Structural** | $0 | $0 | Caller-supplied `effective_from`, `version_label`, `retracted`, `supersedes_document_id`. All scoring SQL-side. No fact extraction. |
| **2. Fact-aware (no LLM)** | CPU only | $0 | Adds skimr+spaCy fact extraction + fact dedup + diversity backfill. |
| **3. Full** | LLM ingest + async slow path | SQL | Everything — LLM fact extraction, LLM-inferred fact edges, contradiction detection. |

Config:

```python
class PGRGConfig:
    evolution_tier: Literal['off', 'structural', 'fact_aware', 'full'] = 'off'
```

### 3.3 Two-phase ingest

#### Phase 1: Fast path, in-transaction

```
1.  Compute content_hash + dedup check (existing)
2.  Resolve version metadata
      if caller supplied effective_from / version_label / supersedes_document_id:
          use as-is (speed path)
      else if tier ∈ {fact_aware, full}:
          one LLM call on doc preamble → extract date / version / supersedes hints
      else:
          skip (effective_from defaults to now())
3.  Chunk document (existing; fixed hierarchy chunker)
4.  Embed chunks (existing)
5.  Per chunk, in parallel (semaphore-bounded):
      a. entity + relationship extraction (existing)
      b. fact extraction (new; combined with (a) when extractor='llm')
6.  Batch embed facts (no-op if tier < fact_aware)
7.  Entity resolution (existing pg_trgm + vector)
8.  Write in single transaction:
      documents    (+ evolution columns)
      document_versions (iff version_label or supersedes present)
      chunks       (existing)
      entities     (existing)
      relationships (existing)
      facts        (new)
      entity_chunks, relationship_chunks (existing)
```

#### Phase 2: Slow async path, post-commit (Tier 3 only)

Runs after commit. Never blocks the caller. Cheap to skip or retry.

```
For each newly-inserted fact F:
    candidates ← top-fact_edge_candidate_k facts by vector similarity
                 (same namespace, excluding facts from same chunk)
    LLM-judge (F, candidate) pairs in batch:
        edge_type ∈ {SUPERSEDES, CONTRADICTS, REFINES, SUPPORTS, PRECEDES, NONE}
        confidence ∈ [0, 1]
    insert fact_edges rows where edge_type ≠ NONE

If doc has supersedes_document_id set:
    For each fact F in new doc:
        find facts F' in superseded doc with matching (subject_entity_id, predicate)
        add (F, F', SUPERSEDES, inferred_by='document_hint')
```

Budget: `fact_edge_candidate_k=8` → ~20K LLM-judge calls for a 2500-fact corpus. Single-digit dollars on nano.

### 3.4 Caller-hint contract (speed path)

Callers that already know versioning skip auto-inference:

```python
await rag.ingest(
    files=["python-3.12-docs/*.md"],
    namespace="python_docs",
    metadata={
        "effective_from": datetime(2024, 10, 1),
        "version_label": "Python 3.12",
        "supersedes_document_id": "python-3.11-doc-id",
    },
)

await rag.ingest(
    files=["hrt-cardioprotection-2001.pdf"],
    namespace="cardiology",
    metadata={
        "effective_from": datetime(2001, 6, 1),
        "retracted": True,
        "retracted_at": datetime(2002, 7, 17),
        "retraction_reason": "WHI trial invalidated findings",
    },
)
```

When a hint is provided, the corresponding inference step is skipped. Zero extra LLM cost for callers with structured metadata.

### 3.5 Cost story

- **Tier 1:** $0. All metadata caller-provided.
- **Tier 2:** CPU only. skimr+spaCy per chunk on CPU. No LLM.
- **Tier 3:** combined entity+fact extraction prompt (~20% token increase over today's entity extraction) + async slow-path edge inference. Medical corpus (~537 chunks under fixed chunker): ~$2 combined extraction + ~$3-5 slow path ≈ **~$5-7 per fresh ingest**. Same order of magnitude as today.

---

## 4. Retrieval, Scoring & Context Assembly

### 4.1 Scoring formula

When `evolution_tier ≠ 'off'`, existing retrieval SQL gains two new score components. Composes onto NAIVE / LOCAL / GLOBAL — no mode-specific branching.

```
temporal_boost    = exp(-ln(2) * age_years(c.effective_from) / half_life_years)
supersession_pen  = 1 - (count_superseded_facts / total_facts_in_chunk) * λ_sup
retraction_filter = 0 if c.retracted else 1
```

Final:

```sql
score = retraction_filter * (
    w_sem    * (1 - (c.embedding <=> query_embedding)) +
    w_bm25   * ts_rank(c.search_vector, tsquery) +
    w_graph  * graph_boost_score +
    w_recent * temporal_boost +
    w_supersession  * supersession_pen
)
```

Effective dates resolve via `COALESCE(c.effective_from, d.effective_from, c.created_at, now())`. All new terms are NULL-safe — missing metadata collapses the expression back to today's three-leg hybrid score.

### 4.2 Default weights (conservative, empirically tunable)

| Weight | Default | Notes |
|---|---|---|
| `w_sem` | 0.50 | baseline semantic |
| `w_bm25` | 0.20 | FTS |
| `w_graph` | 0.20 | graph boost (when applicable) |
| `w_recent` | 0.10 | temporal decay |
| `w_supersession` | 0.10 | supersession penalty |
| `temporal_half_life_years` | 5.0 | chunks halve in weight every 5 years |
| `λ_sup` | 0.5 | how heavily to penalize superseded content |

**These are defaults, not truths.** Weights are corpus-dependent hyperparameters. Ship with a `rag.tune_scoring_weights()` utility that grid-searches weights against a gold QA set using the existing bake-off runner infrastructure. For medical, expect `w_recent` to land much higher than 0.10 once tuned.

### 4.3 Retraction modes

Config: `retracted_behavior`:

- **`hide`** — retracted chunks filtered entirely (`WHERE NOT c.retracted`).
- **`flag`** (default) — retracted chunks rank normally but carry a `retracted=True` flag; answer LLM sees `<retracted: DATE>` tag.
- **`surface_both`** — retracted + superseding chunks returned together; LLM synthesizes "once claimed, later retracted."

### 4.4 Supersession modes

Config: `supersession_behavior`:

- **`hide`** — superseded chunks filtered.
- **`prefer_new`** — superseded down-weighted via `supersession_pen`.
- **`surface_both`** (default) — return both current and superseded; LLM gets "here's what was true, here's what changed."

### 4.5 Fact sidecar query

After retrieval returns chunks, one additional query populates the sidecar:

```sql
SELECT id, source_chunk_id, subject, predicate, object, support_span,
       effective_from, effective_to, retracted,
       (SELECT array_agg(edge_type || ':' || dst_fact_id)
          FROM fact_edges WHERE src_fact_id = facts.id) AS outgoing_edges
FROM facts
WHERE source_chunk_id = ANY(%(chunk_ids)s)
  AND namespace = %(namespace)s
```

One query per retrieval. No N+1.

### 4.6 Context assembly — four passes

Runs after retrieval, before the answer LLM sees anything, when `evolution_tier ≠ 'off'`.

**Pass 1: Fact-level dedup.** Two chunks whose fact sets overlap ≥ `dedup_threshold` (default 0.8) — drop the lower-ranked. Fact identity by `(subject_entity_id, predicate, object_entity_id)` when resolvable, else cosine ≥ 0.92 on fact embeddings. Frees result slots for downstream operations.

**Pass 2: Supersession reordering.** For each chunk C, if any of C's facts have incoming `SUPERSEDES` edges from a fact in chunk D (also in result set), promote D above C regardless of original scores. Then apply `supersession_behavior` policy (hide C / keep both / keep only D).

**Pass 3: Diversity-aware backfill** (the "latest misses older" fix). Walk the entity set of top-3 chunks. For each entity, query: are there older chunks (not in result set) with facts about this entity whose `(predicate, object)` doesn't appear in any top-3 chunk's fact set? If yes and not superseded, inject at position K+1 with `backfill=True`.

**Pass 4: Contradiction flagging.** Scan final chunk set for `CONTRADICTS` fact-edges between chunks in the result. Attach `QueryResult.contradictions: list[dict]`:

```python
[
    {
        "fact_a": {"chunk_id": 442, "claim": "statins cause cognitive decline", "effective_from": "..."},
        "fact_b": {"chunk_id": 881, "claim": "statins do not affect cognition", "effective_from": "..."},
        "resolution": None,
    }
]
```

Answer LLM sees both chunks and the contradiction list.

### 4.7 Context formatting for the answer LLM

MAGMA-style provenance tags when evolution tracking is on:

```
[effective: 2024-06-22] [ref: chunk-8812] [version: Python 3.12]
useEffect with no dependency array runs after every render...

[effective: 2022-03-01] [ref: chunk-3301] [version: Python 3.10] [superseded]
useEffect's cleanup function used to run...

[retracted: 2002-07-17] [ref: chunk-91]
HRT was shown to be cardioprotective...
```

Answer prompt instructs the LLM to respect retraction/supersession markers.

### 4.8 Graceful partial-metadata handling

Every new signal is optional at the row level:

- `effective_from IS NULL` → `created_at` fallback; temporal boost neutral (1.0)
- `version_label IS NULL` → version queries ignore this doc
- `retracted` absent → treated false
- Chunk has zero facts → dedup/backfill skip it silently; ranks on semantic/BM25/graph signal only
- Fact missing `subject_entity_id` → dedup falls back to embedding cosine
- No outgoing `fact_edges` → no supersession/contradiction semantics for this fact

You can mix Tier 0 and Tier 3 content freely in the same namespace. Retrieval works; evolution logic only activates where the data exists.

### 4.9 Per-query override

```python
rag.query(q, evolution_aware=False)   # force classic behavior even on tracked data
rag.query(q, as_of=datetime(2023, 1, 1))  # time-travel query
rag.query(q, version_filter="Python 3.12")  # version-scoped
```

---

## 5. Configuration Surface (Consolidated)

```python
class PGRGConfig:
    # --- Master tier ---
    # Zero cost when 'off'; ramp tier for more features.
    evolution_tier: Literal['off', 'structural', 'fact_aware', 'full'] = 'off'

    # --- Scoring weights (only active when evolution_tier != 'off') ---
    # Defaults are conservative; run rag.tune_scoring_weights() per corpus.
    w_sem:   float = 0.50
    w_bm25:  float = 0.20
    w_graph: float = 0.20
    w_recent: float = 0.10
    w_supersession:  float = 0.10
    temporal_half_life_years: float = 5.0
    lambda_supersession: float = 0.5

    # --- Retrieval behavior ---
    retracted_behavior:    Literal['hide','flag','surface_both'] = 'flag'
    supersession_behavior: Literal['hide','prefer_new','surface_both'] = 'surface_both'
    contradiction_detection: bool = True

    # --- Context assembly ---
    fact_dedup_threshold: float = 0.8
    diversity_backfill:   bool  = True

    # --- Fact extraction ---
    fact_extractor: Literal['llm', 'skimr_spacy', 'none'] = 'none'
    fact_similarity_threshold: float = 0.92
    fact_edge_inference: bool = True
    fact_edge_candidate_k: int = 8
```

Per-ingest and per-query overrides supported via kwargs.

---

## 6. Testing Strategy

### 6.1 Unit tests (no DB)

- Fact extractor implementations (mocked LLM response) produce correctly-shaped `ExtractedFact`.
- Context assembly passes (dedup, reordering, backfill, contradiction flag) on synthetic fact sets.
- Scoring SQL produces expected values for synthetic chunk rows (tested via pure-Python reimplementation of the score expression).
- NULL-safe scoring: partial metadata collapses correctly.

### 6.2 Integration tests (DB required)

- Migration applies cleanly on a DB with existing evolution-free data.
- Ingest under each tier produces expected table row counts.
- Query under each `retracted_behavior` / `supersession_behavior` returns correct result sets.
- `as_of` query returns historical state.
- Mixed-tier data in one namespace retrieves correctly.
- `rag.tune_scoring_weights()` grid search produces valid config on a tiny gold set.

### 6.3 Evaluation fixtures

Three synthetic "evolving" corpora for regression testing:
- **Medical retraction:** 5 docs, 2 of which supersede earlier ones, 1 retracted.
- **Software versioning:** Python 3.10/3.11/3.12 mock docs with version_label supersession.
- **Policy effective-dates:** 4 versions of a refund policy with overlapping effective date ranges.

Gold QA sets for each; used by `tune_scoring_weights()`.

### 6.4 Benchmarks

Add an evolution-aware benchmark to `benchmarks/age-bakeoff/`:
- LoCoMo-style conversation memory corpus (if available).
- Medical retraction corpus (PubMed retraction-watch + original papers).
- Goal: demonstrate pg-raggraph with evolution tracking beats pg-raggraph without on these corpora.

---

## 7. Phased Implementation Plan

Total: **10-12 weeks** to full Tier 3. Tier 1 alone is shippable in ~4 weeks.

### Phase 1 — Tier 1 (Structural) — 3-4 weeks

Ship the schema, metadata contract, and SQL-side scoring. No fact extraction, no LLM.

**Week 1: Schema & migration**
- Create `facts`, `fact_edges`, `document_versions` tables (empty for Tier 1).
- ALTER `documents` for evolution columns.
- Migration file `002_evolution_tracking.sql`.
- Update `schema.sql` for fresh installs.
- Unit + integration tests for migration idempotency.

**Week 2: Config + caller-hint contract**
- `PGRGConfig` additions (evolution_tier, all scoring weights, behavior modes).
- `rag.ingest(metadata={...})` contract — plumb `effective_from`, `version_label`, `retracted`, `supersedes_document_id` to document columns.
- Per-ingest override support.

**Week 3: SQL scoring**
- Update NAIVE / LOCAL / GLOBAL query templates with NULL-safe evolution scoring.
- Retraction filter (hide/flag).
- Basic supersession scoring via document-level `supersedes_document_id` chain walk.
- `as_of` and `version_filter` query kwargs.
- `rag.tune_scoring_weights()` utility (wraps existing bake-off runner).

**Week 4: Tests, docs, alpha release**
- Evaluation fixtures (synthetic corpora).
- Integration tests for mixed Tier 0 / Tier 1 namespaces.
- User-facing docs: "Evolution tracking quickstart", migration guide, cookbook.
- Release as `pg-raggraph 0.3.0-alpha`.

**Deliverable:** medical retraction + software versioning + policy compliance use cases all working at zero LLM cost.

### Phase 2 — Tier 2 (Fact-aware, no LLM) — 2-3 weeks

Add fact extraction + fact-level retrieval enrichment.

**Week 5-6: Extractor protocol + skimr implementation**
- `FactExtractor` Protocol + `ExtractedFact` DTO.
- `SkimrSpacyExtractor` — skimr top-K salient sentence selection, spaCy dep-parse for SPO.
- Fact embedding batch pipeline.
- Fact insertion into `facts` table during ingest.
- Fact sidecar SQL query (one query, array-aggregated).

**Week 7: Context assembly passes**
- Pass 1 (dedup) + Pass 3 (diversity backfill) implementations.
- `ChunkResult.facts` field population.
- Integration tests on the medical retraction fixture.

**Deliverable:** fact dedup + diversity backfill improvements to retrieval quality for evolution-aware corpora.

### Phase 3 — Tier 3 (Full, LLM-augmented) — 4-5 weeks

Add LLM fact extractor, fact edge inference, contradiction detection.

**Week 8-9: LLM extractor + combined prompt**
- `LlmFactExtractor` with structured output.
- Combine entity/relationship/fact extraction into one LLM prompt (save one round trip per chunk).
- Version-metadata auto-inference from doc preamble.

**Week 10: Slow-path edge inference**
- Async worker queue for post-commit fact edge inference.
- Vector-constrained candidate selection (top-K nearest facts per new fact).
- LLM batch classifier: produces `fact_edges` rows.
- Budget accounting + cost tracker integration.

**Week 11: Supersession + contradiction passes**
- Pass 2 (supersession reordering) in context assembly.
- Pass 4 (contradiction flagging) + `QueryResult.contradictions`.
- Integration of all three `supersession_behavior` modes.

**Week 12: Benchmarks, hardening, beta release**
- Evolution-aware benchmark corpus ingestion + evaluation.
- Full tier-matrix integration testing.
- Docs update for Tier 3.
- Release as `pg-raggraph 0.3.0-beta`.

**Deliverable:** scientific consensus + agent memory use cases + auto-inferred supersession on all corpora.

### Work breakdown (task tags)

Each phase produces tasks in the existing TaskCreate system, tagged:
- `evolve:schema` — migration + DDL
- `evolve:config` — PGRGConfig + kwargs plumbing
- `evolve:scoring` — SQL + tune utility
- `evolve:extract` — fact extractors
- `evolve:assembly` — context assembly passes
- `evolve:edges` — slow-path inference
- `evolve:test` — unit + integration
- `evolve:docs` — user-facing docs + cookbook

### Ship cadence

- **Phase 1 → alpha (0.3.0-alpha).** 4 weeks in. Usable by medical/software/policy users who have structured metadata.
- **Phase 2 → alpha.1.** 7 weeks in. Incremental improvement; no API change.
- **Phase 3 → beta (0.3.0-beta).** 12 weeks in. Full feature set.
- **Stable (0.3.0).** 2-4 weeks of hardening after beta based on early-adopter feedback.

Alpha users can ship production workloads at Tier 1 / 2 immediately. Tier 3 is beta-gated until contradiction detection and fact edge inference have enough real-world exercise.

---

## 8. Open Questions & Decisions Deferred

1. **Fact-level retrieval mode (Shape 1) as v2.** If fact sidecar proves useful but callers want facts as primary result units, add `query(..., return_format="facts")` as a v2 feature. Deferred.
2. **Entity-version identity.** "React 18's useEffect" vs "React 19's useEffect" as distinct entity versions. Current design uses document-level versioning and lets entities stay singular. If fact-level disambiguation proves necessary, add `entity_versions` in v2. Deferred.
3. **Retraction-watch API integration.** Auto-pull medical retractions from retractionwatch.com and apply to existing ingested docs. Valuable but scope-creep for v1. Separate feature.
4. **Causal edge inference correctness.** MAGMA's paper uses a confidence threshold δ for causal inference; exact value is corpus-dependent. Ship with δ=0.75 default, tune per corpus in Tier 3.
5. **Skimr choice.** Basic skimr vs skimr-neural. Basic (extractive) is the default — deterministic, no hallucination. skimr-neural (abstractive) deferred as an opt-in.
6. **Compatibility with chunkshop.** chunkshop is sibling ingestion tooling. If chunkshop produces chunks, evolution metadata must flow through. Plan: chunkshop's YAML config gets `evolution_metadata:` block that maps to pg-raggraph's `metadata={...}` contract.

---

## 9. Success Criteria (What "Done" Looks Like)

Phase 1 (Tier 1) is done when:
- Medical retraction corpus ingested with retractions; retrieval hides retracted content under `retracted_behavior='hide'`, flags under `'flag'`.
- Software versioning corpus ingested; `version_filter="Python 3.12"` returns only 3.12 chunks.
- Policy corpus ingested; `as_of=datetime(2023,1,1)` returns the policy version effective at that date.
- `rag.tune_scoring_weights()` grid-searches and writes improved weights for a gold QA set.
- Mixed Tier 0 / Tier 1 namespace retrieves correctly (no errors, sensible scores).
- Integration test suite green.
- Docs shipped.

Phase 2 (Tier 2) is done when:
- skimr+spaCy extractor produces valid facts on the medical corpus.
- Fact dedup reduces result-set redundancy on the synthetic medical fixture.
- Diversity backfill surfaces older-fact-unique chunks on the "latest misses older" synthetic test.

Phase 3 (Tier 3) is done when:
- LLM extractor produces valid combined-prompt output on the medical corpus.
- Slow-path inference produces non-trivial `fact_edges` on the medical corpus within budget.
- Supersession reordering demonstrates on a supersession fixture.
- Contradiction detection surfaces the planted contradictions in a synthetic contradiction fixture.
- Benchmark numbers show measurable retrieval improvement over Tier 0 on at least one evolution-aware corpus.

---

## 10. Non-Goals (Explicitly)

- **Causal reasoning beyond retrieval.** We surface causal fact edges; we don't do causal inference on them (no do-calculus, no counterfactuals).
- **Truth-maintenance system.** We mark facts retracted/superseded when told or inferred; we don't adjudicate conflicts automatically.
- **Multi-modal facts.** Facts are text-grounded. Image/audio/video facts deferred.
- **Real-time consistency.** Tier 3 slow-path is eventually consistent; ingest-to-edges latency is seconds-to-minutes.
- **User-facing query DSL.** `as_of` and `version_filter` are kwargs, not a query language.

---

## Appendix A — Relationship to MAGMA

MAGMA (arXiv:2601.03236) proposes four graph views (semantic, temporal, causal, entity) for agent long-term memory, with policy-guided traversal at retrieval time. This spec adopts MAGMA's core insight (evolving knowledge needs temporal/causal/entity separation) and extends it:

- **Broader target:** all evolving KBs, not just agent session memory.
- **Explicit retraction & supersession:** MAGMA's causal edges imply temporal precedence; this spec adds explicit `SUPERSEDES` and `CONTRADICTS` semantics beyond temporal ordering.
- **Tier model:** MAGMA assumes LLM throughout; this spec offers a no-LLM tier (Tier 1) for metadata-rich use cases.
- **Graceful partial metadata:** this spec handles Tier-mixed namespaces and NULL-able evolution signals; MAGMA assumes all nodes have full metadata.
- **Fact-as-sidecar (Shape 2):** this spec preserves existing chunk-level API for zero-breaking adoption; MAGMA designs around facts-first retrieval.

## Appendix B — Relationship to existing pg-raggraph design decisions

- **Chunking:** hierarchy chunker with cap (fixed in 2026-04-22 session) is orthogonal to this spec. Works as-is.
- **Dual content** (`content` / `embedded_content`): orthogonal. Evolution tracking adds rows in new tables; chunks retain today's dual-content semantics.
- **Smart mode:** today's confidence-based routing stays. Evolution-aware scoring composes onto all retrieval modes including smart.
- **Entity resolution:** unchanged. Facts reference resolved entities when possible via `subject_entity_id` / `object_entity_id`.
