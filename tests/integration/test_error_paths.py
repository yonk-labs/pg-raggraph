"""PR-105 — error-path test suite.

Covers the failure modes that the audit identified as historically
under-tested. Each test asserts a specific exception type or behavior, not
just `pytest.raises(Exception)`. Read the docstring before adjusting any
assertion: the audit's value is in the *specific* error contract, not the
mere fact of an error.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.config import PGRGConfig
from pg_raggraph.evolution import tune_scoring_weights

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Connection / DSN
# ---------------------------------------------------------------------------


async def test_bad_dsn_raises_connection_error_with_helpful_message():
    """rag.connect() against an unreachable DB wraps in ConnectionError
    naming the DSN — the user shouldn't have to read a stack trace to
    find the URL they got wrong."""
    rag = GraphRAG(dsn="postgresql://postgres:postgres@127.0.0.1:1/nope")
    with pytest.raises(ConnectionError) as exc_info:
        await rag.connect()
    msg = str(exc_info.value)
    assert "Cannot connect to PostgreSQL" in msg
    # The DSN we supplied should appear in the message so users see what
    # got tried (not the env default).
    assert "127.0.0.1:1" in msg


async def test_pgrg_env_production_with_default_dsn_raises_runtime_error(monkeypatch):
    """PR-211: alpha defaults bake in well-known credentials. In
    production, that's a deploy-time bug — refuse to start."""
    monkeypatch.setenv("PGRG_ENV", "production")
    # PGRGConfig must be invoked WITHOUT inheriting the test DSN — so we
    # explicitly omit dsn to land on the default.
    with pytest.raises(RuntimeError) as exc_info:
        PGRGConfig()
    msg = str(exc_info.value)
    assert "default Postgres credentials" in msg
    assert "PGRG_ENV=production" in msg


async def test_pgrg_env_production_with_custom_dsn_succeeds(monkeypatch):
    """The production guard only fires for the *default* DSN. A real DSN
    must not be blocked."""
    monkeypatch.setenv("PGRG_ENV", "production")
    cfg = PGRGConfig(dsn="postgresql://realuser:realpass@db.example.com:5432/app")
    # Just instantiating without raising is the whole assertion.
    assert "realuser" in cfg.dsn


# ---------------------------------------------------------------------------
# Namespace validation
# ---------------------------------------------------------------------------


async def test_invalid_namespace_special_chars_raises_value_error(db):
    """PR-105: namespace allowlist is the boundary contract — anything
    outside [a-zA-Z0-9_\\-\\.] gets rejected with the regex echoed in the
    message so the user knows the rule."""
    rag = GraphRAG(dsn=db.config.dsn)
    await rag.connect()
    try:
        with pytest.raises(ValueError) as exc_info:
            await rag.delete("bad ns!@#")
        assert "Invalid namespace" in str(exc_info.value)
    finally:
        await rag.close()


async def test_invalid_namespace_too_long_raises_value_error(db):
    """65 chars exceeds the 64-char allowlist. The error must mention
    the length contract so the user can fix it without reading source."""
    rag = GraphRAG(dsn=db.config.dsn)
    await rag.connect()
    try:
        with pytest.raises(ValueError) as exc_info:
            await rag.delete("a" * 65)
        assert "Invalid namespace" in str(exc_info.value)
        assert "1-64" in str(exc_info.value)
    finally:
        await rag.close()


# ---------------------------------------------------------------------------
# Evolution-aware retrieval contracts
# ---------------------------------------------------------------------------


async def test_query_naive_datetime_as_of_raises_value_error(db):
    """Cookbook contract: as_of must be tz-aware. Naive datetimes silently
    misbehave against TIMESTAMPTZ; enforced in evolution.py and bubbled
    out via rag.query()."""
    rag = GraphRAG(dsn=db.config.dsn, evolution_tier="structural")
    await rag.connect()
    try:
        with pytest.raises(ValueError) as exc_info:
            await rag.query(
                "anything",
                namespace="medical_hrt",
                as_of=datetime(2001, 1, 1),  # naive — no tzinfo
            )
        assert "timezone-aware" in str(exc_info.value).lower()
    finally:
        await rag.close()


# ---------------------------------------------------------------------------
# tune_scoring_weights cost guard (PR-206)
# ---------------------------------------------------------------------------


async def test_tune_scoring_weights_max_grid_size_guard(db):
    """5x5x5x5 = 625 cells; default cap is 50. The guard must fire
    BEFORE any LLM/retrieval call so we don't burn budget."""
    rag = GraphRAG(dsn=db.config.dsn, evolution_tier="structural")
    await rag.connect()
    try:
        big_grid = {
            "w_sem": [0.1, 0.2, 0.3, 0.4, 0.5],
            "w_recent": [0.0, 0.1, 0.2, 0.3, 0.4],
            "w_supersession": [0.0, 0.1, 0.2, 0.3, 0.4],
            "w_graph": [0.1, 0.2, 0.3, 0.4, 0.5],
        }
        with pytest.raises(ValueError) as exc_info:
            await tune_scoring_weights(
                rag,
                namespace="medical_hrt",
                gold=[{"question": "x", "expected_substring": "y"}],
                grid=big_grid,
            )
        msg = str(exc_info.value)
        assert "Grid size 625" in msg
        assert "max_grid_size=50" in msg
    finally:
        await rag.close()


async def test_tune_scoring_weights_unknown_field_raises(db):
    """Typos in weight names create new attributes silently on PGRGConfig
    (no validate_assignment) — must be rejected at the boundary."""
    rag = GraphRAG(dsn=db.config.dsn, evolution_tier="structural")
    await rag.connect()
    try:
        with pytest.raises(ValueError) as exc_info:
            await tune_scoring_weights(
                rag,
                namespace="medical_hrt",
                gold=[{"question": "x", "expected_substring": "y"}],
                grid={"w_typo": [0.5]},
            )
        assert "Unknown weight names" in str(exc_info.value)
        assert "w_typo" in str(exc_info.value)
    finally:
        await rag.close()


# ---------------------------------------------------------------------------
# Server hardening (PR-104) — direct unit checks on the helpers
# ---------------------------------------------------------------------------


async def test_filename_sanitizer_strips_path_traversal():
    """`../../etc/passwd` must not survive sanitization. We strip path
    components first, then allowlist-replace the remainder."""
    from pg_raggraph.server import _sanitize_filename

    assert _sanitize_filename("../../etc/passwd") == "passwd"
    assert _sanitize_filename("/abs/path/x.txt") == "x.txt"
    assert _sanitize_filename("foo bar.md") == "foo_bar.md"
    # Shell-meta chars (no embedded `/` so basename keeps the whole string)
    # become single underscores; collapsed runs are intentional.
    assert _sanitize_filename("a;b|c.md") == "a_b_c.md"


async def test_filename_sanitizer_rejects_empty_inputs():
    """Names that sanitize to nothing usable (empty, only-dots,
    only-separators) return None so the endpoint can 400 cleanly."""
    from pg_raggraph.server import _sanitize_filename

    assert _sanitize_filename("") is None
    assert _sanitize_filename("....") is None
    assert _sanitize_filename("/") is None


# ---------------------------------------------------------------------------
# Server endpoint integration via FastAPI TestClient
# ---------------------------------------------------------------------------


async def test_ingest_endpoint_rejects_disallowed_extension(db):
    """PR-104: file with a non-allowlisted extension returns 415 with
    a clear message naming the rejected extension and the allowlist."""
    from fastapi.testclient import TestClient

    from pg_raggraph.server import create_app

    app = create_app(dsn=db.config.dsn, namespace="error_path_test")
    with TestClient(app) as client:
        resp = client.post(
            "/ingest",
            files={"files": ("evil.exe", BytesIO(b"x"), "application/octet-stream")},
            data={"namespace": "error_path_test"},
        )
    assert resp.status_code == 415
    body = resp.json()
    assert ".exe" in body["detail"]


async def test_ingest_endpoint_rejects_oversize_upload(db, monkeypatch):
    """PR-104: PGRG_SERVER_MAX_UPLOAD_MB caps upload size; over-cap
    returns 413 with the limit echoed back."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PGRG_SERVER_MAX_UPLOAD_MB", "1")
    from pg_raggraph.server import create_app

    app = create_app(dsn=db.config.dsn, namespace="error_path_test")
    payload = b"x" * (2 * 1024 * 1024)  # 2 MB > 1 MB cap
    with TestClient(app) as client:
        resp = client.post(
            "/ingest",
            files={"files": ("big.md", BytesIO(payload), "text/markdown")},
            data={"namespace": "error_path_test"},
        )
    assert resp.status_code == 413
    assert "1 MB" in resp.json()["detail"]


async def test_graph_endpoint_rejects_invalid_limit(db):
    """PR-103: ?limit=N is bounded; out-of-range values return 400 with
    a clear message — not 500 from a downstream parse error."""
    from fastapi.testclient import TestClient

    from pg_raggraph.server import create_app

    app = create_app(dsn=db.config.dsn, namespace="error_path_test")
    with TestClient(app) as client:
        # Non-numeric, non-'all' value
        resp = client.get("/graph?limit=banana")
        assert resp.status_code == 400
        assert "Invalid limit" in resp.json()["detail"]
        # Above the 5000 cap
        resp = client.get("/graph?limit=10000")
        assert resp.status_code == 400
        assert "limit max is 5000" in resp.json()["detail"]


async def test_health_returns_ok_against_live_db(db):
    """Sanity: /health is the cheap liveness probe and should succeed
    against the test database. If it doesn't, the rest of the server
    tests would lie."""
    from fastapi.testclient import TestClient

    from pg_raggraph.server import create_app

    app = create_app(dsn=db.config.dsn, namespace="error_path_test")
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_ready_returns_ok_against_migrated_db(db):
    """PR-208: /ready must return 200 once schema migrations are
    applied (the db fixture takes care of that). The response payload
    must include the resolved schema_version so deploys can verify the
    pod's expectation matches the DB."""
    from fastapi.testclient import TestClient

    from pg_raggraph.server import create_app

    app = create_app(dsn=db.config.dsn, namespace="error_path_test")
    with TestClient(app) as client:
        resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["schema_version"] >= 1
    assert body["expected_schema_version"] >= 1
