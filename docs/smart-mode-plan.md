# Smart Mode + Dev KB — Implementation Plan

## Goal

Add a better retrieval architecture to pg-raggraph:
- **`naive+boost`** mode: vector+BM25 with cheap 1-hop graph re-ranking
- **`smart`** mode: confidence-triggered routing (fast path for easy questions, graph expand for hard ones)
- **`pgrg devmem`** subcommand: dev-KB-tuned defaults on top of the above

Each chunk is self-contained: takes 15-45 min, ends with passing tests, leaves the codebase working.

---

## Phase 1: Foundation (plumbing only, no behavior change)

### Chunk 1.1 — Add confidence signals to QueryResult
**Goal:** Expose the top_score, avg_score, and confidence level from retrieval.

**Files:**
- `src/pg_raggraph/models.py` — add `top_score`, `avg_score`, `confidence` to `QueryResult`
- `src/pg_raggraph/retrieval.py` — populate them from the ranked chunks

**Test:** Unit test that `QueryResult` has the new fields and they're computed correctly from a list of chunks.

**Effort:** 20 min

---

### Chunk 1.2 — Add routing config knobs
**Goal:** New config fields for threshold-based routing.

**Files:**
- `src/pg_raggraph/config.py` — add `boost_confidence_threshold: float = 0.7`, `expand_confidence_threshold: float = 0.4`, `enable_graph_boost: bool = True`

**Test:** Unit test that env vars override defaults.

**Effort:** 10 min

---

### Chunk 1.3 — Add `smart` and `naive_boost` to QueryMode enum
**Goal:** Register the new modes without implementing them yet. Stubs raise NotImplementedError.

**Files:**
- `src/pg_raggraph/retrieval.py` — expand `QueryMode = Literal["local", "global", "hybrid", "naive", "naive_boost", "smart"]`

**Test:** Unit test that passing `mode="smart"` doesn't fail type validation (raises NotImplementedError instead).

**Effort:** 5 min

---

## Phase 2: Graph Boost (the key technique)

### Chunk 2.1 — Write the 1-hop boost SQL
**Goal:** A single SQL query that takes a list of seed chunk IDs and returns a boost multiplier for each.

**Files:**
- `src/pg_raggraph/sql/graph_boost.sql` — the query template

**SQL skeleton:**
```sql
WITH seed_entities AS (
  SELECT DISTINCT entity_id
  FROM entity_chunks WHERE chunk_id = ANY(%(chunk_ids)s)
),
neighbors AS (
  SELECT DISTINCT
    CASE WHEN r.src_id IN (SELECT entity_id FROM seed_entities)
         THEN r.dst_id ELSE r.src_id END AS nid
  FROM relationships r
  WHERE r.src_id IN (SELECT entity_id FROM seed_entities)
     OR r.dst_id IN (SELECT entity_id FROM seed_entities)
)
SELECT c.id,
       COUNT(DISTINCT ec.entity_id) FILTER (WHERE ec.entity_id IN (SELECT nid FROM neighbors))
         AS neighbor_hits
FROM chunks c
LEFT JOIN entity_chunks ec ON ec.chunk_id = c.id
WHERE c.id = ANY(%(chunk_ids)s)
GROUP BY c.id;
```

**Test:** Integration test — insert a small graph, get boost hits for known chunks, verify.

**Effort:** 30 min

---

### Chunk 2.2 — Implement `_graph_boost()` Python helper
**Goal:** Function that takes a QueryResult, runs the boost query, and re-ranks.

**Files:**
- `src/pg_raggraph/retrieval.py` — add `async def _graph_boost(result, db, boost_factor=1.2)`

**Logic:**
```python
async def _graph_boost(
    result: QueryResult, db, boost_factor: float = 1.2
) -> QueryResult:
    if not result.chunks:
        return result
    chunk_ids = [c.chunk_id for c in result.chunks]  # need to add chunk_id to ChunkResult
    boost_map = await db.fetch_all(BOOST_SQL, {"chunk_ids": chunk_ids})
    id_to_hits = {r["id"]: r["neighbor_hits"] for r in boost_map}
    for chunk in result.chunks:
        hits = id_to_hits.get(chunk.chunk_id, 0)
        if hits > 0:
            chunk.score *= boost_factor
    result.chunks.sort(key=lambda c: c.score, reverse=True)
    return result
```

**Prerequisite:** Add `chunk_id: int` to `ChunkResult` model (small schema change).

**Test:** Integration test — compare naive result vs naive+boost on a corpus where we know graph structure matters.

**Effort:** 45 min

---

### Chunk 2.3 — Wire up `naive_boost` mode
**Goal:** The `naive_boost` mode = naive + `_graph_boost()` applied.

**Files:**
- `src/pg_raggraph/retrieval.py` — in the mode dispatcher, if `mode == "naive_boost"`, run naive then apply `_graph_boost()`.

**Test:** Integration test using NTSB corpus (where we saw graph helps): expect `naive_boost` to score slightly better than pure `naive`.

**Effort:** 20 min

---

## Phase 3: Smart Routing

### Chunk 3.1 — Implement `smart` mode routing
**Goal:** Run naive, check confidence, escalate or boost as needed.

**Files:**
- `src/pg_raggraph/retrieval.py` — add `async def _smart_query()`

**Logic:**
```python
async def _smart_query(question, db, embedder, config, namespace):
    result = await _naive_query(question, db, embedder, config, namespace)
    top = result.top_score
    avg = result.avg_score

    # High confidence: ship naive
    if top >= config.boost_confidence_threshold:
        result.query_mode = "smart[naive]"
        return result

    # Low confidence: full graph expansion
    if top < config.expand_confidence_threshold:
        expanded = await _local_query(question, db, embedder, config, namespace)
        merged = _merge_results(result, expanded)
        merged.query_mode = "smart[expanded]"
        return merged

    # Medium confidence: graph boost
    boosted = await _graph_boost(result, db, config)
    boosted.query_mode = "smart[boosted]"
    return boosted
```

**Test:** Unit test with 3 mocked naive results (high/med/low confidence) — verify correct path taken.

**Effort:** 45 min

---

### Chunk 3.2 — Make `smart` the new default mode
**Goal:** `smart` replaces `hybrid` as the default for `GraphRAG.query()` and `pgrg query`.

**Files:**
- `src/pg_raggraph/__init__.py` — change default mode to `"smart"`
- `src/pg_raggraph/cli.py` — add `smart` to choices, default=smart
- `src/pg_raggraph/models.py` — default `query_mode` field

**Test:** Existing tests updated to expect `smart` as default. CLI test verifies `pgrg query "..."` runs in smart mode.

**Effort:** 20 min

---

### Chunk 3.3 — Expose smart mode metadata
**Goal:** Users can see which path smart mode took ("naive", "boosted", "expanded").

**Files:**
- CLI output includes the smart path chosen
- `QueryResult.query_mode` is set to e.g. `"smart[boosted]"`

**Test:** CLI test — query at different confidence levels, assert output mentions the path.

**Effort:** 15 min

---

## Phase 4: Benchmarks + Tuning

### Chunk 4.1 — Benchmark smart vs other modes
**Goal:** Run all 4 corpora with the new smart mode, compare to naive/local/global/hybrid.

**Files:**
- `benchmarks/run_all_benchmarks.py` — add smart mode to the modes list

**Expected outcome:** smart should match naive on easy questions, match hybrid on hard questions, with latency between them.

**Test:** Run the benchmark, commit results. Update `FINAL_RESULTS.md`.

**Effort:** 20 min

---

### Chunk 4.2 — Tune thresholds based on real data
**Goal:** Pick good default thresholds from the benchmark data.

**Files:**
- `src/pg_raggraph/config.py` — update defaults
- `docs/user-guide.md` — document tuning guidance

**Test:** Re-run benchmarks with tuned thresholds, confirm smart mode wins on average.

**Effort:** 20 min

---

## Phase 5: Dev KB Foundation (`devmem` subcommand)

### Chunk 5.1 — Dev-specific extraction prompt
**Goal:** A separate extraction prompt optimized for code/engineering docs.

**Files:**
- `src/pg_raggraph/extraction.py` — add `DEV_EXTRACTION_PROMPT` constant, pass via config

**Prompt focus:** extract `person`, `service`, `library`, `file`, `commit`, `incident`, `ticket`, `concept` entities. Relations like `OWNS`, `DEPENDS_ON`, `TOUCHED`, `CAUSED`, `REFERENCES`.

**Test:** Unit test — feed a sample PR description, verify it extracts the right entity types.

**Effort:** 30 min

---

### Chunk 5.2 — Add `extraction_prompt` config knob
**Goal:** Users can switch between default and dev prompts via config.

**Files:**
- `src/pg_raggraph/config.py` — `extraction_prompt: str = "default"` (default | dev | custom)
- `src/pg_raggraph/extraction.py` — pick prompt based on config

**Test:** Unit test — set `extraction_prompt="dev"`, verify the right prompt is used.

**Effort:** 15 min

---

### Chunk 5.3 — Code-aware chunker
**Goal:** When chunking Python/JS/TS files, split on function/class boundaries instead of headings.

**Files:**
- `src/pg_raggraph/chunking.py` — new `_split_by_code_structure()` helper
- Detect file type from extension, route to appropriate chunker

**Test:** Unit test — chunk a Python file with 3 functions, verify 3 chunks with function names in metadata.

**Effort:** 45 min

---

### Chunk 5.4 — Git metadata ingestion
**Goal:** When ingesting a Git repo, capture commit/author/date as chunk metadata.

**Files:**
- `src/pg_raggraph/chunking.py` — optional `git_blame` metadata per chunk
- New helper: `_get_git_info(file_path)` using `subprocess.run(["git", "log", "-1", ...])`

**Test:** Integration test — ingest a file from this repo, verify the chunk metadata has author + commit.

**Effort:** 30 min

---

### Chunk 5.5 — `pgrg devmem` CLI subcommand
**Goal:** New command group with dev-KB-tuned defaults.

**Files:**
- `src/pg_raggraph/cli.py` — add `@main.group()` for devmem
- Commands: `devmem init`, `devmem ingest`, `devmem ask`, `devmem status`
- Defaults: `extraction_prompt=dev`, `chunk_strategy=code-aware`, `namespace=devmem`

**Test:** CLI test — `pgrg devmem --help` shows the new commands.

**Effort:** 30 min

---

### Chunk 5.6 — Devmem ingest with smart defaults
**Goal:** `pgrg devmem ingest ./repo/` does the right thing automatically.

**Files:**
- `src/pg_raggraph/cli.py` — devmem ingest implementation
- Walks repo, applies code-aware chunking, uses dev prompt, captures Git metadata

**Test:** Integration test — ingest a small test repo, verify entity types include `file`, `commit`, etc.

**Effort:** 30 min

---

### Chunk 5.7 — Devmem ask with smart mode default
**Goal:** `pgrg devmem ask "who owns auth?"` defaults to smart mode with dev-tuned thresholds.

**Files:**
- `src/pg_raggraph/cli.py` — devmem ask implementation
- Pretty-prints chunks, entities, and the smart mode path taken

**Test:** End-to-end test — ingest sample repo, ask question, verify meaningful answer.

**Effort:** 20 min

---

## Phase 6: Polish

### Chunk 6.1 — Documentation update
**Goal:** User guide documents the new modes and devmem usage.

**Files:**
- `docs/user-guide.md` — new section on smart mode and query modes
- `docs/devmem-guide.md` — new doc for devmem subcommand

**Effort:** 30 min

---

### Chunk 6.2 — Update CLAUDE.md
**Goal:** Future Claude sessions know about the new architecture.

**Files:**
- `CLAUDE.md` — add smart mode, devmem, boost architecture

**Effort:** 10 min

---

### Chunk 6.3 — Demo script
**Goal:** A one-command demo showing smart mode in action.

**Files:**
- `benchmarks/demo_smart_mode.py` — ingest a sample dev corpus, run 5 queries showing different smart paths

**Test:** Running the script produces clear output showing when smart chose naive vs boost vs expand.

**Effort:** 30 min

---

## Summary

| Phase | Chunks | Total Effort |
|-------|--------|--------------|
| 1. Foundation | 3 | ~35 min |
| 2. Graph Boost | 3 | ~95 min |
| 3. Smart Routing | 3 | ~80 min |
| 4. Benchmarks | 2 | ~40 min |
| 5. Dev KB | 7 | ~200 min |
| 6. Polish | 3 | ~70 min |
| **Total** | **21 chunks** | **~8.5 hours** |

### Recommended order

Do Phases 1-4 first (~4 hours). That gives us the smart/boost architecture, working across all existing corpora. Stop there and re-benchmark — this alone is a significant improvement.

Then do Phase 5 (~3.5 hours) as a separate session when we're ready to build the devmem layer.

Phase 6 (~1 hour) at the very end.

### Acceptance criteria

After Phase 4:
- [ ] `naive_boost` and `smart` modes exist and pass tests
- [ ] `smart` is the new default for `query()` and CLI
- [ ] Cross-corpus benchmark shows smart ≥ naive on all corpora
- [ ] Smart latency is within 1.5x of naive on high-confidence queries
- [ ] Smart latency is within 1.2x of hybrid on low-confidence queries

After Phase 5:
- [ ] `pgrg devmem` subcommand with `init`, `ingest`, `ask`, `status`
- [ ] Code-aware chunking handles Python files correctly
- [ ] Git metadata captured on ingest
- [ ] Dev entity types extracted from sample codebase

After Phase 6:
- [ ] User guide updated
- [ ] Demo script works end-to-end
- [ ] CLAUDE.md reflects new architecture
