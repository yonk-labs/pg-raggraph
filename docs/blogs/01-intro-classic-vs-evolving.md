---
title: "Two GraphRAG workloads, one Postgres database"
slug: "01-intro-classic-vs-evolving"
date: 2026-04-27
audience: external
series: "Tier 1 evolving knowledge"
part: 1
---

# Two GraphRAG workloads, one Postgres database

Most GraphRAG demos answer one kind of question: given a static corpus of
docs, find the right chunk. That's the **classic** workload. Static
wikis, code Q&A, internal documentation. The corpus is a snapshot, the
"current truth" is the only truth, and a vector index plus some graph
boost gets you the rest of the way.

Plenty of corpora aren't static, though. Medical literature gets
retracted. APIs evolve across versions. Policies change effective dates.
For these, the right answer depends on *when* you ask, *which version*
the user runs, or whether the source has been superseded. That's the
**evolving knowledge** workload.

pg-raggraph supports both. Same library. Same Postgres database. Same
indexes. Two query patterns.

## A 60-second tour

**Classic.** Ingest your docs, query, get chunks back. The `naive_boost`
mode re-ranks the top-K from vector + BM25 using 1-hop entity
connectivity from the graph table:

```python
from pg_raggraph import GraphRAG

rag = GraphRAG(dsn=DSN, namespace="dev_kb")
result = await rag.query("Who owns the auth service?", mode="naive_boost")
```

On a real 909-doc dev codebase (`pg-agents`), `naive_boost` lifts top
score by **+18.9%** versus plain `naive` at essentially the same latency
(107 ms vs 109 ms p50). That's the standard pgrg pitch:
[`benchmarks/pg-agents-results.md`](../../benchmarks/pg-agents-results.md).

**Evolving.** Add `evolution_tier="structural"` and ingest with metadata,
then use the time/version/retraction filters at query time:

```python
from datetime import datetime, timezone
from pg_raggraph import GraphRAG

rag = GraphRAG(
    dsn=DSN, namespace="medical", evolution_tier="structural"
)

# Hide retracted papers — return modern guidance only:
rag.config.retracted_behavior = "hide"
result = await rag.query("Is HRT cardioprotective?")

# Time-travel — what was the consensus on Dec 31, 2001?
result_old = await rag.query(
    "Is HRT cardioprotective?",
    as_of=datetime(2001, 12, 31, tzinfo=timezone.utc),
)
```

Two queries, same library, same database, two different correct answers.
We measure both in posts #2 and #3.

## Why this lives in one library

The thesis is unchanged: pgvector + adjacency tables + recursive CTEs +
PostgreSQL full-text search = a complete GraphRAG stack on a single
ACID-compliant database. No graph database extension. No vector DB
sidecar. No separate fact store.

The evolving-knowledge layer adds four columns to `documents` —
`effective_from`, `effective_to`, `retracted`, `version_label` — plus a
companion `document_versions` table for `retracted_at` and supersession
metadata. At query time, two filter sets get added to the SQL:
retraction filter (when `retracted_behavior="hide"`) and effective-date
filter (when `as_of` is supplied). Same indexes. Same provenance trail.
Same observability story. The cost of the evolving feature is two
pretty-cheap predicates and the metadata you already have to ingest.

## What you can skip

A lot of the GraphRAG literature talks about Tier 2/3 fact extraction,
LLM-inferred supersession, contradiction graphs. That work matters when
your corpus has narrative claims and you need to model relationships
*between* claims. For most corpora — versioned docs, retraction-aware
literature, time-stamped policies — Tier 1 (structural metadata only) is
enough. No extraction beyond the entities you already extract for graph
boost. No LLM calls at query time. The two paths in this series both run
purely on Tier 1.

## What's in the rest of the series

- **Post #2 — [Versioned Python docs](02-path-a-versioned-python-docs.md).** Ingest
  Python 3.10, 3.11, and 3.12 documentation under three `version_label`s.
  Query with and without `version_filter`. See where it works (13/13
  perfect filter purity) and one honest place where it doesn't (PEP 695
  `type` keyword query without a filter).
- **Post #3 — [Medical retractions](03-path-b-medical-retractions.md).** Ingest 48
  PubMed abstracts on HRT and cardiovascular outcomes spanning 1998
  through 2025. Demonstrate that the same query about HRT
  cardioprotection returns different correct answers depending on
  whether you ask "now" with retractions hidden, or `as_of=2001-12-31`
  before the WHI trial result.

If your corpus is static, the second post is still worth reading —
versioning your own internal docs starts mattering as soon as you have
two releases. If your corpus is evolving, post #3 is probably the one
that maps to your problem.

## Try it

Both paths are real benchmark scripts in the repo, not contrived demos.
Clone and run:

```bash
git clone https://github.com/yonk-labs/pg-raggraph
cd pg-raggraph
docker compose up -d postgres
uv sync

# Path A — versioned Python docs
cd benchmarks/python-versioned-docs
uv run python download_python_docs.py
uv run python ingest.py
uv run python run_path_a.py

# Path B — medical retractions
cd ../medical-hrt
# (download script + curated manifest + ingest + runner)
uv run python ingest.py
uv run python run_path_b.py
```

The decision matrix at [`docs/USE-CASES.md`](../USE-CASES.md) helps you
pick which workload fits your corpus.
