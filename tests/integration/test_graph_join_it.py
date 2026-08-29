"""Integration tests for typed traversal / dependent conjunctive joins (issue #95).

Builds the issue's exact join world synthetically (no LLM, no embeddings):

    person —LIVES_IN→ city
    person —CRAVES/likes→ food
    restaurant —LOCATED_IN→ city
    restaurant —SERVES→ food

and proves that ``graph_join`` returns exactly the satisfying restaurant(s)
with full provenance, that traversal is typed and directed, and that the
join SQL uses the relationship indexes at 10^4-edge scale.
"""

from __future__ import annotations

import json
import os

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.graph_join import build_join_sql, parse_bind_steps, parse_intersect_steps

pytestmark = pytest.mark.integration

TEST_DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NS = "test_graph_join_95"

# (name, entity_type, description)
ENTITIES = [
    ("Maria Ashby", "person", "Food-loving Portland local"),
    ("Devon Cole", "person", "Austin taco enthusiast"),
    ("Ida Frost", "person", "Portlander craving tacos"),
    ("Portland", "city", "City in Oregon"),
    ("Austin", "city", "City in Texas"),
    ("ramen", "food", "Noodle soup"),
    ("tacos", "food", "Folded tortillas"),
    ("pizza", "food", "Flatbread with toppings"),
    ("Noodle Haven", "restaurant", "Ramen shop in Portland"),
    ("Slice City", "restaurant", "Pizza place in Portland"),
    ("Ramen Bar ATX", "restaurant", "Ramen shop in Austin"),
    ("Taco Verde", "restaurant", "Taqueria in Austin"),
    ("Taco Norte", "restaurant", "Taqueria in Austin"),
]

# (src, rel_type, dst, provenance sentence). Rel types deliberately mix
# case ('likes') to prove case-insensitive matching.
RELS = [
    ("Maria Ashby", "LIVES_IN", "Portland", "Maria Ashby lives in Portland."),
    ("Maria Ashby", "CRAVES", "ramen", "Maria Ashby has been craving ramen."),
    ("Devon Cole", "LIVES_IN", "Austin", "Devon Cole lives in Austin."),
    ("Devon Cole", "likes", "tacos", "Devon Cole likes tacos."),
    ("Ida Frost", "LIVES_IN", "Portland", "Ida Frost lives in Portland."),
    ("Ida Frost", "CRAVES", "tacos", "Ida Frost craves tacos."),
    ("Noodle Haven", "LOCATED_IN", "Portland", "Noodle Haven is located in Portland."),
    ("Noodle Haven", "SERVES", "ramen", "Noodle Haven serves ramen."),
    ("Slice City", "LOCATED_IN", "Portland", "Slice City is located in Portland."),
    ("Slice City", "SERVES", "pizza", "Slice City serves pizza."),
    ("Ramen Bar ATX", "LOCATED_IN", "Austin", "Ramen Bar ATX is located in Austin."),
    ("Ramen Bar ATX", "SERVES", "ramen", "Ramen Bar ATX serves ramen."),
    ("Taco Verde", "LOCATED_IN", "Austin", "Taco Verde is located in Austin."),
    ("Taco Verde", "SERVES", "tacos", "Taco Verde serves tacos."),
    ("Taco Norte", "LOCATED_IN", "Austin", "Taco Norte is located in Austin."),
    ("Taco Norte", "SERVES", "tacos", "Taco Norte serves tacos."),
]


@pytest.fixture
async def rag():
    """GraphRAG over a synthetic join world. No LLM, no embeddings needed."""
    r = GraphRAG(dsn=TEST_DSN, namespace=NS)
    await r.connect()
    await r.delete(NS)

    doc_id = await r.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (NS, "test_hash_graph_join_95", "test/join_world.md"),
    )

    entity_ids: dict[str, int] = {}
    for name, etype, desc in ENTITIES:
        entity_ids[name] = await r.db.insert_returning_id(
            "INSERT INTO entities (namespace, name, entity_type, description) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (NS, name, etype, desc),
        )

    chunk_ids: dict[tuple[str, str, str], int] = {}
    for src, rtype, dst, sentence in RELS:
        cid = await r.db.insert_returning_id(
            "INSERT INTO chunks (document_id, content, token_count) "
            "VALUES (%s, %s, %s) RETURNING id",
            (doc_id, sentence, len(sentence.split())),
        )
        chunk_ids[(src, rtype, dst)] = cid
        rid = await r.db.insert_returning_id(
            "INSERT INTO relationships (namespace, src_id, dst_id, rel_type, description) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (NS, entity_ids[src], entity_ids[dst], rtype, sentence),
        )
        await r.db.execute(
            "INSERT INTO relationship_chunks (relationship_id, chunk_id) VALUES (%s, %s)",
            (rid, cid),
        )
        for endpoint in (src, dst):
            await r.db.execute(
                "INSERT INTO entity_chunks (entity_id, chunk_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                (entity_ids[endpoint], cid),
            )

    r._test_entity_ids = entity_ids
    r._test_chunk_ids = chunk_ids
    yield r
    await r.delete(NS)
    await r.close()


# --- find_entities: anchor binding -----------------------------------------


async def test_find_entities_exact(rag):
    matches = await rag.find_entities("Maria Ashby", namespace=NS)
    assert matches
    assert matches[0].name == "Maria Ashby"
    assert matches[0].match_type == "exact"
    assert matches[0].score == 1.0
    assert matches[0].entity_type == "person"


async def test_find_entities_fuzzy_typo(rag):
    matches = await rag.find_entities("Maria Ashbee", namespace=NS)
    assert matches
    assert matches[0].name == "Maria Ashby"
    assert matches[0].match_type == "trgm"
    assert 0 < matches[0].score < 1.0


async def test_find_entities_type_filter(rag):
    # "Taco" fuzzily hits both taquerias; entity_type filter must hold.
    matches = await rag.find_entities("Taco Verde", entity_type="restaurant", namespace=NS)
    assert all(m.entity_type == "restaurant" for m in matches)
    assert matches[0].name == "Taco Verde"
    # A wrong type filter excludes it.
    assert await rag.find_entities("Taco Verde", entity_type="person", namespace=NS) == []


async def test_find_entities_no_match(rag):
    assert await rag.find_entities("Zzyzx Quandary", namespace=NS) == []


async def test_find_entities_fuzzy_off(rag):
    assert await rag.find_entities("Maria Ashbee", fuzzy=False, namespace=NS) == []


# --- traverse: typed, directed walk -----------------------------------------


async def test_traverse_typed_out(rag):
    maria = rag._test_entity_ids["Maria Ashby"]
    hops = await rag.traverse([maria], rel_types="LIVES_IN", direction="out", namespace=NS)
    assert [h.name for h in hops] == ["Portland"]
    hop = hops[0]
    assert hop.rel_type == "LIVES_IN"
    assert hop.depth == 1
    assert hop.from_id == maria
    assert hop.weight == 1.0
    # Provenance: the edge's chunk ids point at the supporting sentence.
    assert chunk_of(rag, "Maria Ashby", "LIVES_IN", "Portland") in hop.chunk_ids


async def test_traverse_direction_asymmetry(rag):
    portland = rag._test_entity_ids["Portland"]
    # Nothing leaves Portland via LIVES_IN...
    out = await rag.traverse([portland], rel_types="LIVES_IN", direction="out", namespace=NS)
    assert out == []
    # ...but two people point into it.
    inbound = await rag.traverse([portland], rel_types="LIVES_IN", direction="in", namespace=NS)
    assert sorted(h.name for h in inbound) == ["Ida Frost", "Maria Ashby"]


async def test_traverse_type_filter_excludes_other_edges(rag):
    portland = rag._test_entity_ids["Portland"]
    inbound = await rag.traverse([portland], rel_types="LOCATED_IN", direction="in", namespace=NS)
    assert sorted(h.name for h in inbound) == ["Noodle Haven", "Slice City"]


async def test_traverse_synonym_list_case_insensitive(rag):
    devon = rag._test_entity_ids["Devon Cole"]
    # Edge stored as lowercase 'likes'; query with upper-case synonym list.
    hops = await rag.traverse(
        [devon], rel_types=["LIKES", "CRAVES"], direction="out", namespace=NS
    )
    assert [h.name for h in hops] == ["tacos"]


async def test_traverse_multi_hop_untyped(rag):
    maria = rag._test_entity_ids["Maria Ashby"]
    hops = await rag.traverse([maria], direction="any", max_hops=2, namespace=NS)
    names = {h.name for h in hops}
    # 1 hop: Portland, ramen. 2 hops: whatever touches those.
    assert {"Portland", "ramen", "Noodle Haven", "Slice City", "Ida Frost"} <= names
    assert all(h.depth <= 2 for h in hops)


async def test_traverse_validation(rag):
    with pytest.raises(ValueError):
        await rag.traverse([], namespace=NS)
    with pytest.raises(ValueError):
        await rag.traverse([1], direction="up", namespace=NS)
    with pytest.raises(ValueError):
        await rag.traverse([1], max_hops=0, namespace=NS)


# --- graph_join: the dependent conjunctive join ------------------------------


def chunk_of(rag, src, rtype, dst) -> int:
    return rag._test_chunk_ids[(src, rtype, dst)]


async def test_graph_join_issue_scenario(rag):
    """'Restaurant for Maria' — bind city+food, intersect, unique answer."""
    result = await rag.graph_join(
        "Maria Ashby",
        bind=[("LIVES_IN", "city"), ("CRAVES", "food")],
        intersect=[("LOCATED_IN", "$city"), ("SERVES", "$food")],
        namespace=NS,
    )
    assert result.anchor is not None and result.anchor.name == "Maria Ashby"

    # Bound intermediates are carried for explainability.
    assert [b.name for b in result.bindings["city"]] == ["Portland"]
    assert [b.name for b in result.bindings["food"]] == ["ramen"]

    # Exactly the one satisfying restaurant.
    assert [m.name for m in result.matches] == ["Noodle Haven"]
    match = result.matches[0]
    assert match.entity_type == "restaurant"

    # One supporting edge per constraint, tied to the right bound value.
    assert len(match.evidence) == 2
    by_constraint = {ev.constraint_idx: ev for ev in match.evidence}
    assert by_constraint[0].var == "city" and by_constraint[0].var_name == "Portland"
    assert by_constraint[1].var == "food" and by_constraint[1].var_name == "ramen"
    assert by_constraint[0].rel_type == "LOCATED_IN"
    assert by_constraint[1].rel_type == "SERVES"

    # Provenance chunk ids point at the exact supporting sentences.
    assert (
        chunk_of(rag, "Noodle Haven", "LOCATED_IN", "Portland") in by_constraint[0].edge_chunk_ids
    )
    assert chunk_of(rag, "Noodle Haven", "SERVES", "ramen") in by_constraint[1].edge_chunk_ids
    assert chunk_of(rag, "Maria Ashby", "LIVES_IN", "Portland") in result.chunk_ids()


async def test_graph_join_fuzzy_anchor(rag):
    """A typo'd anchor still binds via pg_trgm and completes the join."""
    result = await rag.graph_join(
        "Maria Ashbee",
        bind=[("LIVES_IN", "city"), ("CRAVES", "food")],
        intersect=[("LOCATED_IN", "$city"), ("SERVES", "$food")],
        namespace=NS,
    )
    assert result.anchor is not None
    assert result.anchor.name == "Maria Ashby"
    assert result.anchor.match_type == "trgm"
    assert [m.name for m in result.matches] == ["Noodle Haven"]


async def test_graph_join_anchor_by_id(rag):
    result = await rag.graph_join(
        rag._test_entity_ids["Maria Ashby"],
        bind=[("LIVES_IN", "city"), ("CRAVES", "food")],
        intersect=[("LOCATED_IN", "$city"), ("SERVES", "$food")],
        namespace=NS,
    )
    assert [m.name for m in result.matches] == ["Noodle Haven"]


async def test_graph_join_synonym_rel_types(rag):
    """Devon's craving edge is stored lowercase as 'likes'; synonyms find it."""
    result = await rag.graph_join(
        "Devon Cole",
        bind=[("LIVES_IN", "city"), (["LIKES", "CRAVES"], "food")],
        intersect=[("LOCATED_IN", "$city"), ("SERVES", "$food")],
        namespace=NS,
    )
    assert [b.name for b in result.bindings["food"]] == ["tacos"]
    assert sorted(m.name for m in result.matches) == ["Taco Norte", "Taco Verde"]


async def test_graph_join_multi_candidate_intersection(rag):
    """Two Austin taquerias satisfy Devon's join — both returned, full evidence."""
    result = await rag.graph_join(
        "Devon Cole",
        bind=[("LIVES_IN", "city"), ("LIKES", "food")],
        intersect=[("LOCATED_IN", "$city"), ("SERVES", "$food")],
        namespace=NS,
    )
    assert sorted(m.name for m in result.matches) == ["Taco Norte", "Taco Verde"]
    for m in result.matches:
        assert {ev.constraint_idx for ev in m.evidence} == {0, 1}
        assert all(ev.edge_chunk_ids for ev in m.evidence)


async def test_graph_join_empty_intersection(rag):
    """Ida craves tacos but lives in Portland — no Portland taqueria exists.

    Bindings still come back populated so the caller can see which leg
    produced candidates and which intersection eliminated them.
    """
    result = await rag.graph_join(
        "Ida Frost",
        bind=[("LIVES_IN", "city"), ("CRAVES", "food")],
        intersect=[("LOCATED_IN", "$city"), ("SERVES", "$food")],
        namespace=NS,
    )
    assert result.anchor is not None
    assert [b.name for b in result.bindings["city"]] == ["Portland"]
    assert [b.name for b in result.bindings["food"]] == ["tacos"]
    assert result.matches == ()


async def test_graph_join_unknown_anchor(rag):
    result = await rag.graph_join(
        "Zzyzx Quandary",
        bind=[("LIVES_IN", "city")],
        intersect=[("LOCATED_IN", "$city")],
        namespace=NS,
    )
    assert result.anchor is None
    assert result.matches == ()
    assert result.bindings == {"city": []}
    assert result.chunk_ids() == []


async def test_graph_join_plan_validation_surfaces(rag):
    with pytest.raises(ValueError, match="undeclared"):
        await rag.graph_join(
            "Maria Ashby",
            bind=[("LIVES_IN", "city")],
            intersect=[("SERVES", "$food")],
            namespace=NS,
        )
    with pytest.raises(ValueError, match="at least one bind"):
        await rag.graph_join("Maria Ashby", bind=[], intersect=[("SERVES", "$x")], namespace=NS)


# --- EXPLAIN: index usage at 10^4 edges (issue acceptance criterion) ---------


async def test_join_uses_relationship_indexes_at_scale(rag):
    """No seq-scan on relationships for the typed steps at ~2x10^4 edges."""
    # Bulk-grow the namespace: 2,000 filler entities, 20,000 filler edges.
    await rag.db.execute(
        "INSERT INTO entities (namespace, name, entity_type) "
        "SELECT %s, 'filler-' || g, 'filler' FROM generate_series(1, 2000) g",
        (NS,),
    )
    await rag.db.execute(
        """
        INSERT INTO relationships (namespace, src_id, dst_id, rel_type)
        SELECT %s,
               f.ids[1 + (g / 10)],
               f.ids[1 + (((g / 10) * 31 + g %% 10) %% 2000)],
               'FILLER_REL_' || (g %% 10)
        FROM generate_series(0, 19999) g,
             (SELECT array_agg(id ORDER BY id) AS ids FROM entities
              WHERE namespace = %s AND entity_type = 'filler') f
        """,
        (NS, NS),
    )
    await rag.db.execute("ANALYZE entities")
    await rag.db.execute("ANALYZE relationships")

    binds = parse_bind_steps([("LIVES_IN", "city"), ("CRAVES", "food")])
    intersects = parse_intersect_steps(
        [("LOCATED_IN", "$city"), ("SERVES", "$food")], ["city", "food"]
    )
    sql = build_join_sql(binds, intersects)
    params = {
        "namespace": NS,
        "anchor_id": rag._test_entity_ids["Maria Ashby"],
        "match_limit": 50,
        "bind_0_types": ["LIVES_IN"],
        "bind_1_types": ["CRAVES"],
        "cand_0_types": ["LOCATED_IN"],
        "cand_1_types": ["SERVES"],
    }
    rows = await rag.db.fetch_all("EXPLAIN (FORMAT JSON) " + sql, params)
    plan = rows[0]["QUERY PLAN"]
    if isinstance(plan, str):
        plan = json.loads(plan)

    def seq_scans_on_relationships(node) -> list[dict]:
        found = []
        if node.get("Node Type") == "Seq Scan" and node.get("Relation Name") == "relationships":
            found.append(node)
        for child in node.get("Plans", []):
            found.extend(seq_scans_on_relationships(child))
        return found

    offenders = seq_scans_on_relationships(plan[0]["Plan"])
    assert offenders == [], f"seq scan on relationships in join plan: {offenders}"

    # And the join still returns exactly the right answer at scale.
    result = await rag.graph_join(
        "Maria Ashby",
        bind=[("LIVES_IN", "city"), ("CRAVES", "food")],
        intersect=[("LOCATED_IN", "$city"), ("SERVES", "$food")],
        namespace=NS,
    )
    assert [m.name for m in result.matches] == ["Noodle Haven"]
