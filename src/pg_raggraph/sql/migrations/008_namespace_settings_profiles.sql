CREATE TABLE IF NOT EXISTS namespace_settings (
    namespace TEXT PRIMARY KEY,
    retrieval_profile JSONB,
    updated_at TIMESTAMPTZ DEFAULT now()
);
