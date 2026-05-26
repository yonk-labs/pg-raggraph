import os

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph import code_graph as cg

DSN = os.environ.get("PGRG_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="requires PGRG_TEST_DSN")

NS = "test_code_graph"


async def _seed(rag, edges):
    """edges: list of (src_fqn, dst_fqn, rel_type, weight, snippet). Inserts
    CODE_SYMBOL entities (idempotent) and CALLS-style relationships."""
    db = rag._db
    names = {n for e in edges for n in (e[0], e[1])}
    ids = {}
    for name in names:
        row = await db.fetch_one(
            "INSERT INTO entities (namespace, name, entity_type, description) "
            "VALUES (%s, %s, 'CODE_SYMBOL', %s) "
            "ON CONFLICT (namespace, name) DO UPDATE SET name = EXCLUDED.name "
            "RETURNING id",
            (NS, name, f"Code symbol {name}"),
        )
        ids[name] = row["id"]
    for src, dst, rel, weight, snippet in edges:
        await db.execute(
            "INSERT INTO relationships (namespace, src_id, dst_id, rel_type, weight, "
            "description, properties) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (NS, ids[src], ids[dst], rel, weight, snippet, "{}"),
        )
    return ids


async def _fresh(rag):
    await rag.connect()
    await rag.delete(NS)  # clear any prior run's data in this namespace


@pytest.mark.asyncio
async def test_code_impact_direct_callers_and_callees():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        # b is called by a; b calls c.
        await _seed(rag, [
            ("a", "b", "CALLS", 1.0, "a() calls b()"),
            ("b", "c", "CALLS", 1.0, "b() calls c()"),
        ])
        res = await cg.code_impact(rag._db, "b", namespace=NS, depth=1)
        assert res.found
        assert [(e.fqn, e.rel_type, e.evidence, e.depth) for e in res.callers] == [
            ("a", "CALLS", "a() calls b()", 1)
        ]
        assert [(e.fqn, e.rel_type, e.evidence, e.depth) for e in res.callees] == [
            ("c", "CALLS", "b() calls c()", 1)
        ]
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_code_impact_transitive_depth():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        # chain: a -> b -> c -> d  (callees of a at depth 3)
        await _seed(rag, [
            ("a", "b", "CALLS", 1.0, ""),
            ("b", "c", "CALLS", 1.0, ""),
            ("c", "d", "CALLS", 1.0, ""),
        ])
        res = await cg.code_impact(rag._db, "a", namespace=NS, depth=2)
        callee_fqns = {(e.fqn, e.depth) for e in res.callees}
        assert ("b", 1) in callee_fqns
        assert ("c", 2) in callee_fqns
        assert all(e.depth <= 2 for e in res.callees)  # d (depth 3) excluded
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_code_impact_cycle_terminates():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        await _seed(rag, [
            ("a", "b", "CALLS", 1.0, ""),
            ("b", "a", "CALLS", 1.0, ""),
        ])
        res = await cg.code_impact(rag._db, "a", namespace=NS, depth=10)
        assert res.found  # does not hang; cycle guard bounds the walk
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_code_impact_not_found():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        res = await cg.code_impact(rag._db, "nope.missing", namespace=NS, depth=1)
        assert res.found is False
        assert res.callers == [] and res.callees == []
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_code_impact_min_confidence_filters():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        await _seed(rag, [
            ("a", "b", "CALLS", 0.3, "weak"),
            ("a", "c", "CALLS", 0.9, "strong"),
        ])
        res = await cg.code_impact(rag._db, "a", namespace=NS, depth=1, min_confidence=0.5)
        assert {e.fqn for e in res.callees} == {"c"}
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_code_impact_depth_must_be_positive():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        with pytest.raises(ValueError):
            await cg.code_impact(rag._db, "a", namespace=NS, depth=0)
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_graphrag_code_impact_resolves_namespace_from_config():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await _fresh(rag)
    try:
        await _seed(rag, [("a", "b", "CALLS", 1.0, "a() calls b()")])
        res = await rag.code_impact("b")  # namespace from config
        assert res.found
        assert {e.fqn for e in res.callers} == {"a"}
    finally:
        await rag.delete(NS)
        await rag.close()
