"""Tests for standalone migration CLI and pool guardrails."""

import logging
import os

import psycopg
import pytest
from click.testing import CliRunner

import pg_raggraph.config as config_mod
from pg_raggraph.cli import main
from pg_raggraph.config import PGRGConfig

pytestmark = pytest.mark.integration

TEST_DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)


def test_migrate_command_applies_migrations_and_exits():
    result = CliRunner().invoke(main, ["--db", TEST_DSN, "migrate"])

    assert result.exit_code == 0, result.output
    assert "Migrations applied." in result.output
    with psycopg.connect(TEST_DSN) as conn:
        count = conn.execute("SELECT count(*) FROM pgrg_applied_migrations").fetchone()[0]
    assert count > 0


def test_pool_max_over_ten_warns_once(caplog):
    config_mod._pool_max_warned = False
    caplog.set_level(logging.WARNING, logger="pg_raggraph.config")

    PGRGConfig(pool_max=11)
    PGRGConfig(pool_max=12)

    warnings = [rec.message for rec in caplog.records if "Configured pool_max=" in rec.message]
    assert len(warnings) == 1
    assert "pool_max=11" in warnings[0]
