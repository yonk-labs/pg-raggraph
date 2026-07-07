-- Vector-only baseline — the accelerator's Stage-1 vector query, verbatim
-- structure from get_vector_semantic_graphrag_optimized's `vector` CTE
-- (setup_postgres_legal_seeddata.py) including their court filter
-- (9029 = Washington Supreme Court; all in-corpus gold cases are court 9029).
-- This is the "40 percent recall" reference arm in Microsoft's write-up.
SELECT id,
       data#>>'{name_abbreviation}' AS case_name,
       RANK() OVER (ORDER BY description_vector <=> %(qvec)s::vector) AS vector_rank
FROM cases_updated
WHERE (data#>>'{court, id}')::integer IN (9029)
ORDER BY description_vector <=> %(qvec)s::vector
LIMIT %(k)s;
