-- Background-extraction lifecycle on `documents`.
--
-- Adds the per-document status column used by the deferred-extraction queue
-- (see backfill.py and `pgrg extract`). Lifecycle is:
--   'pending'     -- chunks + embeddings stored, graph not yet extracted
--   'processing'  -- claimed by a worker (SELECT ... FOR UPDATE SKIP LOCKED)
--   'ready'       -- entities + relationships written
--   'failed'      -- extraction raised; graph_error holds the reason
--
-- Existing rows were extracted under the pre-feature synchronous default, so
-- they are correct to backfill as 'ready'. The NOT NULL DEFAULT 'ready'
-- handles both the existing-row backfill (no rewrite — defaults apply lazily
-- in PG 11+) and new rows that the caller doesn't explicitly mark.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS graph_status TEXT NOT NULL DEFAULT 'ready',
    ADD COLUMN IF NOT EXISTS graph_extracted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS graph_error TEXT;

-- Partial index over the queue working-set only. 'ready' is the steady state
-- and dominates row count; indexing it would bloat for no gain. Ordering by
-- created_at means the claim query (FIFO) can stop at LIMIT N.
CREATE INDEX IF NOT EXISTS idx_documents_graph_status_pending
    ON documents (namespace, created_at)
    WHERE graph_status = 'pending';
