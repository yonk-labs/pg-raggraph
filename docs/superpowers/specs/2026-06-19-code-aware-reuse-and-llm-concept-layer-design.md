# Code docs: pre_chunked⟷code-graph coexistence (A-enabler) + deferred LLM concept layer (B)

**Date:** 2026-06-19
**Status:** Design — pending review
**Repo scope:** **pg-raggraph (this repo) ONLY.** Bento is a downstream consumer owned
by a different agent. This spec defines two *library capabilities*; how/when bento
turns them on (reuse flags, the C1 embedder gate, the int8/#872 decision) is **out of
scope** and captured only as a handoff contract at the bottom.

---

## Goal — two independent library capabilities

1. **Capability 1 (makes vector-reuse SAFE for code docs).** Today, supplying
   `pre_chunked` chunks skips the code-graph staging, so a consumer that reuses
   upstream chunks+vectors for code would silently lose its code graph. Fix the
   library so `pre_chunked` and the deferred code-graph build **coexist**.
2. **Capability 2 (adds a conceptual graph layer — "B").** Today code-language docs
   get the structural graph (CALLS/INHERITS/IMPLEMENTS) but **no** LLM-extracted
   concepts. Add a config-gated path so the *already-existing* deferred LLM extractor
   also runs on code docs, producing a dual-level graph — **without touching ingest
   latency** (it runs in the background worker that already exists).

Both are opt-in library behaviors. Neither changes default behavior until a consumer
asks for it.

---

## Hard constraint: FAST INGEST

The deferred-extraction architecture (`backfill.py`) exists precisely so heavy graph
work stays off the ingest critical path. Every change here lives inside that
philosophy:
- Capability 1 *removes* work from ingest (no re-embed when `pre_chunked` is supplied).
- Capability 2 adds work **only** in the deferred worker — ingest latency unchanged.

No synchronous LLM call or synchronous graph resolution may be added to ingest.

---

## Background (pg-raggraph internals, today)

For a code-language doc ingested with `defer_extraction=True` (how bento drives
code-aware KBs):
- Chunking can come from the caller (`pre_chunked`) or pg-raggraph's own chunker
  (`__init__.py:1198-1238`). The `pre_chunked` path reuses caller embeddings and
  validates **dim only** (`:1205`).
- `__code_edges__` stamped on `chunk[0]` are popped; in cross-file/corpus mode the
  per-doc edges are intentionally dropped and a corpus symbol index is accumulated
  instead (`:1242-1268`).
- **The landmine:** `code_backfill_stage` is written **only when `pre_chunked is None`**
  (`:1508`). So the deferred code graph is fed only when pg-raggraph did its own
  chunking.
- Two deferred workers (`backfill.py`): `extract_documents` (`:156`) → LLM
  entity/relationship extraction via `_extract_one` (`:342`); `backfill_code_graph`
  (`:226`) → structural code graph. `_extract_one` runs the LLM branch only when
  `not skip_extraction and llm_base_url` (`:387`); a code doc with `skip_extraction`
  falls to `else` → `_mark_ready`, 0 entities (`:392-396`).
- Graph node/edge types: `code_graph.py` (`CALLS/INHERITS/IMPLEMENTS`),
  `chunkshop_bridge.py:117-151` (`CODE_SYMBOL` nodes keyed by `fqn`).

---

## Capability 1 — `pre_chunked` ⟷ code-graph staging coexistence

**Change.** Decouple `code_backfill_stage` population from the chunking branch. When a
doc is a code language **and** `defer_extraction` is set, stage it for the code-graph
worker **regardless of whether chunks arrived via `pre_chunked` or our own chunker**
(`__init__.py:1508` and surrounding block).

The stage row needs `content`, `language`, `source_path` (`backfill.py:298`). On the
`pre_chunked` path these come from the supplied chunk payload + its metadata (the
upstream chunker stamps `language`/`source_path`; if absent, fall back to the doc-level
`source_path` and language detection). **If a required field is missing on a
`pre_chunked` code doc, fail loud at ingest** — do not silently skip staging (that
reintroduces the landmine).

**Don't-lose-anything:**
- [ ] Staged `content` is the full per-symbol source the backfill re-parses — verify the corpus graph produces the **same edge set** from `pre_chunked` content as from self-chunked content (parity test).
- [ ] `CODE_SYMBOL` nodes + all three edge types still result.
- [ ] `fqn`/`callees` chunk metadata supplied via `pre_chunked` is persisted on the chunk rows (powers downstream symbol surfaces).
- [ ] `documents.graph_status` lifecycle unchanged (pending → ready after the deferred worker(s)).

**Tests (unit + integration):**
- `pre_chunked` + code language + defer → `code_backfill_stage` populated (direct regression for `:1508`).
- Edge-set parity: reused-chunks corpus == self-chunked corpus on a fixture repo.
- Missing `language`/`source_path` on a `pre_chunked` code doc → loud failure, not a silent no-stage.
- Non-code `pre_chunked` doc → no staging (unchanged).

---

## Capability 2 — deferred LLM concept layer for code docs ("B")

**Change.** Add a config flag (provisional: `PGRGConfig.extract_concepts_for_code`,
default **False**) that lets the deferred LLM extractor run on code-language docs
**in addition to** `backfill_code_graph`. When set:
- A code doc is processed by **both** deferred workers: structural resolver writes
  CALLS/INHERITS/IMPLEMENTS + `CODE_SYMBOL`; the LLM extractor writes concept entities
  + relationships over the same stored chunks (`_extract_one`, lift the
  `skip_extraction` short-circuit at `backfill.py:387` for this case).
- Use a **code-tuned extraction prompt** (extend the `devmem` prompt precedent:
  components / services / modules / concepts / dependencies — not generic prose
  entities). Open question: new prompt vs. reuse devmem's.
- Concept nodes must not collide with `CODE_SYMBOL` nodes of the same name — key/merge
  on `(name, entity_type)` so a concept "authentication" and a symbol
  `auth.login` stay distinct.

**graph_status terminal state.** With two deferred workers that must both finish,
`documents.graph_status` may only flip to `ready` once *both* complete. Confirm the
current state machine can express this (Open Question); if not, add a small
"both-done" gate. Default-off means this only matters when the flag is set.

**Fast-ingest:** unchanged — all of this is in the deferred phase.

**Don't-lose-anything:** structural graph is **authoritative and unchanged**; concept
layer is purely additive. Flag off → byte-identical to today.

**Tests:**
- Flag ON: code doc yields structural edges **and** concept entities.
- Flag OFF: structural-only, identical to current behavior (regression guard).
- Dedup: a concept and a `CODE_SYMBOL` with the same string don't merge.
- Idempotency: re-running both workers is a no-op.

---

## chunkshop — no change required

chunkshop already emits per-symbol chunks, embeddings, `fqn`, and `callees`. Neither
capability needs a chunkshop change. (Two *future, out-of-scope* ideas noted for the
record: chunkshop exposing parsed edges so the resolver can skip re-parsing; and an
fp32 emit option — the latter is a bento/embedder-alignment matter, not ours.)

---

## Downstream contract for the bento agent (NOT pg-raggraph work)

So the other agent knows the interface these capabilities expose:

- **To use Capability 1 (reuse vectors for code-aware):** send code-aware chunks as
  `pre_chunked` (chunks + vectors + `fqn`/`callees`/`language`/`source_path` metadata)
  and keep `defer_extraction=True`. pg-raggraph will reuse the vectors *and* still
  build the code graph. **Activation is entirely bento's call** — gated by bento's
  `BENTO_INGEST_REUSE_VECTORS` flag and its C1 embedder-parity gate (`#875`), which
  today refuses reuse while the cell is int8 and the proxy fp32 (the `#872` decision).
  pg-raggraph stays agnostic to all of that.
- **To use Capability 2 (concept layer):** set the pg-raggraph config flag per KB
  (off by default) and surface the extra deferred backlog in bento's existing
  `backfill-status`.
- pg-raggraph does **not** know the string `"code-aware"`; it reasons about code
  *language* + `defer_extraction` + the concept flag. Bento maps its kb_model to these.

---

## Risks (pg-raggraph-scoped)

| Risk | Mitigation |
|------|------------|
| Capability 1 silently breaks the code graph for some `pre_chunked` shape | Loud-fail on missing stage fields; parity test; default path unchanged |
| Concept LLM extraction pollutes the clean structural graph | Flag off by default; distinct `entity_type`; dedup on `(name, entity_type)` |
| LLM re-emits call-like relations already structural | Accept minor overlap; structural edges authoritative; dedupe on `(src,dst,rel_type)` |
| Two deferred workers race on `graph_status` | Single terminal transition gated on both complete; idempotent writes |

---

## Validation

- **Capability 1:** prove edge-set parity (reused vs self-chunked) and that staging
  fires on the `pre_chunked` code path. Library-level; can be done with fixtures here.
- **Capability 2 (hypothesis — "concepts help code retrieval"):** needs a code-KB eval
  on real data; that data/harness likely lives bento-side, so **coordinate the eval**
  rather than asserting the lift. Ship the capability off-by-default until measured.

---

## Open questions (pg-raggraph-scoped)

1. **Vendoring:** how do changes here reach `bento/backend/tools/pg-raggraph` (subtree / pinned version / copy)? Affects release sequencing for the bento agent.
2. **Stage fields on `pre_chunked`:** confirm `language`/`source_path` are reliably present in the upstream chunk metadata, or define the fallback precisely.
3. **graph_status with two workers:** can the current state machine express "ready only when both deferred workers done"? If not, scope the gate.
4. **Concept prompt:** new code-concept prompt vs. reuse/extend `devmem`'s dev prompt.
5. **Config surface:** final name/shape of the concept-layer switch (`PGRGConfig` field vs. per-ingest param) so bento can set it cleanly.
