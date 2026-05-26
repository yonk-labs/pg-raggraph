-- Online embedding-model migration state (single active migration at a time).
CREATE TABLE IF NOT EXISTS embedding_migration (
    id              BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
    target_model    TEXT NOT NULL,
    target_dim      INT  NOT NULL,
    phase           TEXT NOT NULL,          -- prepared|backfilled|indexed|cutover
    backfill_source TEXT NOT NULL DEFAULT 'reembed',  -- reembed|chunkshop_sink
    started_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
