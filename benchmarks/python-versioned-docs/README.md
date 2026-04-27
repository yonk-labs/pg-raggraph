# Python versioned docs corpus — Tier 1 Path A

**Purpose:** Real-world corpus for testing pgrg's `version_filter` Tier 1
evolution feature. Same Python language reference page (or selected pages)
ingested three times under three `version_label`s — Python 3.10, 3.11, 3.12.
Tests whether retrieval correctly scopes to a single version.

**Source:** `https://docs.python.org/3.10/`, `…/3.11/`, `…/3.12/` —
official docs, BSD-licensed.

**Mission brief:** `skill-output/mission-brief/Mission-Brief-tier1-real-bench-tutorial.md`
SC-003, SC-004.

## Files

- `download_python_docs.py` — fetches selected pages for each version
- `ingest.py` — ingests with `metadata={"version_label": "Python 3.x"}`
- `gold.yaml` — ≥15 hand-written gold questions
- `run_path_a.py` — runs the gold questions and produces metrics
- `results.md` — measured numbers (filled in after benchmarking)

## Pages selected (rationale)

We pick **4 pages × 3 versions = 12 documents** that cover features with
known cross-version differences, so `version_filter` has real signal to
exploit:

1. `library/enum.html` — `StrEnum` added in 3.11; enhanced in 3.12.
2. `whatsnew/3.10.html`, `whatsnew/3.11.html`, `whatsnew/3.12.html` — version-specific changes.
3. `library/typing.html` — type-hint surface evolves every release.
4. `reference/datamodel.html` — language-level changes (e.g., 3.12 PEP 695 generics).

Each page is downloaded for its target version. The "whatsnew" page is
version-specific by definition; the other three are downloaded three times.
