"""Tests for HNSW runtime tuning config."""

import os
from importlib.resources import files

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.db import Database

pytestmark = pytest.mark.integration

TEST_DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)


@pytest.mark.asyncio
async def test_hnsw_ef_search_applied_to_acquired_connections():
    db = Database(
        PGRGConfig(
            dsn=TEST_DSN,
            hnsw_ef_search=80,
            pool_min=1,
            pool_max=1,
        )
    )
    await db.connect()
    try:
        row = await db.fetch_one("SHOW hnsw.ef_search")
        assert row["hnsw.ef_search"] == "80"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_hnsw_index_reloptions_reflect_configured_defaults():
    db = Database(PGRGConfig(dsn=TEST_DSN, pool_min=1, pool_max=1))
    await db.connect()
    try:
        rows = await db.fetch_all(
            "SELECT relname, reloptions "
            "FROM pg_class "
            "WHERE relname IN ('idx_chunk_embed', 'idx_entity_embed')"
        )
    finally:
        await db.close()

    options = {row["relname"]: set(row["reloptions"] or []) for row in rows}
    assert options["idx_chunk_embed"] >= {"m=16", "ef_construction=64"}
    assert options["idx_entity_embed"] >= {"m=16", "ef_construction=64"}


def test_hnsw_build_params_config_defaults():
    cfg = PGRGConfig()
    assert cfg.hnsw_m == 16
    assert cfg.hnsw_ef_construction == 64
    assert cfg.hnsw_ef_search == 40


def test_hnsw_build_params_render_into_schema_and_migration():
    db = Database(PGRGConfig(hnsw_m=32, hnsw_ef_construction=128))
    schema = files("pg_raggraph.sql").joinpath("schema.sql").read_text()
    migration = files("pg_raggraph.sql.migrations").joinpath("004_hnsw_params.sql").read_text()

    rendered_schema = db._render_sql_template(schema)
    rendered_migration = db._render_sql_template(migration)

    assert "WITH (m = 32, ef_construction = 128)" in rendered_schema
    assert "WITH (m = 32, ef_construction = 128)" in rendered_migration
