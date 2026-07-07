-- Microsoft HorizonDB "Pattern 1: Authority boosting" — VERBATIM STRUCTURE.
-- Source: https://learn.microsoft.com/en-us/azure/horizondb/ai/graph-rag
--   (ms.date 2026-06-02, section "Pattern 1: Authority boosting")
--
-- Local adaptations, and nothing else:
--   * documents            -> cases_updated  (their accelerator's table name)
--   * id/content           -> id (TEXT), data#>>'{name_abbreviation}'
--   * doc_id::text::int    -> trim(both '"' from doc_id::text)  — our case ids
--                             are TEXT; the doc's ::int cast assumed int ids.
--   * query_embedding      -> %(qvec)s::vector parameter (fastembed, 384-dim;
--                             the doc leaves the embedding source abstract)
--   * graph name           -> 'case_graph', edge label REF (the accelerator's
--                             graph; the doc's snippet says citation_graph/CITES)
--   * LIMIT 10             -> LIMIT %(k)s so recall@k can sweep k
--
-- One statement: ag_catalog.cypher() CTE + pgvector <=> CTE + RRF fusion.
WITH vector_hits AS (
    SELECT id, data#>>'{name_abbreviation}' AS content,
           description_vector <=> %(qvec)s::vector AS distance
    FROM cases_updated
    ORDER BY description_vector <=> %(qvec)s::vector
    LIMIT 60
),
citation_authority AS (
    SELECT trim(both '"' from g.doc_id::text) AS doc_id, count(*) AS cite_count
    FROM ag_catalog.cypher('case_graph', $$
        MATCH ()-[:REF]->(target)
        RETURN target.case_id
    $$) AS g(doc_id agtype)
    GROUP BY trim(both '"' from g.doc_id::text)
)
SELECT v.id, v.content,
    1.0 / (60 + ROW_NUMBER() OVER (ORDER BY v.distance)) +
    1.0 / (60 + ROW_NUMBER() OVER (ORDER BY COALESCE(a.cite_count, 0) DESC)) AS rrf_score
FROM vector_hits v
LEFT JOIN citation_authority a ON v.id = a.doc_id
ORDER BY rrf_score DESC
LIMIT %(k)s;
