-- Per-document source_type label (issue #38).
--
-- Downstream consumers rendering multi-source responses need each retrieved
-- chunk identifiable by origin (citation chips: which source produced this
-- result). Stamped at ingest via ingest_records(source_type=...) or a
-- per-record "source_type" key; projected through every retrieval strategy
-- onto ChunkResult.source_type. Nullable so pre-existing documents keep
-- working. Partial index because the column is a projection today, but a
-- "filter by source_type" path is plausible and the index is cheap while
-- the column is sparse.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS source_type VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_doc_ns_source_type
    ON documents (namespace, source_type)
    WHERE source_type IS NOT NULL;
