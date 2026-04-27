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
