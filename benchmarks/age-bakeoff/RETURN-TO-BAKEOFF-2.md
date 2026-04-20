# Return to the bake-off — session handoff #2 (2026-04-20)

**Continuation of the work after [RETURN-TO-BAKEOFF.md](RETURN-TO-BAKEOFF.md) and the four tasks it scoped.**

Tasks 21-24 are **done** (hierarchy port to bake-off, full hierarchy sweep on SCOTUS, graph-augmentation verdict, pg-raggraph-vs-AGE verdict). Three commits landed on `main` (`9c7b6da`, `0cc6017`, `92ae493`).

This handoff covers the **follow-on work kicked off via `/autonomy`** — steps 1-4 of the post-bake-off sequence — and where that got interrupted.

---

## The one-sentence status

**The "ship hierarchy as the default chunker" recommendation from REPORT-VERDICT.md is dead.** Acme did not replicate SCOTUS's +7/+8 lift — in fact hierarchy slightly hurt accuracy on acme and introduced hallucinations. The SCOTUS win was dataset-specific. We need to decide how to ship this honestly before continuing.

---

## What happened (chronological)

1. User invoked `/autonomy` with a 4-step sequence:
   1. Second-corpus replication on acme
   2. Port hierarchy into `src/pg_raggraph/chunking.py` (default if step 1 passes)
   3. Smart-mode investigation (smart 17 vs naive 18/30 on SCOTUS)
   4. `/whats-next` deep dive
2. Autonomy contract written to `.autonomy/contract-2026-04-19-post-bakeoff.md`.
3. Tasks 5-8 created. Task 5 (acme sweep) marked in_progress; 6/7/8 pending with blockedBy chain.
4. Acme hierarchy sweep launched in background via a one-off driver script (`/tmp/acme-hier-sweep.sh`, not checked in; the reusable driver is `scripts/run-hier-sweep.sh`).
5. Sweep completed all 6 raw JSONs in ~1 hour total wall (first mode ~4 min with ingest, subsequent modes ~3 min each under `SKIP_INGEST=1`).
6. Judge phase hit its 20-minute wrapper timeout **during the 6th file** (acme__hier_smart). Judge was re-run manually; still in progress at the time of handoff.
7. Smart-mode investigation done in parallel (see below) — smart loses to naive on exactly 1 question on SCOTUS. Within noise.
8. Acme replication numbers analyzed from 5 of 6 finished judge files; the pattern was clear enough to stop and escalate. Smart-mode judgement at ±1 question doesn't change the story.
9. This handoff written. Judge still running for acme__hier_smart.

---

## The acme finding (full detail in `results/ACME-HIER-REPLICATION.md`)

| mode | acme pgrg sentence_aware | acme pgrg hierarchy | delta | SCOTUS delta (for contrast) |
|---|---|---|---|---|
| hybrid | 5/30 | 4/30 | **-1** | +8 |
| local | 6/30 | 4/30 | **-2** | +8 |
| global | 7/30 | 5/30 | **-2** | +8 |
| naive | 4/30 | 4/30 | 0 | +8 |
| naive_boost | 4/30 | 5/30 | +1 | +7 |
| smart | 6/30 | pending re-judge | ? | -1 |

Hallucinations: acme sentence_aware = 1-3 per mode; acme hierarchy = 3-4 per mode; SCOTUS = 0 across both chunkers.

**Diagnosis:** hierarchy's title-prefix fallback (`"{title}\n\n{body}"`) wins when titles are **concrete, disambiguating nouns** (SCOTUS: "Miranda v. Arizona: Overview"). It loses when titles are **format strings** (acme: "Weekly sync: Search Redesign status update"). On acme every chunk ends up prefixed with a meeting-format phrase that repeats across the corpus — homogenizing rather than disambiguating the embeddings.

---

## Smart-mode investigation (Task 7 partial)

Looked at `src/pg_raggraph/retrieval.py:376-436` (`_smart_query`). The routing logic:
- high confidence → ship naive as-is
- medium confidence → graph-boost (re-rank existing top-K by connectivity)
- low confidence → escalate to local mode

Per-question diff on SCOTUS hier_smart vs hier_naive:
- smart loses to naive on exactly **1** question (scotus-q-012: Flowers v. Mississippi authorship — same top-3 docs, slightly different chunks, same preview answer, verdict drifted partially_correct vs fully_correct).
- naive loses to smart on **0** questions.

**Conclusion:** the 17 vs 18 delta is **within ±1-question noise**, not a real mode failure. Smart is functioning as designed. A cleaner decision on smart needs either (a) a bigger question set or (b) re-examining the confidence-threshold calibration against the 18/30 operating point — out of scope for a "ship it or demote it" call.

**Recommendation:** don't demote smart; don't ship a fix based on a single-question delta. Document the near-tie in a release note if/when the chunker story gets resolved.

---

## Where this leaves us

### What's decided

- **Hierarchy ≠ default.** SCOTUS-specific artifact; acme regressed. Whatever we ship into the library is opt-in.
- **Smart mode is fine.** The SCOTUS 17 vs 18 gap is noise. No code change; maybe a doc footnote.
- **The AGE bake-off is closed.** `REPORT-VERDICT.md` and `GRAPH-AUGMENTATION-VERDICT.md` correctly answer the main questions they set out to answer.

### What's NOT decided — pick one before resuming

**A. Ship hierarchy as opt-in, soften verdict docs** _(recommended)_ — 2-3 hours.
  - Port `_split_hierarchy` into `src/pg_raggraph/chunking.py` behind a `chunk_strategy` config flag.
  - Keep current default ("auto" / sentence_aware for prose).
  - Add CHANGELOG entry explaining when to use it.
  - Update `REPORT-VERDICT.md` §6 ("ship hierarchy as default") and `GRAPH-AUGMENTATION-VERDICT.md` shipping section to say "ship as opt-in for corpora with concrete per-doc titles."
  - Add `results/ACME-HIER-REPLICATION.md` to the doc chain (already done — exists on disk; not yet committed).
  - Close the autonomy contract.

**B. Third-corpus replication before shipping** — 3-5 hours (+~$2 budget).
  - Build or source a third corpus (Wikipedia-article-shaped, or tech doc pages) whose titles are concrete but not case-name-shaped. Validate where the boundary lies between "SCOTUS-win" and "acme-draw."
  - Then proceed to (A)-style port.
  - Stronger empirical base; slower to ship.

**C. Heuristic title-quality detection at ingest** — days of work, probably brittle.
  - Not recommended unless we have a compelling motivation (paying customer with mixed-title corpora, etc.).

### Outstanding items independent of the fork

- Re-judge `acme__hier_smart.json` — background job is running, should finish within 30 min of this handoff. Once done, verify the smart row in `ACME-HIER-REPLICATION.md`. The story doesn't change materially either way.
- `ACME-HIER-REPLICATION.md` is on disk but **not committed**. Same for this handoff doc.
- Task 8 (`/whats-next`) never ran.

---

## Environment & paths

Same as `RETURN-TO-BAKEOFF.md` §Environment. Key:

- Working dir: `/home/yonk/yonk-tools/pg-raggraph`
- Both DBs up (pgrg :5434, age :5435). Both corpora ingested with hierarchy chunks still in place from yesterday's runs (can be reused via `--skip-ingest`).
- Budget: ~$47 of $50 remaining.

## Uncommitted state at handoff time

```
results/ACME-HIER-REPLICATION.md                 (new)
results/judge/acme__hier_{global,hybrid,local,naive,naive_boost}.json  (new, 5/6)
results/raw/acme__hier_*.json                    (new, gitignored)
benchmarks/age-bakeoff/RETURN-TO-BAKEOFF-2.md   (new, this doc)
.autonomy/contract-2026-04-19-post-bakeoff.md    (new)
.autonomy/summaries/                              (empty, nothing to save)
```

And one still-running background judge command (`br199c63e`): `uv run age-bakeoff judge --corpus acme`. Let it finish; it'll write `results/judge/acme__hier_smart.json` and update `results/cost-judge.json`.

## Tasks at handoff

| id | status | subject |
|---|---|---|
| 5 | in_progress | Step 1: Acme hierarchy sweep + replication analysis |
| 6 | pending | Step 2: Port hierarchy chunker into pg-raggraph library |
| 7 | pending | Step 3: Smart mode decision |
| 8 | pending | Step 4: /whats-next deep dive |

Task 5 becomes complete once the smart re-judge finishes and `ACME-HIER-REPLICATION.md` is committed. Task 6 awaits the fork decision above. Task 7 is effectively resolved (documented above); needs to be marked completed and the conclusion linked into a release note. Task 8 should run after 6/7 close.

---

## One-line next-session prompt

```
Read benchmarks/age-bakeoff/RETURN-TO-BAKEOFF-2.md then pick A/B/C from the
"What's NOT decided" section and continue. ACME-HIER-REPLICATION.md has the
full data; the SCOTUS "ship hierarchy as default" recommendation is now
incorrect and needs to be softened before it misleads future readers.
```
