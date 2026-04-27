# Path B — Medical HRT real corpus results

**Date:** 2026-04-27
**Branch:** main @ `9fb2a6c`
**Mode:** `naive_boost`, top_k=10 (config default; top-5 used for retraction & pre-2002 checks)
**Corpus:** 48 PubMed HRT/CV abstracts; namespace `medical_hrt`
**Synthetic fixture:** `tests/fixtures/evolving/medical_retraction/` UNTOUCHED (constraint preserved)

## SC-006 Verdict

| Threshold | Result | Pass? |
|---|---|---|
| ≥ 4/5 retraction-aware Qs return ZERO retracted in top-5 (with `retracted_behavior="hide"`) | **5/5 (100%)** | **YES** |
| ≥ 1/5 time-travel Qs (as_of=2001-12-31) return ≥ 1 pre-2002 paper in top-5 | **5/5 (100%)** | **YES** |

**Overall SC-006:** **PASS**

## By category

| Category | n | n passed | rate |
|---|---|---|---|
| retraction_aware | 5 | 5 | 100% |
| time_travel | 5 | 5 | 100% |
| background | 5 | 5 | 100% |
| **Total** | **15** | **15** | **100%** |

## Plan adaptation — `as_of` date

The plan originally specified `as_of="1995-01-01"`. Reality: the earliest abstract in our PubMed haul has `pub_year=1998` (most are 1999–2001). At as_of=1995, the time-travel filter `effective_from <= as_of` excluded every document — zero results. Changed to **`as_of="2001-12-31"`** so the lens captures the full pre-WHI consensus era (1998–2001) without including the 2002 publications. Five questions × this date is the SC-006 evidence.

## What surprised us

1. **Retraction filtering is uniformly clean.** All five retraction-aware queries returned top-5 chunks with **zero** retracted documents. The 7 epistemically-retracted papers (pre-2002 HRT-CV-prevention endorsements) are reliably excluded when `retracted_behavior="hide"`. No leakage even on the most cardioprotection-specific phrasings.

2. **`as_of` correctly undoes retraction-time-bound exclusion.** At `as_of="2001-12-31"`, every time-travel query surfaced pre-2002 papers — *including* the ones marked retracted (retracted_at=2002-07-17). retracted_top5 was 4 or 5 of 5 chunks across all five time-travel queries. This is the cookbook contract: under default `retracted_behavior="flag"`, retracted documents return alongside current guidance, and the as_of filter only restricts on `effective_from` / `effective_to`. The retraction date itself isn't compared against as_of by the SQL — but the practical result is "papers visible at as_of are the era's consensus" because the retraction tagging *describes* the supersession that happened later.

3. **The same query genuinely gives two different answers.** "Is hormone replacement therapy cardioprotective?" with the modern lens (retracted hidden) returns the WHI/post-WHI cautionary literature exclusively. The same query at as_of=2001-12-31 returns the pre-WHI consensus — supportive papers, including the ones now considered superseded. Two answers from the same database without re-ingesting or re-training. **This is the thing the Tier 1 evolving-knowledge feature was built to do.**

## Per-question

See `results.json` for full row dump including chunk-level `top5_meta` (retracted, year) for each query.

## Notes for the blog post

- Lead with "5/5 retraction-aware queries returned zero retracted papers in top-5" — that's the definitive Tier 1 retraction proof on real medical literature.
- Pair it with "5/5 time-travel queries returned the pre-2002 consensus". Same database, two answers.
- Spell out the editorial-retraction-tagging clearly: PubMed didn't formally retract these papers; we tagged them retracted=true to model the *epistemic* retraction WHI represented. Honest, reproducible, real-world.
- Avoid claiming Path B uses formally retracted papers — that's not what the corpus is. The README's "Editorial choice" section is the canonical statement.
