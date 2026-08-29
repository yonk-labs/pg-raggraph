"""Integration tests for trgm-indexable fuzzy binds (perf fix).

The fuzzy anchor bind and the resolution fuzzy match used
``WHERE similarity(name, x) > threshold`` — that SQL form cannot use the
trgm GIN index ``idx_entity_name_trgm`` and seq-scanned an 11.5K-entity
namespace at 31.8ms p50 (benchmarks/age-bakeoff/cap-gold-v1/RESULTS.md,
engine-isolated addendum). The fix gates on ``name % x`` (index-eligible;
compares against ``pg_trgm.similarity_threshold``, pinned per call via a
transaction-local ``set_config``) while keeping the strict ``similarity() >``
gate so results and scores stay byte-equivalent.

Covered here:

1. Result-set + score equivalence between the old (seq-scan) and new
   (indexable) forms — for ``find_entities`` and for the resolution fuzzy
   query — including thresholds BELOW the 0.3 GUC default, which only pass
   if the per-call threshold pinning actually reaches the query's connection.
2. EXPLAIN (FORMAT JSON) on the new ``find_entities`` SQL at >1000 entities
   shows a Bitmap Index Scan on ``idx_entity_name_trgm`` (and proves the old
   form cannot touch that index).
"""

from __future__ import annotations

import json

import pytest

from pg_raggraph.graph_join import build_find_entities_sql, find_entities

pytestmark = pytest.mark.integration

NS = "test_trgm_binds"

# Names chosen for their measured trgm similarity to the probes below —
# exact, high, mid, and (0.2, 0.3) band (below the 0.3 GUC default), plus
# non-matches. The (0.2, 0.3) band is guard-asserted in the tests.
SEED_NAMES = [
    "PostgreSQL",  # exact vs probe "PostgreSQL"
    "PostgreSQL 16",  # ~0.79
    "Postgres",  # ~0.67
    "PostgreSQL HA Cluster",  # ~0.50
    "Postgres Operator",  # ~0.38
    "PostGIS",  # ~0.36
    "The Postgres Query Planner",  # ~0.28  (below 0.3 GUC default)
    "Postgres Kubernetes Operator",  # ~0.26
    "Postgres WAL Archiving Setup",  # ~0.25
    "Postgres High Availability Guide",  # ~0.22
    "PostGIS Spatial Extension",  # ~0.16  (below any tested threshold)
    "pgvector",  # ~0.05
    "SQL Server",  # ~0.11
    "Chesapeake Bay Retriever",  # ~0.275 vs probe "Lake Chesapeake Marina Dock"
    "Maria Ashby",  # ~0.67 vs probe "Maria Ashbee"
]

# The pre-fix find_entities SQL (fuzzy, untyped), verbatim: the similarity()
# WHERE gate forces a seq scan but defines the reference semantics.
OLD_FIND_SQL = """
WITH exact AS (
    SELECT id, name, entity_type, description,
           1.0::double precision AS score, 'exact' AS match_type
    FROM entities
    WHERE namespace = %(namespace)s AND name = %(name)s
),
fuzzy AS (
    SELECT id, name, entity_type, description,
           similarity(name, %(name)s)::double precision AS score, 'trgm' AS match_type
    FROM entities
    WHERE namespace = %(namespace)s AND name <> %(name)s
      AND similarity(name, %(name)s) > %(min_score)s
    ORDER BY score DESC
    LIMIT %(limit)s
)
SELECT * FROM exact
UNION ALL
SELECT * FROM fuzzy
ORDER BY score DESC, name
LIMIT %(limit)s
"""

# The pre-fix resolution fuzzy-match query, verbatim (resolution.py).
OLD_RES_SQL = """SELECT id, name, description,
          similarity(name, %(name)s) AS trgm_score,
          1 - (embedding <=> %(embedding)s::vector) AS vec_score,
          (%(trgm_w)s * similarity(name, %(name)s) +
           %(vec_w)s * (1 - (embedding <=> %(embedding)s::vector))) AS combined
   FROM entities
   WHERE namespace = %(namespace)s
     AND name != %(name)s
     AND similarity(name, %(name)s) > %(min_trgm)s
   ORDER BY combined DESC
   LIMIT 1"""

# The post-fix form of the same query (mirrors resolution.resolve_entity).
NEW_RES_SQL = """SELECT id, name, description,
          similarity(name, %(name)s) AS trgm_score,
          1 - (embedding <=> %(embedding)s::vector) AS vec_score,
          (%(trgm_w)s * similarity(name, %(name)s) +
           %(vec_w)s * (1 - (embedding <=> %(embedding)s::vector))) AS combined
   FROM entities
   WHERE namespace = %(namespace)s
     AND name != %(name)s
     AND name %% %(name)s
     AND similarity(name, %(name)s) > %(min_trgm)s
   ORDER BY combined DESC
   LIMIT 1"""


@pytest.fixture
async def seeded(db, config):
    """Seed NS with the banded names (all with embeddings) and clean up."""
    await db.execute("DELETE FROM entities WHERE namespace = %s", (NS,))
    dim = config.embedding_dim
    for i, name in enumerate(SEED_NAMES):
        # Distinct embeddings so combined scores never tie on LIMIT 1.
        emb = [0.5 + (i + 1) * 0.001] * dim
        await db.execute(
            "INSERT INTO entities (namespace, name, entity_type, description, embedding) "
            "VALUES (%s, %s, %s, %s, %s)",
            (NS, name, "technology", f"seed entity {i}", emb),
        )
    yield db
    await db.execute("DELETE FROM entities WHERE namespace = %s", (NS,))


async def _band_guard(db, probe: str, lo: float, hi: float) -> None:
    """Assert the seed really has a row with lo < similarity(name, probe) < hi."""
    row = await db.fetch_one(
        "SELECT count(*) AS n FROM entities WHERE namespace = %(ns)s "
        "AND similarity(name, %(probe)s) > %(lo)s AND similarity(name, %(probe)s) < %(hi)s",
        {"ns": NS, "probe": probe, "lo": lo, "hi": hi},
    )
    assert row["n"] > 0, f"seed data lost its ({lo}, {hi}) similarity band for {probe!r}"


async def test_find_entities_equivalent_to_seq_scan_form(seeded, db, config):
    """New indexable bind returns identical rows AND scores to the old form.

    min_score=0.2 is the load-bearing case: it sits below the 0.3
    pg_trgm.similarity_threshold server default, so it only passes if the
    per-call set_config actually reaches the connection running the query.
    """
    await _band_guard(db, "PostgreSQL", 0.2, 0.3)
    for probe in ("PostgreSQL", "Maria Ashbee", "Zzyzx Quandary"):
        for min_score in (0.2, 0.3, 0.45):
            old_rows = await db.fetch_all(
                OLD_FIND_SQL,
                {"namespace": NS, "name": probe, "min_score": min_score, "limit": 50},
            )
            old = [
                (
                    r["id"],
                    r["name"],
                    r["entity_type"],
                    r["description"] or "",
                    float(r["score"]),
                    r["match_type"],
                )
                for r in old_rows
            ]
            matches = await find_entities(
                db, config, probe, fuzzy=True, namespace=NS, limit=50, min_score=min_score
            )
            new = [
                (m.id, m.name, m.entity_type, m.description, m.score, m.match_type)
                for m in matches
            ]
            assert new == old, f"divergence for probe={probe!r} min_score={min_score}"


async def test_resolution_fuzzy_equivalent_old_vs_new(seeded, db, config):
    """Resolution fuzzy query: old vs new form agree on row and all scores.

    Runs the new form both on a pooled connection (Database.fetch_one, the
    resolve_entity_lookup context) and inside a Transaction (the
    resolve_entity ingest context) — set_local must pin the threshold on the
    query's own connection in both.
    """
    # 'Lake Chesapeake Marina Dock' matches ONLY 'Chesapeake Bay Retriever'
    # at ~0.275 — below the 0.3 GUC default. If threshold pinning is broken,
    # the new form returns no row at min_trgm=0.2 while the old form does.
    await _band_guard(db, "Lake Chesapeake Marina Dock", 0.2, 0.3)
    row = await db.fetch_one(
        "SELECT max(similarity(name, %(probe)s)) AS mx FROM entities WHERE namespace = %(ns)s",
        {"probe": "Lake Chesapeake Marina Dock", "ns": NS},
    )
    assert float(row["mx"]) < 0.3, "probe must have no match at the GUC default"

    emb = [0.5] * config.embedding_dim
    for probe, min_trgm in (
        ("Lake Chesapeake Marina Dock", 0.2),
        ("PostgreSQL 15", 0.3),
        ("Postgres", 0.3),
        ("Zzyzx Quandary", 0.3),
    ):
        params = {
            "name": probe,
            "embedding": emb,
            "namespace": NS,
            "trgm_w": config.trgm_weight,
            "vec_w": config.vec_weight,
            "min_trgm": min_trgm,
        }
        set_local = {"pg_trgm.similarity_threshold": str(min_trgm)}
        old = await db.fetch_one(OLD_RES_SQL, params)
        new_pooled = await db.fetch_one(NEW_RES_SQL, params, set_local=set_local)
        async with db.transaction() as tx:
            new_tx = await tx.fetch_one(NEW_RES_SQL, params, set_local=set_local)
        assert new_pooled == old, f"pooled divergence for probe={probe!r} min_trgm={min_trgm}"
        assert new_tx == old, f"transaction divergence for probe={probe!r} min_trgm={min_trgm}"
        if probe == "Lake Chesapeake Marina Dock":
            assert old is not None and old["name"] == "Chesapeake Bay Retriever"


def _index_scans(node: dict, index_name: str) -> list[dict]:
    found = []
    if node.get("Index Name") == index_name:
        found.append(node)
    for child in node.get("Plans", []):
        found.extend(_index_scans(child, index_name))
    return found


async def _explain(db, sql: str, params: dict, set_local: dict | None = None) -> dict:
    rows = await db.fetch_all("EXPLAIN (FORMAT JSON) " + sql, params, set_local=set_local)
    plan = rows[0]["QUERY PLAN"]
    if isinstance(plan, str):
        plan = json.loads(plan)
    return plan[0]["Plan"]


async def test_find_entities_uses_trgm_index_at_scale(seeded, db, config):
    """At >1000 entities the new fuzzy bind is a Bitmap Index Scan on
    idx_entity_name_trgm; the old similarity() gate cannot touch that index.

    11,500 fillers reproduce the namespace size of the measured 31.8ms p50
    defect (cap-gold-v1 addendum) — also comfortably past the point where
    the planner prefers the GIN bitmap over a seq scan.
    """
    await db.execute(
        "INSERT INTO entities (namespace, name, entity_type) "
        "SELECT %s, 'filler entity ' || g, 'filler' FROM generate_series(1, 11500) g",
        (NS,),
    )
    # The bulk insert lands in the GIN fastupdate pending list, which inflates
    # the index's cost estimate until autovacuum merges it — flipping the
    # planner to a seq scan nondeterministically. Merge it explicitly so the
    # plan reflects steady state (what a real namespace looks like).
    await db.execute("SELECT gin_clean_pending_list('idx_entity_name_trgm')")
    await db.execute("ANALYZE entities")

    params = {"namespace": NS, "name": "PostgreSQL 15", "min_score": 0.3, "limit": 5}
    new_sql = build_find_entities_sql(fuzzy=True, typed=False)
    new_plan = await _explain(
        db, new_sql, params, set_local={"pg_trgm.similarity_threshold": "0.3"}
    )
    trgm_scans = _index_scans(new_plan, "idx_entity_name_trgm")
    assert trgm_scans, f"no idx_entity_name_trgm scan in new plan: {json.dumps(new_plan)[:2000]}"
    assert any(n.get("Node Type") == "Bitmap Index Scan" for n in trgm_scans), (
        f"idx_entity_name_trgm present but not as Bitmap Index Scan: {trgm_scans}"
    )

    old_plan = await _explain(db, OLD_FIND_SQL, params)
    assert _index_scans(old_plan, "idx_entity_name_trgm") == [], (
        "old similarity() gate unexpectedly used the trgm index — "
        "the baseline for this fix no longer holds"
    )

    # And the indexed form still returns the right answer at scale.
    matches = await find_entities(db, config, "PostgreSQL 15", fuzzy=True, namespace=NS, limit=5)
    assert matches and matches[0].name == "PostgreSQL"  # 0.786 > 'PostgreSQL 16' at 0.75
    assert matches[0].match_type == "trgm"
