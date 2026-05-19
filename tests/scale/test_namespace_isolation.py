"""Tenant namespace isolation tests."""

import os

import psycopg
import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.config import PGRGConfig
from pg_raggraph.db import Database
from pg_raggraph.extraction import extract_from_chunks

pytestmark = pytest.mark.integration

TEST_DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)


async def _cleanup_tenants():
    rag = GraphRAG(TEST_DSN, namespace="ten_cleanup", skip_extraction=True)
    await rag.connect()
    try:
        await rag.db.execute("DELETE FROM documents WHERE namespace LIKE 'ten%'")
        await rag.db.execute("DELETE FROM entities WHERE namespace LIKE 'ten%'")
        await rag.db.execute("DELETE FROM relationships WHERE namespace LIKE 'ten%'")
        await rag.db.execute("DELETE FROM facts WHERE namespace LIKE 'ten%'")
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_no_cross_namespace_leak(scale_rag):
    await scale_rag.ingest_records(
        [{"text": "tenantA secret alpha", "source_id": "a1"}],
        namespace="tenA",
    )
    await scale_rag.ingest_records(
        [{"text": "tenantB secret beta", "source_id": "b1"}],
        namespace="tenB",
    )
    r = await scale_rag.query("secret", mode="naive", namespace="tenA")
    assert len(r.chunks) > 0
    assert all("beta" not in c.content for c in r.chunks)
    assert any("alpha" in c.content for c in r.chunks)


@pytest.mark.asyncio
async def test_rls_blocks_namespace_blind_query():
    await _cleanup_tenants()
    seed = GraphRAG(TEST_DSN, namespace="tenA", skip_extraction=True)
    await seed.connect()
    try:
        await seed.ingest_records(
            [{"text": "tenantA secret alpha", "source_id": "a1"}],
            namespace="tenA",
        )
        await seed.ingest_records(
            [{"text": "tenantB secret beta", "source_id": "b1"}],
            namespace="tenB",
        )
    finally:
        await seed.close()

    rag = GraphRAG(TEST_DSN, namespace="tenA", skip_extraction=True, rls_enabled=True)
    await rag.connect()
    try:
        whoami = await rag.db.fetch_all(
            "SELECT current_user AS u, "
            "current_setting('app.tenant', true) AS t, "
            "(SELECT rolsuper OR rolbypassrls FROM pg_roles "
            " WHERE rolname = current_user) AS privileged"
        )
        assert whoami[0]["u"] == "pgrg_app", whoami
        assert whoami[0]["t"] == "tenA", whoami
        assert whoami[0]["privileged"] is False, (
            f"RLS would be inert: connection role is privileged {whoami}"
        )

        rows = await rag.db.fetch_all("SELECT content_hash, namespace FROM documents")
        seen = {row["namespace"] for row in rows}
        assert seen == {"tenA"}, f"RLS leak: saw namespaces {seen}"

        crows = await rag.db.fetch_all("SELECT content FROM chunks")
        assert all("beta" not in row["content"] for row in crows)
        assert any("alpha" in row["content"] for row in crows)

        catalog = await rag.db.fetch_one(
            "SELECT "
            "has_table_privilege('pgrg_app', 'pgrg_llm_cache', 'SELECT') "
            "  AS cache_select, "
            "(SELECT relrowsecurity FROM pg_class WHERE relname = 'fact_edges') "
            "  AS fact_edges_rls"
        )
        assert catalog["cache_select"] is False
        assert catalog["fact_edges_rls"] is True

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await rag.db.fetch_all("SELECT key, response FROM pgrg_llm_cache")

        with psycopg.connect(TEST_DSN) as conn:
            fact_rows = conn.execute(
                "INSERT INTO facts "
                "(namespace, subject, predicate, object, support_span, extractor) "
                "VALUES "
                "('tenA', 'alpha', 'RELATED_TO', 'tenant', 'alpha span', 'test'), "
                "('tenA', 'alpha2', 'RELATED_TO', 'tenant', 'alpha2 span', 'test'), "
                "('tenB', 'beta', 'RELATED_TO', 'tenant', 'beta span', 'test') "
                "RETURNING id, namespace"
            ).fetchall()
            ten_a_ids = [row[0] for row in fact_rows if row[1] == "tenA"]
            ten_b_id = next(row[0] for row in fact_rows if row[1] == "tenB")
            conn.execute(
                "INSERT INTO fact_edges "
                "(src_fact_id, dst_fact_id, edge_type, inferred_by) "
                "VALUES (%s, %s, 'supports', 'test'), (%s, %s, 'supports', 'test')",
                (ten_a_ids[0], ten_a_ids[1], ten_a_ids[0], ten_b_id),
            )
            conn.commit()
        edge_rows = await rag.db.fetch_all(
            "SELECT src_fact_id, dst_fact_id FROM fact_edges ORDER BY id"
        )
        assert edge_rows == [{"src_fact_id": ten_a_ids[0], "dst_fact_id": ten_a_ids[1]}]
    finally:
        await rag.close()
        await _cleanup_tenants()


class _PermissionDenied(Exception):
    sqlstate = "42501"


class _CacheDeniedDB:
    async def fetch_one(self, query, params=None):
        raise _PermissionDenied("permission denied for table pgrg_llm_cache")

    async def execute(self, query, params=None):
        raise _PermissionDenied("permission denied for table pgrg_llm_cache")


class _FakeLLM:
    async def complete(self, messages):
        return '{"entities":[{"name":"Alpha","entity_type":"concept"}],"relationships":[]}'


@pytest.mark.asyncio
async def test_extraction_treats_denied_llm_cache_as_cache_miss():
    results = await extract_from_chunks(
        [{"content": "Alpha appears here.", "embedded_content": "Alpha appears here."}],
        _FakeLLM(),
        _CacheDeniedDB(),
        PGRGConfig(skip_extraction=False),
    )

    assert [entity.name for entity in results[0].entities] == ["Alpha"]


@pytest.mark.asyncio
async def test_rls_enabled_connection_does_not_poison_non_rls_caller():
    await _cleanup_tenants()
    seed = GraphRAG(TEST_DSN, namespace="tenA", skip_extraction=True)
    await seed.connect()
    try:
        await seed.ingest_records(
            [{"text": "tenantA secret alpha", "source_id": "a1"}],
            namespace="tenA",
        )
        await seed.ingest_records(
            [{"text": "tenantB secret beta", "source_id": "b1"}],
            namespace="tenB",
        )
    finally:
        await seed.close()

    rls_rag = GraphRAG(TEST_DSN, namespace="tenA", skip_extraction=True, rls_enabled=True)
    await rls_rag.connect()
    try:
        rows = await rls_rag.db.fetch_all("SELECT namespace FROM documents")
        assert {row["namespace"] for row in rows} == {"tenA"}
    finally:
        await rls_rag.close()

    plain = GraphRAG(TEST_DSN, namespace="tenA", skip_extraction=True, rls_enabled=False)
    await plain.connect()
    try:
        rows = await plain.db.fetch_all(
            "SELECT namespace FROM documents WHERE namespace LIKE 'ten%'"
        )
        assert {row["namespace"] for row in rows} == {"tenA", "tenB"}
    finally:
        await plain.close()
        await _cleanup_tenants()


@pytest.mark.asyncio
async def test_empty_tenant_after_set_local_reset_is_unbound_on_same_session():
    await _cleanup_tenants()
    seed = GraphRAG(TEST_DSN, namespace="tenA", skip_extraction=True)
    await seed.connect()
    try:
        await seed.ingest_records(
            [{"text": "tenantA secret alpha", "source_id": "a1"}],
            namespace="tenA",
        )
        await seed.ingest_records(
            [{"text": "tenantB secret beta", "source_id": "b1"}],
            namespace="tenB",
        )

        async with seed.db.pool.connection() as conn:
            await conn.execute("SET LOCAL ROLE pgrg_app")
            await conn.execute("SELECT set_config('app.tenant', 'tenA', true)")
            rows = await conn.execute("SELECT namespace FROM documents")
            assert {row[0] async for row in rows} == {"tenA"}
            await conn.commit()

            rows = await conn.execute("SELECT current_setting('app.tenant', true), pgrg_tenant()")
            setting, tenant = await rows.fetchone()
            assert setting == ""
            assert tenant is None

            await conn.execute("SET LOCAL ROLE pgrg_app")
            rows = await conn.execute(
                "SELECT namespace FROM documents WHERE namespace LIKE 'ten%'"
            )
            assert {row[0] async for row in rows} == {"tenA", "tenB"}
            await conn.commit()
    finally:
        await seed.close()
        await _cleanup_tenants()


@pytest.mark.asyncio
async def test_tenant_context_is_scoped_for_id_only_mutators():
    await _cleanup_tenants()
    with psycopg.connect(TEST_DSN) as conn:
        ten_a_id = conn.execute(
            "INSERT INTO entities (namespace, name) VALUES ('tenA', 'Alpha Entity') RETURNING id"
        ).fetchone()[0]
        ten_b_id = conn.execute(
            "INSERT INTO entities (namespace, name) VALUES ('tenB', 'Beta Entity') RETURNING id"
        ).fetchone()[0]
        conn.commit()

    rag = GraphRAG(TEST_DSN, namespace="tenA", skip_extraction=True, rls_enabled=True)
    await rag.connect()
    try:
        with rag.db.tenant("tenB"):
            rows = await rag.db.fetch_all("SELECT id FROM entities ORDER BY id")
            assert [row["id"] for row in rows] == [ten_b_id]

        assert await rag.delete_entity(ten_a_id) is True
    finally:
        await rag.close()

    with psycopg.connect(TEST_DSN) as conn:
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM entities WHERE id = ANY(%s) ORDER BY id",
                ([ten_a_id, ten_b_id],),
            )
        ]
    assert ids == [ten_b_id]
    await _cleanup_tenants()


@pytest.mark.asyncio
async def test_rls_app_role_connection_skips_schema_bootstrap():
    db = Database(
        PGRGConfig(
            dsn=TEST_DSN,
            rls_enabled=True,
            skip_extraction=True,
            pool_min=1,
            pool_max=1,
        )
    )
    await db.connect()
    try:
        async with db.pool.connection() as conn:
            assert await db._should_skip_schema_bootstrap(conn) is False

        async with db.pool.connection() as conn:
            await conn.execute("SET LOCAL ROLE pgrg_app")
            assert await db._should_skip_schema_bootstrap(conn) is True
            await db._verify_schema_ready(conn)
    finally:
        await db.close()
