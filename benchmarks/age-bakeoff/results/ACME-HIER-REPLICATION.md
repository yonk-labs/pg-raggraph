# Hierarchy chunker on acme — does the SCOTUS win replicate?

**Short answer: no. The SCOTUS +7/+8 lift was a dataset-specific artifact, not a universal chunker win.**

**Run date:** 2026-04-19 (pre-midnight into 2026-04-20).
**Corpus:** acme — 160 project-update / meeting-note / 1:1 docs (synthetic workplace knowledge base). 30 gold-labeled questions × 3 runs = 90 Q-runs per engine per mode.
**Chunker under test:** hierarchy (heading-aware + title-prefix fallback), opt-in via `BAKEOFF_CHUNKER=hierarchy`.
**Compared against:** acme sentence_aware baselines from 2026-04-18 (yesterday).
**Embedder / answer / judge:** BAAI/bge-small-en-v1.5 / gpt-5-mini / gpt-5-mini (majority-of-3).

## Headline

Acme pgrg `fully_correct` / 30, sentence_aware → hierarchy:

| mode        | sentence_aware | hierarchy | delta | hallucinations (sa → h) |
|-------------|----------------|-----------|-------|-------------------------|
| hybrid      | 5              | 4         | **-1** | 1 → 4 |
| local       | 6              | 4         | **-2** | 2 → 4 |
| global      | 7              | 5         | **-2** | 2 → 4 |
| naive       | 4              | 4         | 0     | 3 → 4 |
| naive_boost | 4              | 5         | +1    | 2 → 3 |
| smart       | 6              | 4         | **-2** | 1 → 6 |

_**(Smart row re-judged 2026-04-20. Landed at 4/30, consistent with the other hierarchy modes' regression pattern. All six rows are now final.)**_

For comparison, the same sweep on SCOTUS:

| mode | SCOTUS pgrg sentence_aware | SCOTUS pgrg hierarchy | delta |
|---|---|---|---|
| hybrid | 10 | 18 | **+8** |
| naive  | 10 | 18 | **+8** |

Hallucinations: SCOTUS stayed at 0 across both chunkers; acme hallucinations **went up** under hierarchy.

## What changed and why

On acme, the hierarchy chunker moved questions from "wrong" → "partially correct" (wrong: 10-12 → 7-8; partial: 12-13 → 14-16), but fully-correct counts didn't improve — and hallucinations ticked up.

The cause is the same mechanism that carried SCOTUS: hierarchy prepends the document title to every chunk (the "no markdown headings" fallback path), so pgvector sees `{title}\n\n{body}` as a single embedding unit. That trick wins or loses depending on **what the titles look like**.

| corpus | example title | effect when prefixed to every chunk |
|---|---|---|
| SCOTUS | `"Air and Liquid Systems Corp. v. Devries: Overview"` | Every chunk now strongly signals this specific case. Disambiguating. +8 questions. |
| acme   | `"Weekly sync: Search Redesign status update"` | Every chunk from this meeting looks like every other meeting. Semantically noisy. 0 lift, more hallucinations. |

SCOTUS titles are concrete nouns (`case name + aspect`). Acme titles are format strings (`format name + topic + update`). Prefixing a format string 160 times across the corpus doesn't disambiguate — it homogenizes.

## Implication: hierarchy is a tool, not a default

Shipping implication for pg-raggraph itself: **do NOT flip the library's default chunker to hierarchy based on SCOTUS alone.** The bake-off's "ship as default" recommendation in `REPORT-VERDICT.md` §6 and `GRAPH-AUGMENTATION-VERDICT.md` should be softened to:

> Hierarchy chunking wins when document titles are **concrete, unique, and semantically disambiguating** (per-entity docs like cases, papers, Wikipedia articles). It can slightly hurt when titles are **format-style** (meeting notes, status updates, 1:1s, generic emails) — every chunk carrying a repeated format phrase reduces embedding diversity. Plain-text docs with no useful title (e.g., raw transcripts, PDF extractions) land in the middle: hierarchy does nothing harmful but nothing helpful either.

### When to recommend hierarchy

- Legal / academic corpora where each doc has a unique title (case name, paper title, decision name).
- Wikipedia-shaped data where title = entity.
- Product documentation where each page is topic-named.

### When NOT to recommend hierarchy

- Meeting notes / status updates / standups with format-style titles.
- Email threads or chat transcripts with subject lines that repeat.
- Logs or time-series with generic titles.

## What to do next

**Task 2 (library port) is no longer "flip the default."** Revised options:

**Option A (recommended):** Port hierarchy into `src/pg_raggraph/chunking.py` as an **opt-in** strategy (`chunk_strategy: Literal["auto", "sentence_aware", "hierarchy"] = "auto"` config). Document when to use it per the heuristic above. Do not flip the default. Update `REPORT-VERDICT.md` §6 and `GRAPH-AUGMENTATION-VERDICT.md` to reflect the acme finding.

**Option B:** Before deciding, run a third corpus whose titles are **concrete but not case-name-shaped** — e.g., technical-doc pages, HN submissions, Wikipedia articles. Maps the boundary more precisely. Probably 1-2 hours of corpus prep + ~$1 run cost.

**Option C:** Build an auto-detection heuristic — inspect the title distribution at ingest time, turn hierarchy on only when titles are (a) unique per document and (b) not obvious format strings. Hard to get right; probably brittle. Would need its own eval sweep.

## Budget

Total acme sweep + judge: estimated <$1 (much cheaper than SCOTUS because 160 docs vs 772). Still well under the $50 ceiling; ~$47 remaining.

## Open items caused by this finding

1. **Update REPORT-VERDICT.md's shipping-recommendation section** — soften "ship as default" to "ship as opt-in."
2. **Update GRAPH-AUGMENTATION-VERDICT.md's shipping-implications section** — same softening.
3. ~~Re-judge `acme__hier_smart.json`~~ — **done 2026-04-20.** Result: 4/30 pgrg, 4/30 age. Matches the predicted 4-5 range and the rest of the regression pattern.
4. **Decide on the Option A/B/C fork above** before proceeding to library port.
5. **Optional third-corpus replication** (Option B) — would strengthen the generalization story either way.

## Artifacts

- `results/raw/acme__hier_{hybrid,smart,local,global,naive,naive_boost}.json` — all 6 raw files, 180 records each.
- `results/judge/acme__hier_{hybrid,local,global,naive,naive_boost,smart}.json` — all 6 judge files (smart added 2026-04-20).
- Baselines: `results/judge/acme.json` + `results/judge/acme__{smart,local,global,naive,naive-boost}.json` (unchanged from yesterday).
