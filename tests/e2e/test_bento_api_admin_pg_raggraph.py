"""E2E tests through bento-api (:8000) -- the paths where bento consumes
pg-raggraph.

bento-api forwards ``/v1/admin/pg-raggraph/{status,indexes,query}`` to the
pg-raggraph-proxy after resolving ``kb_id`` -> namespace via
``kb_namespace()`` (bento/backend/api/kb_namespace.py:
``f"kb-{kb_id}"``, except the ``LEGACY_KB_ID`` sentinel -> ``"default"``).
This admin forwarder has no auth/ownership check (``admin_auth`` is a
placeholder) -- unlike the public ``/v1/ask`` flow, whose ``namespace``
debug backdoor requires either the legacy "default" namespace or an
authenticated KB owner (see tests/e2e/conftest.py). It is therefore the
only route that can safely exercise a throwaway namespace with no bento
account, which is what these tests use it for.

We seed that namespace directly via the pg-raggraph-proxy (bento-api has
no ingest route wired through admin/pg-raggraph), then read it back
through bento-api to prove the wiring end to end.
"""

from __future__ import annotations

import httpx
import pytest

from .conftest import BENTO_API_BASE, proxy_request

pytestmark = pytest.mark.e2e


def test_admin_status_and_indexes_after_seed(throwaway_kb_id):
    kb_id, namespace = throwaway_kb_id
    proxy_request(
        "POST",
        "/v1/ingest",
        {
            "records": [{"text": "E2E admin-route smoke doc.", "source_id": "e2e:status:1"}],
            "namespace": namespace,
            "skip_extraction": True,
        },
    )

    status = httpx.get(
        f"{BENTO_API_BASE}/v1/admin/pg-raggraph/status", params={"kb_id": kb_id}, timeout=10
    )
    assert status.status_code == 200
    body = status.json()
    assert body["namespace"] == namespace
    assert body["documents"] == 1
    assert body["chunks"] == 1

    indexes = httpx.get(
        f"{BENTO_API_BASE}/v1/admin/pg-raggraph/indexes", params={"kb_id": kb_id}, timeout=10
    )
    assert indexes.status_code == 200
    assert indexes.json()["namespace"] == namespace


def test_admin_query_returns_seeded_chunk(throwaway_kb_id):
    kb_id, namespace = throwaway_kb_id
    proxy_request(
        "POST",
        "/v1/ingest",
        {
            "records": [
                {
                    "text": "Incident INC-9000 root cause: the E2E admin query path smoke test.",
                    "source_id": "e2e:query:1",
                }
            ],
            "namespace": namespace,
            "skip_extraction": True,
        },
    )

    resp = httpx.post(
        f"{BENTO_API_BASE}/v1/admin/pg-raggraph/query",
        json={"kb_id": kb_id, "question": "INC-9000 root cause", "mode": "naive", "top_k": 5},
        timeout=15,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["namespace"] == namespace
    assert body["chunks"], "expected the seeded chunk back through the admin forwarder"
    assert body["chunks"][0]["document_source"] == "e2e:query:1"


def test_admin_query_unseeded_kb_id_is_empty_not_error(throwaway_kb_id):
    """A kb_id nobody ingested for still round-trips cleanly (empty result,
    not a 5xx) -- the admin forwarder does no KB-catalog validation."""
    kb_id, _namespace = throwaway_kb_id  # never ingested into
    resp = httpx.post(
        f"{BENTO_API_BASE}/v1/admin/pg-raggraph/query",
        json={"kb_id": kb_id, "question": "anything", "mode": "naive"},
        timeout=15,
    )
    assert resp.status_code == 200
    assert resp.json()["chunks"] == []
