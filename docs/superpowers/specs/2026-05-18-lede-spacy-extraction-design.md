# Design: `lede_spacy` non-LLM extraction path

- **Date:** 2026-05-18
- **Status:** Approved (brainstorming → writing-plans)
- **Owner:** consumer-surface / extraction
- **Topic slug:** lede-spacy-extraction

## Problem

`PGRGConfig.fact_extractor: Literal["llm", "lede_spacy", "none"] = "none"`
(`src/pg_raggraph/config.py:235`) is a **phantom config option**. It is:

- accepted by the pydantic `Literal` (so `fact_extractor="lede_spacy"` validates),
- documented as a working non-LLM path in `docs/Config-Reference.md:503`,
  `docs/cookbook/evolution-tracking.md:133`, and `docs/user-guide.md:429`,
- read by **zero code**. The only extraction gate in the ingest path is
  `if not self.config.skip_extraction and self.config.llm_base_url:`
  (`src/pg_raggraph/__init__.py:368` and `:596`).

Consequences:

1. Selecting `fact_extractor="lede_spacy"` with no `llm_base_url` falls
   straight into "Extraction disabled — ingesting as pure vector RAG"
   (`__init__.py:376`). It silently produces **0 entities** — no error,
   no warning. A consumer (e.g. stele's no-LLM invariant) cannot build a
   graph without an LLM even though the config says they can.
2. The `config.py:231` comment claims `lede_spacy` "dep-parses [sentences]
   into SPO triples". **No yonk-labs package ships SPO triple extraction.**
   Verified against PyPI 2026-05-18: `lede` 0.3.0, `lede-spacy` 0.3.0,
   `chunkshop` 0.4.3 all expose entity NER (PERSON/ORG/GPE) and
   `correlate_facts` (entity↔number pairs, a v0.2 "known-gated" primitive)
   — none expose subject-predicate-object relationship triples.

## Goal

Make `fact_extractor="lede_spacy"` a real, deterministic, LLM-free
extraction path that builds an actual entity+relationship graph, wired
into the existing ingest pipeline, with fail-loud behavior when its
optional dependencies are absent. Correct the documentation to match
what is actually delivered.

## Non-goals (v1)

- Populating the Tier 2 `facts` / `fact_edges` tables via
  `lede.extract.correlate_facts` / `stats`. The tables exist
  (`sql/schema.sql:179`) but stay empty; this is a separate, deeper
  follow-up. v1 delivers entities + edges through the proven
  `ExtractionResult` seam only.
- SPO / dependency-parse triple extraction. Not shipped by any upstream
  package; not in scope. The doc claims that promise it will be corrected.
- Changing the `"llm"` or `"none"` paths' behavior.

## Verified upstream API (PyPI, 2026-05-18)

- `lede` 0.3.0 — "deterministic extractive summarization, zero runtime
  deps." `from lede import summarize`;
  `summarize(text, max_length=500, mode="default", attach=["metadata"])`
  → object with `.summary` (str), `.metadata` (`Metadata(dates, amounts,
  urls, entities)`), `.stats`, `.outline`, `.phrases`,
  `.correlated_facts`. Also `from lede.extract import metadata, ...`.
  `.summary` is verbatim source sentences (never paraphrased).
- `lede-spacy` 0.3.0 — "spaCy-powered enrichment backend for lede —
  PERSON/ORG/GPE entity extraction via en_core_web_sm." Importing it
  registers the spaCy backend; `metadata(text, backend="spacy")` (or
  `summarize(..., attach=["metadata"])` with the backend importable)
  populates `Metadata.entities`.
- spaCy model `en_core_web_sm` (~50 MB) is required and is **not**
  auto-pulled by us (no silent large download inside a library).

## Design

### Component 1 — `src/pg_raggraph/lede_extraction.py` (new)

A focused module with one public function mirroring the existing
extractor seam so it drops into the pipeline with no downstream change:

```python
async def extract_from_chunks_lede(
    chunks: list[dict],
    llm,            # ignored — accepted for seam-compatibility, always None here
    db,             # unused (no LLM cache); kept for signature parity
    config: PGRGConfig,
) -> list[ExtractionResult]:
    ...
```

- Same return contract as `extraction.extract_from_chunks`
  (`list[ExtractionResult]`, one per chunk), so storage, entity
  resolution, and dedupe at `__init__.py:881+` are reused unchanged.
- Per chunk, on `chunk["embedded_content"] or chunk["content"]`:
  1. **Entities** ← lede + `lede_spacy` NER over the **full chunk text**
     (not a truncated summary — entity coverage must not depend on
     summary length). Mapped: `PERSON → person`, `ORG → organization`,
     `GPE → location` (other labels → `concept`). Run through the
     existing `extraction._is_valid_entity` / `filter_extraction`.
  2. **Relationships** ← deterministic **sentence-level co-occurrence**:
     two entities whose mentions fall in the same sentence get a
     `RELATED_TO` edge, `weight` = number of co-occurring sentences in
     the chunk, `description` = one supporting sentence verbatim.
     Explicitly typed as co-occurrence — **not** a semantic relation.
  3. Exact lede entrypoint (`lede.extract.metadata(content,
     backend="spacy")` vs `lede.summarize(content,
     attach=["metadata"]).metadata`) and the sentence-iteration source
     (lede-exposed spans vs a directly-loaded spaCy `Doc`) are
     **pinned in the implementation plan after probing the installed
     package** — the spec fixes the contract (full-text NER +
     sentence co-occurrence), not the private call path.
- CPU-bound spaCy work runs in a thread (`asyncio.to_thread`) so it does
  not block the event loop; bounded by `config.extract_concurrency`.
- Lazy imports only (mirrors `chunking._chunk_via_chunkshop`). A
  module-level `ensure_lede_available()` raises a single clear error.

### Component 2 — ingest gate wiring (`src/pg_raggraph/__init__.py`)

The two sites at `:368` and `:596` currently gate solely on
`llm_base_url`. New logic (both sites, identical):

- `fact_extractor == "lede_spacy"` → select `extract_from_chunks_lede`
  as the `extract_from_chunks_fn`; **do not require `llm_base_url`**;
  `llm` stays `None`. Call `ensure_lede_available()` here so the failure
  is at ingest start, not mid-document.
- `fact_extractor in ("llm", "none")` → unchanged from today
  (existing `skip_extraction` / `llm_base_url` logic).
- `_extract_and_store` at `:865` already treats `llm is None` specially;
  the lede path must run even when `llm is None`. The selection of the
  extractor fn (not the `llm` truthiness) becomes the branch key. The
  `llm is None or skip_llm_for_this_doc` short-circuit at `:865` is
  adjusted so a lede extractor is still invoked.

### Component 3 — fail-loud

`ensure_lede_available()` raises `RuntimeError` (caught and surfaced at
`connect()`/first ingest, not swallowed like the LLM-provider
`try/except` at `:370`) with the exact remediation:

```
fact_extractor="lede_spacy" requires the optional extra and the spaCy model:
    pip install 'pg-raggraph[lede_spacy]'
    python -m spacy download en_core_web_sm
```

Missing `lede`, missing `lede_spacy`, and missing `en_core_web_sm` are
distinguished in the message. No silent 0-entity no-op; no silent model
download.

### Component 4 — packaging (`pyproject.toml`)

New extra mirroring `[chunkshop]`:

```toml
lede_spacy = ["lede>=0.3", "lede-spacy>=0.3", "spacy>=3.7"]
```

Added to the `all` aggregate extra. `uv sync --extra lede_spacy` for
dev/test. The spaCy model is documented, not declared (not a pip dist).

### Component 5 — documentation

- Correct `config.py:231` comment (drop "SPO triples"; describe NER
  entities + co-occurrence edges).
- Correct `docs/Config-Reference.md:503`, `docs/cookbook/
  evolution-tracking.md:133`, `docs/user-guide.md:429`: `lede_spacy` =
  deterministic non-LLM **entity** graph (NER) + co-occurrence edges;
  no LLM URL needed; requires `[lede_spacy]` extra + spaCy model;
  fact-table (Tier 2) population is a noted follow-up.

## Data flow

```
ingest() → gate reads config.fact_extractor
  └─ "lede_spacy": ensure_lede_available()
        → extract_from_chunks_fn = extract_from_chunks_lede
        → llm = None (not required)
  per chunk: lede + lede_spacy NER over full chunk text
        → entities (NER, mapped+filtered)
        → RELATED_TO edges (sentence-level co-occurrence)
        → ExtractionResult
  → existing dedupe / resolution / storage (__init__.py:881+) UNCHANGED
```

## Testing (everything gets tests; test-as-user)

- **Unit** (`tests/unit/`, no DB): entity-label→type mapping;
  co-occurrence edge construction (weights, verbatim support span);
  `ensure_lede_available()` message for each missing-dep case (monkeypatch
  import failure); config-gate selection logic.
- **Integration** (`tests/integration/`, real PG on :5434): ingest a
  fixture doc with `fact_extractor="lede_spacy"` and **no** `llm_base_url`;
  assert non-empty `entities` and `relationships` rows; assert no
  "Extraction disabled" degrade path taken.
- **E2E** (`tests/test_e2e.py`): extend the cumulative path to cover the
  no-LLM `lede_spacy` ingest → query round-trip.
- Skip-marker pattern: integration/E2E lede tests skip cleanly if the
  spaCy model is absent in CI, with an xfail/skip reason — but unit
  tests for fail-loud must run regardless (they assert the error).

## Risks / open points

- spaCy `en_core_web_sm` in CI: tests must skip-or-xfail gracefully when
  the model is not installed; the fail-loud unit test asserts the error
  path without needing the model.
- Entities are taken over the **full chunk text**, so summary length
  has no effect on entity coverage. (Earlier framing that scoped
  entities to "salient sentences" was rejected in self-review — it would
  silently drop low-salience entities.) The implementation plan must
  verify the chosen lede entrypoint extracts NER over full input, not a
  truncated summary, against the installed `lede==0.3.0` package.
- Co-occurrence edges are noisier than LLM relations. This is the honest
  ceiling of no-LLM edge extraction and is documented as such, not hidden.

## Attribution

`lede` and `lede-spacy` are yonk-labs sibling packages (Apache-2.0).
Co-occurrence-edge heuristic is original to this design.
