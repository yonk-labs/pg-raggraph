"""Unit tests for graph_join plan validation and SQL building (issue #95).

No database required — exercises the pure helpers in
``pg_raggraph.graph_join``.
"""

from __future__ import annotations

import pytest

from pg_raggraph.graph_join import (
    BoundValue,
    EntityMatch,
    GraphJoinMatch,
    GraphJoinResult,
    JoinEvidence,
    build_find_entities_sql,
    build_join_sql,
    build_traverse_sql,
    normalize_rel_types,
    parse_bind_steps,
    parse_intersect_steps,
)

# --- normalize_rel_types ----------------------------------------------------


def test_normalize_single_string():
    assert normalize_rel_types("lives_in") == ("LIVES_IN",)


def test_normalize_synonym_list_upper_and_dedupe():
    assert normalize_rel_types(["likes", "CRAVES", "Likes "]) == ("LIKES", "CRAVES")


def test_normalize_empty_raises():
    with pytest.raises(ValueError):
        normalize_rel_types([])
    with pytest.raises(ValueError):
        normalize_rel_types("   ")


def test_normalize_non_string_raises():
    with pytest.raises(ValueError):
        normalize_rel_types([42])


# --- parse_bind_steps -------------------------------------------------------


def test_bind_defaults_to_out():
    steps = parse_bind_steps([("LIVES_IN", "city")])
    assert steps[0].direction == "out"
    assert steps[0].var == "city"
    assert steps[0].rel_types == ("LIVES_IN",)


def test_bind_explicit_direction_and_synonyms():
    steps = parse_bind_steps([(["likes", "craves"], "food", "any")])
    assert steps[0].rel_types == ("LIKES", "CRAVES")
    assert steps[0].direction == "any"


def test_bind_rejects_bad_direction():
    with pytest.raises(ValueError, match="direction"):
        parse_bind_steps([("LIVES_IN", "city", "sideways")])


def test_bind_rejects_duplicate_var():
    with pytest.raises(ValueError, match="twice"):
        parse_bind_steps([("A", "x"), ("B", "x")])


def test_bind_rejects_invalid_var_name():
    with pytest.raises(ValueError, match="identifier"):
        parse_bind_steps([("A", "$city")])
    with pytest.raises(ValueError, match="identifier"):
        parse_bind_steps([("A", "1city")])


def test_bind_rejects_empty_and_bad_shape():
    with pytest.raises(ValueError, match="at least one bind"):
        parse_bind_steps([])
    with pytest.raises(ValueError, match="bind\\[0\\]"):
        parse_bind_steps(["LIVES_IN"])
    with pytest.raises(ValueError, match="bind\\[0\\]"):
        parse_bind_steps([("A", "x", "out", "extra")])


# --- parse_intersect_steps --------------------------------------------------


def test_intersect_parses_var_refs():
    steps = parse_intersect_steps(
        [("LOCATED_IN", "$city"), ("SERVES", "$food", "in")],
        ["city", "food"],
    )
    assert steps[0].var == "city"
    assert steps[0].direction == "out"
    assert steps[1].var == "food"
    assert steps[1].direction == "in"


def test_intersect_requires_dollar_prefix():
    with pytest.raises(ValueError, match="\\$name"):
        parse_intersect_steps([("LOCATED_IN", "city")], ["city"])


def test_intersect_rejects_undeclared_var():
    with pytest.raises(ValueError, match="undeclared"):
        parse_intersect_steps([("LOCATED_IN", "$town")], ["city"])


def test_intersect_rejects_empty():
    with pytest.raises(ValueError, match="at least one intersect"):
        parse_intersect_steps([], ["city"])


# --- build_traverse_sql -----------------------------------------------------


def test_traverse_sql_out_is_directed():
    sql = build_traverse_sql("out", typed=True)
    assert "r.src_id = w.entity_id" in sql
    assert "r.dst_id = w.entity_id" not in sql
    assert "upper(r.rel_type) = ANY(%(rel_types)s)" in sql


def test_traverse_sql_in_is_directed():
    sql = build_traverse_sql("in", typed=True)
    assert "r.dst_id = w.entity_id" in sql
    assert "r.src_id = w.entity_id" not in sql


def test_traverse_sql_any_walks_both_ways():
    sql = build_traverse_sql("any", typed=False)
    assert "r.src_id = w.entity_id OR r.dst_id = w.entity_id" in sql
    assert "CASE WHEN" in sql
    assert "rel_types" not in sql  # untyped walk has no type filter


def test_traverse_sql_excludes_retracted_and_cycles():
    sql = build_traverse_sql("out", typed=False)
    assert "NOT COALESCE(r.retracted, FALSE)" in sql
    assert "= ANY(w.path)" in sql


def test_traverse_sql_rejects_bad_direction():
    with pytest.raises(ValueError):
        build_traverse_sql("both", typed=False)


# --- build_join_sql ---------------------------------------------------------


def _issue_plan():
    binds = parse_bind_steps([("LIVES_IN", "city"), (["CRAVES", "LIKES"], "food")])
    intersects = parse_intersect_steps(
        [("LOCATED_IN", "$city"), ("SERVES", "$food")], ["city", "food"]
    )
    return binds, intersects


def test_join_sql_has_one_cte_per_step():
    binds, intersects = _issue_plan()
    sql = build_join_sql(binds, intersects)
    for name in ("bind_0", "bind_1", "cand_0", "cand_1", "matched"):
        assert f"{name} AS (" in sql
    # Parameter placeholders for every rel-type list.
    for p in ("bind_0_types", "bind_1_types", "cand_0_types", "cand_1_types"):
        assert f"%({p})s" in sql


def test_join_sql_is_single_statement():
    binds, intersects = _issue_plan()
    sql = build_join_sql(binds, intersects)
    assert ";" not in sql


def test_join_sql_intersects_all_constraints():
    binds, intersects = _issue_plan()
    sql = build_join_sql(binds, intersects)
    assert "USING (candidate_id)" in sql
    assert "LIMIT %(match_limit)s" in sql


def test_join_sql_direction_fragments():
    binds = parse_bind_steps([("LIVES_IN", "city", "in")])
    intersects = parse_intersect_steps([("LOCATED_IN", "$city", "in")], ["city"])
    sql = build_join_sql(binds, intersects)
    # bind 'in': anchor is the destination, neighbor is the source.
    assert "r.dst_id = %(anchor_id)s" in sql
    # intersect 'in': $var —rel→ candidate.
    assert "r.src_id = b.entity_id" in sql


def test_join_sql_constraint_references_correct_bind():
    binds = parse_bind_steps([("A", "x"), ("B", "y")])
    intersects = parse_intersect_steps([("C", "$y")], ["x", "y"])
    sql = build_join_sql(binds, intersects)
    assert "JOIN bind_1 b ON" in sql
    assert "JOIN bind_0 b ON" not in sql


def test_join_sql_excludes_anchor_and_retracted():
    binds, intersects = _issue_plan()
    sql = build_join_sql(binds, intersects)
    assert "<> %(anchor_id)s" in sql
    assert "NOT COALESCE(r.retracted, FALSE)" in sql


def test_join_sql_carries_provenance():
    binds, intersects = _issue_plan()
    sql = build_join_sql(binds, intersects)
    assert "relationship_chunks" in sql
    assert "entity_chunks" in sql


# --- build_find_entities_sql ------------------------------------------------


def test_find_entities_sql_exact_only():
    sql = build_find_entities_sql(fuzzy=False, typed=False)
    assert "similarity" not in sql
    assert "'exact' AS match_type" in sql


def test_find_entities_sql_fuzzy_and_typed():
    sql = build_find_entities_sql(fuzzy=True, typed=True)
    assert "similarity(name, %(name)s)" in sql
    assert "lower(entity_type) = lower(%(entity_type)s)" in sql
    assert "UNION ALL" in sql


def test_find_entities_sql_fuzzy_gate_is_index_eligible():
    """The fuzzy WHERE gate must use the %% operator (trgm-GIN-indexable),
    not a bare similarity() comparison (forces a seq scan — the 31.8ms p50
    fuzzy-bind defect from the cap-gold-v1 bake-off addendum)."""
    sql = build_find_entities_sql(fuzzy=True, typed=False)
    assert "name %% %(name)s" in sql
    # The strict > gate stays for byte-equivalent boundary semantics.
    assert "similarity(name, %(name)s) > %(min_score)s" in sql


# --- GraphJoinResult.chunk_ids ----------------------------------------------


def test_result_chunk_ids_dedup_and_sort():
    anchor = EntityMatch(1, "Maria", "person", "", 1.0, "exact")
    bound = BoundValue("city", 2, "Portland", "city", "", 10, "LIVES_IN", 1.0, (7, 3), (3,))
    ev = JoinEvidence(0, "city", 2, "Portland", 11, "LOCATED_IN", 1.0, (9, 7))
    match = GraphJoinMatch(5, "Noodle Haven", "restaurant", "", (ev,), (12,))
    result = GraphJoinResult(anchor=anchor, bindings={"city": [bound]}, matches=(match,))
    assert result.chunk_ids() == [3, 7, 9, 12]


def test_empty_result_chunk_ids():
    assert GraphJoinResult(anchor=None).chunk_ids() == []
