-- Vector-only baseline — the accelerator's Stage-1 vector query
-- (structure from get_vector_semantic_graphrag_optimized's `vector` CTE),
-- carried over from horizondb-h2h/sql/vector_baseline.sql with ONE
-- preregistered adaptation (METHODOLOGY §3): the court_id = 9029 filter is
-- DROPPED — the cap-gold corpus is single-court (wash-2d = Washington
-- Supreme Court), so the filter is a no-op at best and misleading at worst.
SELECT id,
       data#>>'{name_abbreviation}' AS case_name,
       RANK() OVER (ORDER BY description_vector <=> %(qvec)s::vector) AS vector_rank
FROM cases_updated
ORDER BY description_vector <=> %(qvec)s::vector
LIMIT %(k)s;
