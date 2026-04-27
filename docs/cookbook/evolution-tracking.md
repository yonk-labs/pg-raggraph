# Evolution Tracking (Tier 1) — Quickstart

pg-raggraph `0.3.0-alpha` introduces evolution tracking: retrieval that
respects when documents were effective, which ones were retracted, and which
ones supersede earlier versions. This page walks through enabling Tier 1
(Structural — metadata-driven, no LLM cost).

All examples assume:

```python
from datetime import datetime, timezone
from pg_raggraph import GraphRAG
```

## 1. Turn it on

Tier 1 is opt-in. Pass `evolution_tier="structural"` directly to `GraphRAG`
(it forwards to `PGRGConfig` under the hood), or set
`PGRG_EVOLUTION_TIER=structural` in your environment:

```python
rag = GraphRAG(
    dsn=DSN,
    namespace="medical",
    evolution_tier="structural",
)
```

## 2. Supply evolution metadata at ingest

Pass a `metadata` dict to `rag.ingest()`. Every file in the call picks up
the same metadata. Use timezone-aware datetimes — `timestamptz` columns
behave most predictably with explicit tzinfo:

```python
await rag.ingest(
    ["papers/hrt_1992.md"],
    namespace="medical",
    metadata={
        "effective_from": datetime(1992, 6, 1, tzinfo=timezone.utc),
        "retracted": True,
        "retracted_at": datetime(2002, 7, 17, tzinfo=timezone.utc),
        "retraction_reason": "WHI 2002 RCT invalidated findings",
    },
)
```

Supported keys: `effective_from`, `effective_to`, `retracted`,
`retracted_at`, `retraction_reason`, `version_label`,
`supersedes_document_id`.

## 3. Query

Retrieval automatically respects your tier config:

```python
result = await rag.query(
    "Is HRT cardioprotective?",
    namespace="medical",
)
# retracted docs filtered; current guidance surfaces
```

### Time-travel query

`as_of` requires a timezone-aware datetime — naive datetimes raise
`ValueError`:

```python
result = await rag.query(
    "What was the refund policy?",
    namespace="policy",
    as_of=datetime(2023, 6, 1, tzinfo=timezone.utc),
)
```

### Version-scoped query

```python
result = await rag.query(
    "How do I use StrEnum?",
    namespace="python_docs",
    version_filter="Python 3.12",
)
```

### Force classic retrieval

```python
# Ignore evolution semantics for this one call
result = await rag.query(q, namespace=ns, evolution_aware=False)
```

## 4. Tune scoring weights per corpus

Default weights are calibrated on SCOTUS. Your corpus may want different
recency / supersession weights. Grid-search against a gold QA set:

```python
report = await rag.tune_scoring_weights(
    namespace="medical",
    gold=[
        {"question": "Is HRT cardioprotective?",
         "expected_substring": "does not prevent"},
        # ...
    ],
    grid={
        "w_sem":           [0.3, 0.5, 0.7],
        "w_recent":        [0.0, 0.1, 0.3, 0.5],
        "w_supersession":  [0.0, 0.1, 0.3],
    },
    mode="naive",
    write_back=True,  # updates rag.config
)
print(report["best"])
```

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
