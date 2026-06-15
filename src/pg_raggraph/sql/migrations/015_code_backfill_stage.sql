-- Durable staging for out-of-band code-graph backfill (#81).
--
-- When ingest_records(..., defer_extraction=True) runs over code docs
-- (chunk_strategy="chunkshop:symbol_aware"), the corpus code-graph resolver is
-- skipped so the call returns fast. The raw file content is persisted here so a
-- later `pgrg backfill-code-graph` run can re-parse it, rebuild the cross-file
-- symbol index, and write the CALLS/INHERITS/IMPLEMENTS edges.
--
-- LOGGED (a normal table), UNLIKE code_calls_stage: this content must survive
-- BETWEEN the deferred ingest and a later backfill run — possibly across a
-- crash/restart. An UNLOGGED table is truncated on crash recovery, which would
-- silently lose the content. The table doubles as the code-graph work queue,
-- keyed independently of documents.graph_status (which `pgrg extract` owns), so
-- entity backfill and code-graph backfill never contend.
CREATE TABLE IF NOT EXISTS code_backfill_stage (
    document_id BIGINT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    namespace   TEXT NOT NULL,
    content     TEXT NOT NULL,
    language    TEXT,
    source_path TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_code_backfill_stage_ns
    ON code_backfill_stage (namespace);
