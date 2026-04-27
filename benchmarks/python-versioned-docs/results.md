# Path A — Versioned Python docs results

**Date:** 2026-04-27
**Branch:** main @ `369c2ea`
**Mode:** `naive_boost`, `top_k=10` (config default; top-5 used for filter check, top-3 for target check)
**Corpus:** 12 docs (Python 3.10 / 3.11 / 3.12 × {enum, typing, datamodel, whatsnew}); 1364 chunks total; namespace `python_docs`

## SC-004 Verdict

| Threshold | Result | Pass? |
|---|---|---|
| ≥ 80% of `version_filter`-tagged Qs return top-5 chunks ONLY from matching version | **100% (13/13)** | **YES** |
| For ≥ 1 unfiltered_target Q, top-3 contains expected version | **1/2** | **YES** |

**Overall SC-004:** **PASS**

## By category

| Category | n | n passed | rate |
|---|---|---|---|
| filtered_match | 5 | 5 | 100% |
| cross_version | 6 | 6 | 100% |
| whatsnew | 2 | 2 | 100% |
| unfiltered_target | 2 | 1 | 50% |
| **Total** | **15** | **14** | **93.3%** |

## What surprised us

1. **Version filtering is uniformly clean when invoked.** All 13 questions that supplied a `version_filter` returned top-5 chunks consisting **only** of chunks from the requested version label. Zero leakage. The `version_label` column promotion (from ingest metadata to `documents.version_label`) plus the retrieval-time predicate is doing exactly the job it was designed to do.

2. **Cross-version Qs work without ambiguity.** Pairs like "How do I use StrEnum?" with `version_filter="Python 3.11"` vs `"Python 3.12"` correctly resolved each time. No vector-space contamination across versions despite identical question text and overlapping chunk content.

3. **Unfiltered targeting is lossier.** `pyver-q-012` ("What does PEP 695 syntax for type aliases look like?") returned 3.11/3.10 chunks in top-5, not 3.12 as expected. Cause: the older docs discuss `TypeAlias` from `typing` (the pre-PEP-695 way), and the question keyword "type alias" has stronger surface-level overlap with the older content than with 3.12's terse `type` keyword. This is a *real-world challenge for unfiltered evolving-knowledge retrieval* — when newer terminology is sparser, vector search drifts toward older synonyms. `pyver-q-013` ("new syntax for generic functions added in 3.12") did get 3.12 in top-3, partly because "3.12" is mentioned in the whatsnew page directly.

   Implication for users: when answer phrasing varies sharply across versions, pure unfiltered retrieval can pick the wrong era. `version_filter` (when intent is known) and recency-weighted scoring (`w_recent`, surfaced for tuning) are the mitigations.

## Per-question

See `results.json` for full row dump including chunk-level `top_versions` for each query.

## Notes for the blog post

- Lead with "13/13 perfect filter purity" — that's the clean win.
- Use `pyver-q-012` as the honest counter-example: an unfiltered query about a 3.12-only feature can still retrieve older content if the answer terminology shifted dramatically. Frame as "this is exactly when you reach for `version_filter`".
- Mention the corpus stats (1364 chunks, 12 docs) to give a sense of corpus weight.
