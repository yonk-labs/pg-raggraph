# Retrieval Profile Ladder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the benchmark-proven context-packing recipes into a first-class `retrieval_profile` feature: a 7-rung cheap-to-accurate ladder, per-namespace persisted defaults, per-call overrides, API/server/MCP wiring, and benchmark harness reuse of the same library packer.

**Mission Brief:** `skill-output/mission-brief/Mission-Brief-retrieval-profile-ladder.md`

**Phase F calibration note:** LoCoMo validation is complete in `.matrix-runs/deep-f-locomo-validation-full/`. It did **not** rescue `chunk_summary_facts` or plain `per_doc_summary_facts@N` as defaults. It **did** show conversational data benefits from stacked summary+raw context: `doc_summary_facts_plus_chunks` led LoCoMo at 90.0% pass / 0.911 score, but that strategy is only calibrated on LoCoMo in the current D/E/F set. The default ladder in `benchmarks/matrix/profile_calibration.json` is now `f-informed-1`, keeps `profile="raw"` as a separate escape hatch, and uses a monotonic aggregate ladder:

| rung | name | strategy | aggregate tokens | aggregate accuracy |
|---:|---|---|---:|---:|
| 0 | cheap | `doc_summary_facts@3` | 2110 | 0.6111 |
| 1 | cheap_plus | `doc_summary_facts@5` | 2375 | 0.6333 |
| 2 | lean | `full_selected_docs@3` | 4304 | 0.6889 |
| 3 | balanced | `doc_and_chunk_summary_toc_facts_plus_top5` | 6672 | 0.7056 |
| 4 | rich | `full_selected_docs@5` | 7304 | 0.7333 |
| 5 | stacked | `per_doc5_chunksum_top5` | 10495 | 0.7556 |
| 6 | accurate | `full_selected_docs@10` | 13878 | 0.8000 |

**Latency prerequisite:** Retrieval latency is not a packing problem. Profiling shows the graph hydration query dominates hybrid/local/global latency. `entity_chunks` has no `chunk_id` index for `WHERE chunk_id = ANY(...)`, and `RELATIONSHIPS_FOR_ENTITIES` can scan/sort large `entities`/`relationships` ranges before returning 20 rows. In the bench DB, adding `idx_entity_chunks_chunk` plus rewriting relationship hydration to seed relationship IDs first dropped the LoCoMo sample relationship query from ~180 ms to ~2 ms in `EXPLAIN ANALYZE`.

---

## File Structure

**New files:**
- `src/pg_raggraph/context.py` — profile/rung resolution and context packing.
- `src/pg_raggraph/profiles.py` — ladder definitions, calibration loading, profile DTO helpers.
- `src/pg_raggraph/sql/migrations/007_graph_hydration_indexes.sql` — graph hydration index.
- `src/pg_raggraph/sql/migrations/008_namespace_settings_profiles.sql` — `namespace_settings` table.
- `tests/unit/test_profiles.py`
- `tests/unit/test_context_packer.py`
- `tests/integration/test_namespace_profiles.py`
- `tests/integration/test_profile_query_paths.py`
- `tests/integration/test_server_profiles.py`

**Modified files:**
- `src/pg_raggraph/config.py`
- `src/pg_raggraph/__init__.py`
- `src/pg_raggraph/retrieval.py`
- `src/pg_raggraph/server.py`
- `src/pg_raggraph/mcp_server.py`
- `benchmarks/matrix/run.py`
- `benchmarks/matrix/analyze.py`
- `benchmarks/matrix/profile_calibration.json`
- relevant docs/cookbook pages

---

## Task 0: Fix Graph Hydration Latency (Prerequisite)

**SC coverage:** protects the latency assumptions behind SC-006/SC-007 and keeps profile selection from hiding a retrieval bottleneck.

- [x] Add migration `007_graph_hydration_indexes.sql` with `CREATE INDEX IF NOT EXISTS idx_entity_chunks_chunk ON entity_chunks(chunk_id);`.
- [x] Rewrite `RELATIONSHIPS_FOR_ENTITIES` in `src/pg_raggraph/retrieval.py` to:
  - materialize seed entity IDs from `entity_chunks WHERE chunk_id = ANY(...)`;
  - collect/limit relationship IDs via `idx_rel_src`/`idx_rel_dst`;
  - only then join `relationships` and `entities` for names/descriptions.
- [ ] Add a scale/integration test that asserts the relationship hydration query returns the same shape and does not perform a full `entity_chunks` scan on a populated fixture.
- [x] Re-run the local latency profiler against LoCoMo and record before/after p50.

## Task 1: Profile DTOs and Ladder Loading

**SC coverage:** SC-001, SC-002, SC-006.

- [x] Create `src/pg_raggraph/profiles.py` with `ProfileRung`, `ProfileCalibration`, and `ProfileSpec` helpers.
- [x] Load `benchmarks/matrix/profile_calibration.json` when available; fall back to packaged defaults when absent.
- [x] Implement resolution for named tiers (`cheap`, `balanced`, `accurate`), float slider, integer rung, string float, and invalid-value errors.
- [x] Keep `raw` as a special escape hatch outside the ordered rung list.
- [x] Unit-test rung count, aggregate monotonic token/accuracy order, raw escape hatch, fallback loading, and all profile resolution forms.

## Task 2: Library Context Packer

**SC coverage:** SC-003, SC-004, SC-005.

- [x] Create `src/pg_raggraph/context.py` and move calibrated context assembly into library code.
- [x] Support the calibrated strategies: doc summaries, full selected docs, stacked summaries+top raw chunks, and `raw`.
- [x] Make the most accurate/stacked rungs include summary/fact sections plus verbatim raw text where the strategy requires it.
- [x] Unit-test `raw` byte-for-token equivalence with legacy chunks.
- [x] Unit-test that the balanced/stacked outputs include both summary markers and raw chunk text.

## Task 3: Harness Uses Library Packer

**SC coverage:** SC-004, SC-009.

- [ ] Replace `benchmarks/matrix/run.py::_assemble_strategy` with an import from `pg_raggraph.context`.
- [ ] Preserve all historical strategy names used by Phases C-F.
- [ ] Add a shared fixture test proving harness and library packer produce identical context.
- [ ] Keep `analyze.py --emit-calibration` aligned with the `f-informed-1` ladder and raw escape hatch metadata.

## Task 4: Config and Query API

**SC coverage:** SC-002, SC-003, SC-010.

- [x] Add `retrieval_profile` / global default config fields to `PGRGConfig`.
- [x] Add `profile=` to `GraphRAG.query()` and `GraphRAG.ask()`.
- [ ] Implement precedence for explicit query knobs vs profile-derived knobs and document conflict behavior.
- [x] Ensure no-profile defaults to `balanced`.
- [x] Ensure `profile="raw"` reproduces legacy raw chunk context at the calibrated escape-hatch `top_k`.

## Task 5: Namespace Settings Persistence

**SC coverage:** SC-011.

- [x] Add `namespace_settings(namespace primary key, retrieval_profile jsonb/text, updated_at)` via migration.
- [x] Add library APIs to set/get namespace profile defaults.
- [x] Implement resolution precedence: per-call profile > namespace setting > global default.
- [ ] Integration-test persistence across reconnect.

## Task 6: Introspection API

**SC coverage:** SC-006, SC-007.

- [x] Add `GraphRAG.profiles()` returning rung metadata, calibration estimates, and raw escape hatch metadata.
- [x] Add server `GET /profiles`.
- [x] Add server query/ask profile input.
- [x] Add MCP `profile` argument to `pgrg_query` and `pgrg_ask`.
- [ ] Add integration tests for server and MCP argument threading.

## Task 7: Documentation and Migration Notes

**SC coverage:** SC-003, SC-010, SC-011.

- [ ] Document one-corpus-type-per-namespace guidance.
- [ ] Document cheap/balanced/accurate, slider, integer rung, advanced overrides, and `raw`.
- [ ] Document per-namespace defaults and precedence.
- [ ] Document migration impact: no-profile now means balanced; `raw` is the legacy escape hatch.

## Task 8: Final Verification

**SC coverage:** DC-FINAL.

- [ ] Run unit tests for profiles/context.
- [ ] Run integration tests for namespace settings, query/ask, server, and MCP.
- [ ] Run a small matrix fixture confirming the harness imports the library packer.
- [ ] Re-run `analyze.py --emit-calibration` and confirm all 7 rungs have populated estimates.
- [ ] Re-read the mission brief and produce a SC-001 through SC-011 evidence table.
