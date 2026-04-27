# Medical HRT real corpus — Tier 1 Path B

**Purpose:** Real-world corpus testing pgrg's `retracted` filtering and
`as_of` time-travel Tier 1 features against published medical literature
on hormone replacement therapy (HRT) and cardiovascular outcomes — the
canonical "answer changes after a date" case (WHI 2002 retraction of
the prior cardioprotection consensus).

**Source:** PubMed via NCBI eutils API (`https://www.ncbi.nlm.nih.gov/`).
Abstracts are public-domain summaries; we use abstracts only, not full text.

**Mission brief:** `skill-output/mission-brief/Mission-Brief-tier1-real-bench-tutorial.md`
SC-005, SC-006.

**IMPORTANT:** This corpus is fully separate from the synthetic fixture at
`tests/fixtures/evolving/medical_retraction/` (mission brief constraint).
The synthetic fixture stays for unit tests; this is the real-world corpus
that produces the publishable Path B numbers.

## Files

- `pubmed_query.txt` — exact PubMed search expressions
- `download_abstracts.py` — fetches abstracts via NCBI eutils
- `manifest.yaml` — ≥30 curated abstracts with `effective_from` /
  `retracted` / `retracted_at` / `retraction_reason` metadata
- `ingest.py` — ingests abstracts into pgrg with metadata
- `gold.yaml` — ≥15 hand-written gold questions (≥5 retraction-aware)
- `run_path_b.py` — runs gold Qs in two configurations
  (`retracted_behavior="hide"` and `as_of=1995-01-01`)
- `results.md` — measured numbers + Path B verdict

## Editorial choice — what `retracted=true` means in this corpus

The papers in this corpus were not formally journal-retracted. Their PubMed
records have no `PublicationType="Retracted Publication"`. So we are
applying an *editorial* classification:

> Pre-2002 papers whose titles indicate endorsement of HRT for cardiovascular
> prevention (using a heuristic: HRT/hormone-replacement keywords AND
> prevention/morbidity/mortality/cardiovascular keywords, excluding methodology
> and pre-WHI cautionary papers) are tagged `retracted=true` with
> `retracted_at=2002-07-17` (date of the WHI primary publication) and
> `retraction_reason="WHI 2002 RCT invalidated HRT cardioprotection findings"`.

This models the **epistemic retraction** that WHI represented: the prior
consensus that HRT prevents cardiovascular disease was overturned by a
large RCT. The papers themselves still exist; their conclusions are no
longer believed by the medical community. In real-world Tier-1 evolving
knowledge, this is the most common pattern — formal retraction notices
are rare; supersession by stronger evidence is common.

Result: 7 of 48 abstracts are tagged `retracted=true`. SC-006 evaluates
whether `retracted_behavior="hide"` correctly excludes them.

## Curation provenance

- `download_abstracts.py` ran the three queries in `pubmed_query.txt`,
  yielding 56 abstracts (15 pre-2002 + 26 WHI + 15 post-2002).
- 8 abstracts with empty `abstract` text were dropped.
- Final corpus: **48 abstracts** (13 + 22 + 13), 7 `retracted=true`.
- Each entry's `effective_from` = January 1 of `pub_year`.

