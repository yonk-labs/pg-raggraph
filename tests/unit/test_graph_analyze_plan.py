"""Unit tests for the graph_analyze plan stages and SQL assembly (issue #100).

Pure-Python: stage validation and SQL shape. The retrieval consequence is
proven in tests/integration/test_graph_analyze_it.py against a live database
(mirroring the cap-gold-v1 PGRG_TIER3 pipeline).
"""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.graph_analyze import (
    RRF,
    Authority,
    Expand,
    MetadataFilter,
    SemanticSeed,
    build_analyze_sql,
    build_metadata_where,
)

# --- stage validation ------------------------------------------------------


def test_semantic_seed_validates():
    with pytest.raises(ValueError):
        SemanticSeed("")
    with pytest.raises(ValueError):
        SemanticSeed("q", top_k=0)
    assert SemanticSeed("q").top_k == 60


def test_expand_normalizes_and_validates():
    e = Expand(rel_types="cites")
    assert e.rel_types == ("CITES",)
    assert Expand(rel_types=["CITES", "cites", "REFERENCES"]).rel_types == (
        "CITES",
        "REFERENCES",
    )
    with pytest.raises(ValueError):
        Expand(rel_types="CITES", direction="sideways")
    with pytest.raises(ValueError):
        Expand(rel_types="CITES", max_hops=0)
    with pytest.raises(ValueError):
        Expand(rel_types="CITES", max_hops=11)


def test_authority_only_in_degree():
    assert Authority().metric == "in_degree"
    assert Authority(rel_types="cites").rel_types == ("CITES",)
    with pytest.raises(ValueError):
        Authority(metric="pagerank")


def test_metadata_filter_tuple_form_validates():
    MetadataFilter({"decision_year": ("gte", 1990)})
    with pytest.raises(ValueError):
        MetadataFilter({"decision_year": ("approximately", 1990)})
    with pytest.raises(ValueError):
        MetadataFilter({"decision_year": ("gte",)})


def test_rrf_legs_validate():
    assert RRF().legs == ("semantic", "authority")
    with pytest.raises(ValueError):
        RRF(legs=("semantic", "bm25"))
    with pytest.raises(ValueError):
        RRF(legs=())


@pytest.mark.asyncio
async def test_id_seed_requires_authority_leg():
    """A semantic-only fusion over an id seed has no score legs at all —
    rejected before any database work (db/embed are never touched)."""
    from pg_raggraph.graph_analyze import graph_analyze

    with pytest.raises(ValueError, match="authority"):
        await graph_analyze(
            None,  # db — unreached
            PGRGConfig(),
            None,  # embed — unreached
            [1],
            Expand(rel_types="CITES"),
            fuse=RRF(legs=("semantic",)),
            namespace="ns",
        )


# --- metadata WHERE builder --------------------------------------------------


def _cfg(fields: list[str]) -> PGRGConfig:
    return PGRGConfig(structured_metadata_fields=fields)


def test_metadata_where_rejects_unstructured_fields():
    with pytest.raises(ValueError, match="not a structured field"):
        build_metadata_where(MetadataFilter({"topic": "x"}), _cfg([]))


def test_metadata_where_equality_and_ranges():
    where, params = build_metadata_where(
        MetadataFilter({"court": "9th", "decision_year": ("gte", 1990)}),
        _cfg(["court", "decision_year"]),
    )
    assert "d.metadata->>%(ga_mf_0_f)s = %(ga_mf_0)s" in where
    assert "(d.metadata->>%(ga_mf_1_f)s)::numeric >= %(ga_mf_1)s" in where
    assert params["ga_mf_0"] == "9th"
    assert params["ga_mf_1"] == 1990  # numeric stays numeric for the cast


def test_metadata_where_none_is_empty():
    assert build_metadata_where(None, _cfg([])) == ("", {})


# --- SQL assembly ------------------------------------------------------------


def test_semantic_sql_shape():
    sql = build_analyze_sql(
        SemanticSeed("q", entity_type="case"),
        Expand(rel_types="CITES", max_hops=2),
        "",
        ("semantic", "authority"),
    )
    # five stages present
    assert "seed_chunks AS" in sql
    assert "hop_1 AS" in sql and "hop_2 AS" in sql and "hop_3" not in sql
    assert "JOIN seeds p" in sql  # first hop expands from the seed set
    assert "authority AS" in sql
    assert "r.dst_id = h.entity_id" in sql  # targeted in-degree
    # both RRF legs, NULLS LAST on the semantic rank (graph-reached chunks
    # may lack embeddings)
    assert "ORDER BY semantic_score DESC NULLS LAST" in sql
    assert "ORDER BY authority DESC" in sql
    assert sql.count("RANK() OVER") == 2


def test_id_seed_sql_has_no_semantic_leg():
    sql = build_analyze_sql(
        [1, 2, 3],
        Expand(rel_types="CITES", max_hops=1),
        "",
        ("authority",),
    )
    assert "%(seed_ids)s" in sql
    assert "seed_chunks" not in sql
    assert "NULL::double precision AS semantic_score" in sql
    assert sql.count("RANK() OVER") == 1


def test_direction_any_walks_both_ways():
    sql = build_analyze_sql(
        [1],
        Expand(rel_types="CITES", direction="any", max_hops=1),
        "",
        ("authority",),
    )
    assert "r.src_id = p.entity_id OR r.dst_id = p.entity_id" in sql


def test_metadata_filter_lands_in_cand():
    where, _ = build_metadata_where(
        MetadataFilter({"decision_year": ("gte", 1990)}), _cfg(["decision_year"])
    )
    sql = build_analyze_sql([1], Expand(rel_types="CITES"), where, ("authority",))
    cand = sql.split("cand AS (", 1)[1]
    assert "::numeric >=" in cand


def test_retracted_edges_never_match():
    sql = build_analyze_sql([1], Expand(rel_types="CITES"), "", ("authority",))
    # both the expansion hops and the authority aggregate skip retracted edges
    assert sql.count("NOT COALESCE(r.retracted, FALSE)") >= 2
