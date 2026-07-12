"""Shared fixtures for SERVICE-tier tests: the bento-pg-raggraph-proxy
container running pg-raggraph v0.9.0 as a shim in front of bento-postgres.

The proxy is NOT published to the host (internal-only :8000 inside the
bento docker network) -- every request goes through
``docker exec bento-pg-raggraph-proxy curl``. These tests never touch the
proxy's live config (PGRG_LEXICAL_BACKEND=ts_rank on this container must
stay put -- a benchmark is running against it); they only exercise the
HTTP contract against a namespace private to the test run, then delete
that namespace's rows directly from bento-postgres (the proxy exposes no
delete route).
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid

import pytest

PROXY_CONTAINER = "bento-pg-raggraph-proxy"
PG_CONTAINER = "bento-postgres"
PG_USER = "bento"
PG_DB = "bento"


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


@pytest.fixture(scope="session", autouse=True)
def _require_bento_stack():
    if not _container_running(PROXY_CONTAINER):
        pytest.skip(f"{PROXY_CONTAINER} container is not running")
    if not _container_running(PG_CONTAINER):
        pytest.skip(f"{PG_CONTAINER} container is not running")


def proxy_request(method: str, path: str, body: dict | None = None, timeout: int = 30) -> dict:
    """One HTTP call to the proxy's internal :8000 via ``docker exec curl``
    -- the only reachable path, since the container publishes no host port."""
    cmd = ["docker", "exec", PROXY_CONTAINER, "curl", "-s", "-X", method, f"http://localhost:8000{path}"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, f"docker exec curl failed: {result.stderr}"
    return json.loads(result.stdout)


def delete_bento_namespace(namespace: str) -> None:
    """Delete a namespace's rows directly from bento-postgres.

    The proxy exposes no delete route, so cleanup goes straight to the DB.
    Only ever called with a ``test_pgrg_...`` namespace this suite generated
    itself -- never a shared benchmark KB.
    """
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


@pytest.fixture
def throwaway_namespace():
    """A fresh ``test_pgrg_<ts>_<rand>`` namespace. Deletes its rows from
    bento-postgres on teardown regardless of what the test did."""
    ns = f"test_pgrg_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    try:
        yield ns
    finally:
        delete_bento_namespace(ns)
