-- Content-hash embedding cache (F7).
--
-- Global by design: identical embedded text maps to the same vector across
-- namespaces. The table stores only the SHA-256 of the text and the vector,
-- not tenant/source metadata or plaintext.

CREATE TABLE IF NOT EXISTS embedding_cache (
    cache_namespace TEXT NOT NULL,
    text_sha256 TEXT NOT NULL,
    embedding vector({dim}) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (cache_namespace, text_sha256)
);

REVOKE ALL ON embedding_cache FROM pgrg_app;

CREATE OR REPLACE FUNCTION pgrg_embedding_cache_get(cache_ns TEXT, keys TEXT[])
RETURNS TABLE(text_sha256 TEXT, embedding vector)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT ec.text_sha256, ec.embedding
    FROM embedding_cache ec
    WHERE ec.cache_namespace = cache_ns
      AND ec.text_sha256 = ANY(keys);
$$;

CREATE OR REPLACE FUNCTION pgrg_embedding_cache_put(cache_ns TEXT, key TEXT, value vector)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    INSERT INTO embedding_cache (cache_namespace, text_sha256, embedding)
    VALUES (cache_ns, key, value)
    ON CONFLICT (cache_namespace, text_sha256) DO NOTHING;
$$;

REVOKE ALL ON FUNCTION pgrg_embedding_cache_get(TEXT, TEXT[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION pgrg_embedding_cache_put(TEXT, TEXT, vector) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pgrg_embedding_cache_get(TEXT, TEXT[]) TO pgrg_app;
GRANT EXECUTE ON FUNCTION pgrg_embedding_cache_put(TEXT, TEXT, vector) TO pgrg_app;
