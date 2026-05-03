---
title: "Versioning your docs corpus: a Python 3.10/3.11/3.12 walkthrough"
slug: "02-path-a-versioned-python-docs"
date: 2026-04-27
audience: external
series: "Tier 1 evolving knowledge"
part: 2
---

# Versioning your docs corpus: a Python 3.10/3.11/3.12 walkthrough

If your product ships across versions and your docs accumulate, classic
RAG has a problem: a query about Python 3.12's `StrEnum` enhancements
will happily return the 3.10 docs, because they all say "StrEnum"
loudly. The user gets cross-version contamination. They don't know.

pg-raggraph's Tier 1 evolution tracking solves this with one piece of
metadata at ingest — `version_label` — and one query-time keyword —
`version_filter`. This post measures how well that works on real Python
documentation.

## What we ingested

12 documents: four pages × three Python versions.

| Version | Pages |
|---|---|
| 3.10 | `library/enum`, `library/typing`, `reference/datamodel`, `whatsnew/3.10` |
| 3.11 | `library/enum`, `library/typing`, `reference/datamodel`, `whatsnew/3.11` |
| 3.12 | `library/enum`, `library/typing`, `reference/datamodel`, `whatsnew/3.12` |

Total: 1,364 chunks. The pages were chosen because their content shifts
meaningfully across versions (`StrEnum` added in 3.11 and enhanced in
3.12, PEP 604 union types in 3.10, PEP 695 type-parameter syntax in
3.12, datamodel changes per release).

Each ingest call carried `metadata={"version_label": "Python 3.x"}`.
That's it. No Tier 2, no LLM-inferred supersession. pgrg promotes that
metadata key into a real column on `documents`, indexed for cheap
filtering at query time.

```python
# benchmarks/python-versioned-docs/ingest.py (excerpt)
for version in ("3.10", "3.11", "3.12"):
    label = f"Python {version}"
    for html_file in pages_for(version):
        await rag.ingest(
            [str(html_file)],
            namespace="python_docs",
            metadata={"version_label": label},
        )
```

## What we measured

15 hand-written gold questions across four categories:

- **filtered_match (5)** — query supplied a `version_filter`; expect
  top-5 chunks ONLY from the matching version.
- **cross_version (6)** — same intent across versions (e.g. "How do I
  use StrEnum?" with `version_filter="Python 3.11"` vs `"Python 3.12"`).
- **whatsnew (2)** — release-notes Qs with a version filter.
- **unfiltered_target (2)** — query about a 3.12-only feature, no
  filter; expect 3.12 chunks in top-3 anyway.

The full runner is [`run_path_a.py`](../../benchmarks/python-versioned-docs/run_path_a.py).
Mode: `naive_boost`, `top_k=10`, top-5 used for filter purity check,
top-3 for the unfiltered target check.

## Numbers

| Threshold | Result | Pass? |
|---|---|---|
| ≥ 80% of `version_filter`-tagged Qs return top-5 ONLY from matching version | **100% (13/13)** | YES |
| ≥ 1 unfiltered_target Q has expected version in top-3 | **1/2** | YES |

| Category | n | passed | rate |
|---|---|---|---|
| filtered_match | 5 | 5 | 100% |
| cross_version | 6 | 6 | 100% |
| whatsnew | 2 | 2 | 100% |
| unfiltered_target | 2 | 1 | 50% |
| **Total** | **15** | **14** | **93.3%** |

Filter purity is the headline. Every single question that supplied a
`version_filter` returned top-5 chunks consisting *only* of chunks from
the requested version. Zero leakage across 13 questions, including
cross-version pairs where the question text was identical and only the
filter changed.

## The one we got wrong

`pyver-q-012` — "What does PEP 695 syntax for type aliases look like?",
asked without a filter — returned top-5 chunks ranked
`['Python 3.11', 'Python 3.10', 'Python 3.10', 'Python 3.10', 'Python 3.10']`.
None from 3.12, where PEP 695 actually lives.

The cause is mundane and instructive: the user's vocabulary ("type
aliases") matches the older `typing.TypeAlias` documentation more
strongly than 3.12's terse `type` keyword. The 3.12 doc says things
like "the new `type` statement provides a concise way to define type
aliases" — short, sparse, dense. The 3.10/3.11 docs go on for
paragraphs about `TypeAlias`. In a vector + BM25 race, the older docs
win on surface overlap.

This is exactly when you reach for `version_filter`. With
`version_filter="Python 3.12"` on the same question, the runner returns
five 3.12 chunks in the top-5. The library knows where to look; it just
needs the user (or the application layer) to tell it.

The implication for Tier 1 users: when answer phrasing shifts sharply
across versions and the user's question uses older terminology,
unfiltered retrieval can drift toward older content. Mitigations:
require `version_filter` on routes that need it, or add a recency
weight (`config.w_recent`) to favor newer documents at scoring time.

## How to try it

From a fresh clone:

```bash
git clone https://github.com/yonk-labs/pg-raggraph
cd pg-raggraph
docker compose up -d postgres
uv sync

cd benchmarks/python-versioned-docs
uv run python download_python_docs.py    # fetch HTML, ~5s
uv run python ingest.py                  # ingest with version_label, ~30 min
uv run python run_path_a.py              # runs 15 Qs, ~10 sec
```

You should see the same per-question PASS/FAIL trace and a `results.json`
with the same SC-004 verdict. Within ±1 question per category across
runs, the numbers reproduce.

## When this approach fits your project

Reach for the `version_filter` pattern if:

- Your docs ship across versioned releases (libraries, APIs, SDKs).
- Users routinely ask version-scoped questions.
- You don't want the answer for v1 to leak into a query about v2.

You probably don't need this if:

- Only one version is "live" at a time and you prune old docs.
- Your corpus has no temporal axis at all (most internal wikis).

## Up next

Post #3 covers Path B — medical literature with real retractions, where
the answer changes after a published trial result. Same library, same
database, very different corpus shape.
