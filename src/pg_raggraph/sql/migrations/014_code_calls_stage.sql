-- Spill table for cross-file code-graph resolution (#76 OOM fix, v0.5.0a13).
--
-- The cross-file resolver (chunkshop_bridge.CorpusCodeGraph) accumulates one
-- call site per call across the whole ingest. Holding them all in memory is
-- O(call-sites) and OOMs on large repos (measured ~427 B/call → ~3.6 GB at
-- 100k files). Instead we SPILL call sites here during phase 1 (per file) and
-- stream them back in bounded batches during phase-2 resolution, so resolver
-- memory stays O(batch + symbol index) instead of O(corpus call sites).
--
-- UNLOGGED on purpose: rows are transient scratch — written, drained, then
-- deleted within a single ingest_records() call. Surviving a crash has no
-- value, and skipping WAL makes the high-volume spill cheap. `run_id` isolates
-- concurrent ingests sharing a namespace; the index serves the keyset drain
-- (WHERE namespace = ? AND run_id = ? AND id > ? ORDER BY id).
CREATE UNLOGGED TABLE IF NOT EXISTS code_calls_stage (
    id         BIGSERIAL PRIMARY KEY,
    namespace  TEXT NOT NULL,
    run_id     TEXT NOT NULL,
    payload    JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_code_calls_stage_run
    ON code_calls_stage (namespace, run_id, id);
