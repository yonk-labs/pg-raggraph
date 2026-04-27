# pg-raggraph use cases

pg-raggraph supports two distinct retrieval workloads. Pick the one whose
corpus shape matches yours; both are first-class.

## Use case 1 — Classic GraphRAG

**When:** technical docs, code Q&A, multi-hop entity reasoning over a
corpus where "current truth" is the only truth and documents don't
contradict each other across time.

**Examples:**
- "Who owns the auth service?" over a developer wiki
- "What caused the outage?" over incident reports
- "How does X depend on Y?" over architecture docs

**Recommended config:**

```python
from pg_raggraph import GraphRAG

rag = GraphRAG(dsn=DSN, namespace="dev_kb")
result = await rag.query("Who owns the auth service?", mode="naive_boost")
```

**Validated on:**

- `pg-agents` real dev codebase (909 docs) — `naive_boost` lifts top
  score by **+18.9%** vs plain `naive` at essentially the same latency
  (107 ms vs 109 ms p50). See `benchmarks/pg-agents-results.md`.
- SCOTUS, NTSB, SEC 10-Q, PostgreSQL docs in the AGE bake-off — pgrg
  matched or beat AGE on accuracy, **42–111× faster** on retrieval.
  See `benchmarks/age-bakeoff/results/REPORT-VERDICT.md`.

## Use case 2 — Evolving knowledge

**When:** corpora where the right answer depends on **time**, **version**,
or **retraction status**. Documents accumulate, supersede each other, and
sometimes get withdrawn.

**Examples:**

- "Is HRT cardioprotective?" — the answer changed in 2002 (WHI).
- "How does StrEnum work in Python 3.12?" — version-scoped.
- "What was the refund window in 2023?" — time-travel.

**Recommended config:**

```python
from datetime import datetime, timezone
from pg_raggraph import GraphRAG

rag = GraphRAG(dsn=DSN, namespace="medical", evolution_tier="structural")

# Hide retracted docs (set retracted_behavior in config):
rag.config.retracted_behavior = "hide"
result = await rag.query("Is HRT cardioprotective?")

# Time-travel:
result_old = await rag.query(
    "Is HRT cardioprotective?",
    as_of=datetime(2001, 12, 31, tzinfo=timezone.utc),
)

# Version filter:
result_312 = await rag.query(
    "How does StrEnum work?",
    version_filter="Python 3.12",
)
```

**Validated on:**

- `benchmarks/python-versioned-docs/` — 12 docs (Python 3.10/3.11/3.12),
  15 gold Qs. `version_filter` purity: **13/13 (100%)**. Overall:
  **14/15 (93%)** with one honest counter-example (PEP 695 `type`
  keyword drifted to 3.10/3.11 on an unfiltered query because older
  `TypeAlias` terminology has stronger surface overlap). See
  `benchmarks/python-versioned-docs/results.md`.
- `benchmarks/medical-hrt/` — 48 PubMed HRT/CV abstracts (1998–2025),
  7 epistemically-retracted, 15 gold Qs. `retracted_behavior="hide"`:
  **5/5** with zero retracted in top-5. `as_of="2001-12-31"`: **5/5**
  surface pre-WHI consensus. **15/15 perfect.** See
  `benchmarks/medical-hrt/results.md`.

## Decision matrix — which use case fits your corpus?

| Corpus shape | Use case | Why |
|---|---|---|
| Static technical docs | Classic | No time/version axis; graph boost helps cross-doc reasoning |
| Code Q&A on a single repo | Classic | Same — `naive_boost` wins per pg-agents |
| Codebase across versioned releases | Evolving | `version_label` per release; `version_filter` at query |
| Medical/legal literature with retractions | Evolving | `retracted` + `retracted_at` per doc |
| Policy / contract archive | Evolving | `effective_from` / `effective_to`; `as_of` queries |
| Multi-tenant SaaS with point-in-time audit | Evolving | `as_of` with tenant namespace |
| News archive | Evolving | `effective_from`; freshness scoring |
| Wikipedia-style facts | Classic | Current truth dominates; no per-version queries |

## How to choose at a glance

Ask yourself:

1. **Does my corpus have retracted, superseded, or version-specific
   documents?** Yes → evolving. No → classic.
2. **Will users ask "what was true at time T?"** Yes → evolving (`as_of`).
3. **Are there parallel versions whose answers differ?** Yes → evolving
   (`version_filter`).
4. **None of the above?** Use classic. It's faster and cheaper at ingest
   (no Tier 2/3 fact extraction needed).

## See also

- `docs/EVOLUTION-API-QUICKREF.md` — common API gotchas (read before writing
  Tier 1 code: which kwargs are per-query vs config-only, how to read
  evolution columns, `as_of` + `retracted_at` semantics)
- `docs/cookbook/evolution-tracking.md` — Tier 1 quickstart
- `docs/blog/01-intro-classic-vs-evolving.md` — narrative version of this page
- `docs/blog/02-path-a-versioned-python-docs.md` — versioned-docs walkthrough
- `docs/blog/03-path-b-medical-retractions.md` — medical-retractions walkthrough
- `docs/user-guide.md` — full API reference
