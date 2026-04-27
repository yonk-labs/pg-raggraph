---
title: "When the answer changes: GraphRAG over retracted medical literature"
slug: "03-path-b-medical-retractions"
date: 2026-04-27
audience: external
series: "Tier 1 evolving knowledge"
part: 3
---

# When the answer changes: GraphRAG over retracted medical literature

In July 2002, the Women's Health Initiative published a randomized trial
that overturned the previous decade's consensus on hormone replacement
therapy. Pre-WHI: HRT was widely thought to reduce coronary risk.
Post-WHI: combined HRT was shown to *increase* coronary events, and
guidelines stopped recommending it for primary cardiovascular
prevention.

If you ask a vanilla RAG system "is HRT cardioprotective?" against a
corpus that contains both eras of literature, it returns whatever the
vector index prefers — which is often the older, denser, more numerous
pre-2002 papers. The system sounds confident. It is wrong.

This post walks through the same query against pg-raggraph using two
Tier 1 features: `retracted_behavior="hide"` (return modern guidance
only) and `as_of` (return the consensus that existed on a given date).
The corpus is real PubMed literature.

## What we ingested

48 PubMed abstracts on HRT and cardiovascular outcomes, spanning 1998
through 2025. Three buckets, fetched via three NCBI eutils searches:

- **Pre-2002 (13 abstracts):** the supportive consensus era —
  observational studies and reviews concluding HRT helps coronary
  outcomes.
- **WHI-era (22 abstracts, 2002-2004):** the trial publication and
  immediate aftermath — methodology critiques, guideline revisions,
  practice-pattern shifts.
- **Post-2002 (13 abstracts, 2003+):** modern cautionary guidance plus
  more recent reviews of HRT for non-CV indications.

The corpus is at [`benchmarks/medical-hrt/`](../../benchmarks/medical-hrt/).
PubMed query expressions are in
[`pubmed_query.txt`](../../benchmarks/medical-hrt/pubmed_query.txt).
A curated [`manifest.yaml`](../../benchmarks/medical-hrt/manifest.yaml)
maps each abstract to its evolution metadata: `effective_from` (Jan 1
of `pub_year`), `retracted` (boolean), and where applicable
`retracted_at` and `retraction_reason`.

### Editorial choice — what `retracted=true` means in this corpus

This is important and we want to be precise. The papers in this corpus
were not formally journal-retracted. PubMed's `PublicationType` does not
flag any of them as "Retracted Publication". So we applied an
**editorial** classification:

> Pre-2002 papers whose titles indicate endorsement of HRT for
> cardiovascular prevention (matched by a heuristic on
> HRT/hormone-replacement keywords combined with
> prevention/morbidity/mortality/cardiovascular keywords) are tagged
> `retracted=true`, with `retracted_at=2002-07-17` (the WHI primary
> publication date) and `retraction_reason="WHI 2002 RCT invalidated
> HRT cardioprotection findings"`.

This models the **epistemic retraction** that WHI represented. The
papers themselves still exist; their cardioprotection conclusions are
no longer believed by the medical community. In real-world Tier 1
evolving knowledge, this pattern is more common than formal retractions
— supersession by stronger evidence, not journal withdrawal.

7 of the 48 abstracts are tagged `retracted=true` under this
classification. Modern medical professionals would tell you the
remaining pre-2002 papers about HRT methodology, cautionary
observational signals, or unrelated topics are not invalidated by WHI
even if they were published in the same era.

## What we measured

15 hand-written gold questions across three categories:

- **retraction_aware (5)** — set `retracted_behavior="hide"`, ask the
  cardioprotection-shaped question, expect zero retracted abstracts in
  top-5.
- **time_travel (5)** — ask the same question with `as_of=2001-12-31`,
  expect at least one pre-2002 paper in top-5 (the pre-WHI consensus
  surfaces).
- **background (5)** — general HRT/CV questions with no retraction
  expectation; shape check only.

Mode: `naive_boost`, `top_k=10`. Full runner:
[`run_path_b.py`](../../benchmarks/medical-hrt/run_path_b.py).

## Numbers

| Threshold | Result | Pass? |
|---|---|---|
| ≥ 4/5 retraction_aware Qs return ZERO retracted in top-5 (with `retracted_behavior="hide"`) | **5/5 (100%)** | YES |
| ≥ 1/5 time_travel Qs (`as_of="2001-12-31"`) return ≥ 1 pre-2002 paper in top-5 | **5/5 (100%)** | YES |

| Category | n | passed | rate |
|---|---|---|---|
| retraction_aware | 5 | 5 | 100% |
| time_travel | 5 | 5 | 100% |
| background | 5 | 5 | 100% |
| **Total** | **15** | **15** | **100%** |

## A real query, end to end

```python
from datetime import datetime, timezone
from pg_raggraph import GraphRAG

rag = GraphRAG(dsn=DSN, namespace="medical_hrt", evolution_tier="structural")
await rag.connect()

# 2026 view — retractions hidden. Returns modern guidance only.
rag.config.retracted_behavior = "hide"
modern = await rag.query("Is hormone replacement therapy cardioprotective?")

# 2001 view — pre-WHI consensus. Reset retracted_behavior to default first;
# retracted papers should surface alongside non-retracted ones at as_of.
rag.config.retracted_behavior = "flag"
pre_whi = await rag.query(
    "Is hormone replacement therapy cardioprotective?",
    as_of=datetime(2001, 12, 31, tzinfo=timezone.utc),
)
```

The two `result.chunks` lists reflect what the medical community
actually believed in each era. Same corpus. One database. No retraining.
No re-ingestion. Just two predicates added to the SQL at query time.

## How `as_of` and retraction interact

This is subtle and worth being explicit about. The Tier 1 SQL adds
two filter clauses when relevant:

- **Retraction filter** (only when `cfg.retracted_behavior == "hide"`):
  `NOT documents.retracted`. Absent under `"flag"` (the default).
- **as_of filter** (when `as_of` is supplied): bounds
  `documents.effective_from <= as_of` AND `effective_to > as_of` (or
  null).

The `retracted_at` column lives on `document_versions` and isn't
compared against `as_of` by the SQL filter — *and that's the right
behavior*. `as_of` describes "what was true at time T" via effective
windows. Whether a paper has *since* been retracted is captured by the
`retracted` flag, which controls visibility under
`retracted_behavior="hide"`. The two predicates compose:

| Mode | retracted_behavior | as_of | Result |
|---|---|---|---|
| Modern lens | `"hide"` | none | only non-retracted, current effective |
| Pre-WHI lens | `"flag"` | `2001-12-31` | retracted + non-retracted papers whose effective_from ≤ 2001-12-31 |
| Modern with audit trail | `"flag"` | none | everything; flagged for the caller |

In the Path B runner, retraction_aware questions use the modern lens
and time_travel questions use the pre-WHI lens.

## What surprised us

The retraction filter is almost stubbornly clean. Five queries phrased
deliberately to favor pre-2002 framing ("Is HRT cardioprotective?",
"Should women take HRT to prevent coronary heart disease?", "Does
estrogen plus progestin prevent cardiovascular events?", etc.) all
returned top-5 chunks with **zero** retracted documents. The retracted
papers were filtered at the SQL level and never reached the scorer.

The time-travel result is the more interesting half. With
`as_of="2001-12-31"`, every retraction_aware query phrased identically
came back with 4 or 5 of 5 top chunks from the retracted-tagged papers
— the pre-WHI consensus literature. That's the test: at a date when
those papers had not yet been epistemically retracted by WHI, the
library returns them. Same query. Same database. Different temporal
lens.

## How to try it

From a fresh clone:

```bash
git clone https://github.com/yonk-labs/pg_raggraph
cd pg_raggraph
docker compose up -d postgres
uv sync

cd benchmarks/medical-hrt

# Re-fetch abstracts (~15s, idempotent — skips cached files)
uv run python download_abstracts.py \
  --query '("hormone replacement therapy"[Title/Abstract] OR "HRT"[Title/Abstract]) AND ("cardiovascular"[Title/Abstract] OR "coronary"[Title/Abstract]) AND ("1990"[Date - Publication] : "2001"[Date - Publication])' \
  --max 15 --out abstracts/pre2002/

# (Run the other two queries from pubmed_query.txt the same way.)

# Inspect / re-curate manifest.yaml as needed
uv run python ingest.py             # ~10 min
uv run python run_path_b.py         # ~5 sec, prints PASS/FAIL trace
```

The corpus and manifest are committed to the repo; re-running is purely
about reproducing the numbers, not regenerating the data.

## When this approach fits your project

Reach for the `retracted` + `as_of` pattern if:

- Your corpus accumulates over time and corrections are common.
- Users ask "what was the consensus on date X?" — directly or via
  product features like time-travel audits.
- You have publication-date or effective-date metadata available, even
  if your "retraction" signal is editorial rather than formal.

You probably don't need it if:

- Your corpus is curated and stale entries are pruned (most product
  docs work this way).
- All your users want is "the latest" — `effective_from` ordering and
  recency-weighted scoring give that without retraction tracking.

## Wrapping up the series

Three posts, two corpora, one library. If you're building a knowledge
base where the answer changes — by version, by time, by retraction —
you can do it on plain Postgres without giving up the speed and
operational simplicity that got you to Postgres in the first place.

For the decision matrix on which workload fits your corpus, see
[`docs/USE-CASES.md`](../USE-CASES.md). For the API reference,
[`docs/user-guide.md`](../user-guide.md). For the Tier 1 quickstart,
[`docs/cookbook/evolution-tracking.md`](../cookbook/evolution-tracking.md).
