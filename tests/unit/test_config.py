"""Tests for config module."""

from pg_raggraph.config import PGRGConfig


def test_defaults():
    config = PGRGConfig()
    assert config.dsn == "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
    assert config.namespace == "default"
    assert config.embedding_dim == 384
    assert config.max_hops == 2
    assert config.top_k == 10


def test_override():
    config = PGRGConfig(dsn="postgresql://other:5433/test", namespace="prod", embedding_dim=768)
    assert config.dsn == "postgresql://other:5433/test"
    assert config.namespace == "prod"
    assert config.embedding_dim == 768


def test_resolution_defaults():
    config = PGRGConfig()
    assert config.resolution_threshold == 0.85
    assert config.trgm_weight == 0.4
    assert config.vec_weight == 0.6
    assert abs(config.trgm_weight + config.vec_weight - 1.0) < 0.001


# ---------------------------------------------------------------------------
# PR-218 — redact_dsn: passwords must never reach errors or logs
# ---------------------------------------------------------------------------


def test_redact_dsn_url_with_password():
    from pg_raggraph.config import redact_dsn

    out = redact_dsn("postgresql://alice:hunter2@db.example.com:5432/app")
    assert out == "postgresql://alice:***@db.example.com:5432/app"
    assert "hunter2" not in out


def test_redact_dsn_url_without_password_unchanged():
    from pg_raggraph.config import redact_dsn

    dsn = "postgresql://alice@db.example.com:5432/app"
    assert redact_dsn(dsn) == dsn
    # No userinfo at all
    dsn = "postgresql://db.example.com/app"
    assert redact_dsn(dsn) == dsn


def test_redact_dsn_preserves_query_params():
    from pg_raggraph.config import redact_dsn

    out = redact_dsn("postgresql://u:pw@h:5432/db?sslmode=require&connect_timeout=5")
    assert out == "postgresql://u:***@h:5432/db?sslmode=require&connect_timeout=5"


def test_redact_dsn_unix_socket_url():
    from pg_raggraph.config import redact_dsn

    # Empty host, socket dir via query param — password still redacted.
    out = redact_dsn("postgresql://svc:s3cret@/mydb?host=/var/run/postgresql")
    assert "s3cret" not in out
    assert "svc:***@" in out
    assert "host=/var/run/postgresql" in out


def test_redact_dsn_keyword_conninfo():
    from pg_raggraph.config import redact_dsn

    out = redact_dsn("host=localhost port=5432 user=alice password=hunter2 dbname=app")
    assert "hunter2" not in out
    assert "password=***" in out
    assert "user=alice" in out and "host=localhost" in out


def test_redact_dsn_password_with_special_chars():
    from pg_raggraph.config import redact_dsn

    # Colons in the password: everything after the first ':' is password.
    out = redact_dsn("postgresql://u:p:a:s:s@h/db")
    assert out == "postgresql://u:***@h/db"


def test_redact_dsn_malformed_never_raises():
    from pg_raggraph.config import redact_dsn

    for junk in (
        "",
        "not a dsn at all",
        "postgresql://[::1:broken",  # invalid IPv6 — urlsplit raises ValueError
        "://:@",
        None,
        12345,
    ):
        redact_dsn(junk)  # must not raise; return value just needs to exist
