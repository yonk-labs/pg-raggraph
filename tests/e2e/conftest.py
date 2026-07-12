"""Shared fixtures for E2E tests: bento-api (:8000, published to the host),
exercising the paths where bento actually consumes pg-raggraph.

Seeding still goes through the pg-raggraph-proxy directly (docker exec
curl) -- bento-api has no route that ingests into an arbitrary pg-raggraph
namespace. Two consumer paths exist:

- ``/v1/admin/pg-raggraph/*`` (query/status/indexes) -- a thin debug
  forwarder with no auth/ownership check (``admin_auth`` is a placeholder).
  ``kb_id`` resolves to a namespace via ``kb_namespace()``
  (bento/backend/api/kb_namespace.py): ``f"kb-{kb_id}"`` for any non-empty
  ``kb_id``, no KB-catalog row required.
- ``/v1/ask`` -- the real product flow. Its ``namespace`` debug backdoor
  goes through ``security.kb_access.resolve_accessible_namespace``, which
  requires either the legacy "default" namespace or an authenticated KB
  owner -- it 404s for an anonymous caller naming an arbitrary namespace
  (by design, #516/#518: closes a horizontal-IDOR read leak). So a
  throwaway namespace with no bento account can only be reached through the
  admin forwarder, not through /v1/ask.

``throwaway_kb_id`` yields ``(kb_id, namespace)`` where
``namespace == f"kb-{kb_id}"`` and deletes that namespace's rows from
bento-postgres on teardown.
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid

import httpx
import pytest

PROXY_CONTAINER = "bento-pg-raggraph-proxy"
PG_CONTAINER = "bento-postgres"
PG_USER = "bento"
PG_DB = "bento"
BENTO_API_BASE = "http://localhost:8000"


def _container_running(name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def proxy_request(method: str, path: str, body: dict | None = None, timeout: int = 30) -> dict:
    """One HTTP call to the proxy's internal :8000 via ``docker exec curl``
    -- used only to seed a throwaway namespace bento-api has no ingest
    route for."""
    cmd = ["docker", "exec", PROXY_CONTAINER, "curl", "-s", "-X", method, f"http://localhost:8000{path}"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, f"docker exec curl failed: {result.stderr}"
    return json.loads(result.stdout)


def delete_bento_namespace(namespace: str) -> None:
    """Delete a namespace's rows directly from bento-postgres (the proxy
    exposes no delete route). Only ever called with a namespace this suite
    generated itself -- never a shared benchmark KB."""
    sql = (
        f"DELETE FROM chunks WHERE document_id IN "
        f"(SELECT id FROM documents WHERE namespace = '{namespace}'); "
        f"DELETE FROM entities WHERE namespace = '{namespace}'; "
        f"DELETE FROM relationships WHERE namespace = '{namespace}'; "
        f"DELETE FROM documents WHERE namespace = '{namespace}';"
    )
    subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", PG_USER, "-d", PG_DB, "-c", sql],
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture(scope="session", autouse=True)
def _require_bento_stack():
    if not _container_running(PROXY_CONTAINER):
        pytest.skip(f"{PROXY_CONTAINER} container is not running")
    if not _container_running(PG_CONTAINER):
        pytest.skip(f"{PG_CONTAINER} container is not running")
    try:
        resp = httpx.get(f"{BENTO_API_BASE}/health", timeout=5)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"bento-api not reachable at {BENTO_API_BASE}: {exc}")


@pytest.fixture
def throwaway_kb_id():
    kb_id = f"test_pgrg_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    namespace = f"kb-{kb_id}"
    try:
        yield kb_id, namespace
    finally:
        delete_bento_namespace(namespace)
