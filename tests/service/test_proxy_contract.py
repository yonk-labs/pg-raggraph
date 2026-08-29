"""SERVICE-tier contract tests for bento-pg-raggraph-proxy (pg-raggraph
v0.9.0, bento commit 00346a7d integration).

Everything here targets a namespace private to the test run
(``test_pgrg_<ts>_<rand>``, see ``conftest.throwaway_namespace``) and never
touches the proxy's live config or any shared/benchmark namespace.
"""

from __future__ import annotations

import time

import pytest

from .conftest import proxy_request

pytestmark = pytest.mark.service


def test_health_reports_v0_9_0():
    resp = proxy_request("GET", "/health")
    assert resp["status"] == "ok"
    assert resp["library_version"].startswith("0.9")


def test_ingest_query_roundtrip(throwaway_namespace):
    ns = throwaway_namespace
    ingest = proxy_request(
        "POST",
        "/v1/ingest",
        {
            "records": [
                {
                    "text": (
                        "Incident INC-0001: the ingest worker crashed due to "
                        "disk pressure at 02:00 UTC."
                    ),
                    "source_id": "svc:roundtrip:1",
                }
            ],
            "namespace": ns,
            "skip_extraction": True,
        },
    )
    assert ingest["status"] == "completed"
    assert ingest["documents_written"] == 1
    assert ingest["chunks_written"] == 1

    query = proxy_request(
        "POST",
        "/v1/query",
        {"question": "what happened in INC-0001", "mode": "naive", "namespace": ns, "top_k": 5},
    )
    assert query["namespace"] == ns
    assert len(query["chunks"]) == 1
    assert query["chunks"][0]["document_source"] == "svc:roundtrip:1"


def test_status_and_indexes_reflect_ingest(throwaway_namespace):
    ns = throwaway_namespace
    proxy_request(
        "POST",
        "/v1/ingest",
        {
            "records": [
                {"text": "status/indexes contract smoke doc.", "source_id": "svc:status:1"}
            ],
            "namespace": ns,
            "skip_extraction": True,
        },
    )

    status = proxy_request("GET", f"/v1/status?namespace={ns}")
    assert status["namespace"] == ns
    assert status["documents"] == 1
    assert status["chunks"] == 1

    indexes = proxy_request("GET", f"/v1/indexes?namespace={ns}")
    assert indexes["namespace"] == ns
    assert "indexes" in indexes


def test_ask_returns_grounded_citation(throwaway_namespace):
    ns = throwaway_namespace
    proxy_request(
        "POST",
        "/v1/ingest",
        {
            "records": [
                {
                    "text": "Incident INC-0002: root cause was a stuck migration lock.",
                    "source_id": "svc:ask:1",
                }
            ],
            "namespace": ns,
            "skip_extraction": True,
        },
    )

    ask = proxy_request(
        "POST",
        "/v1/ask",
        {"query": "what was the root cause of INC-0002", "namespace": ns, "mode": "naive"},
    )
    assert ask["citations"], "expected at least one grounded citation"
    assert ask["citations"][0]["source"] == "svc:ask:1"


def test_ingest_start_and_status_job(throwaway_namespace):
    """The fire-and-poll ingest path (/v1/ingest/start + /v1/ingest/status/{job_id})."""
    ns = throwaway_namespace
    start = proxy_request(
        "POST",
        "/v1/ingest/start",
        {
            "records": [
                {"text": "Async ingest job smoke test document.", "source_id": "svc:job:1"}
            ],
            "namespace": ns,
            "skip_extraction": True,
        },
    )
    assert start["status"] == "running"
    job_id = start["job_id"]

    status = None
    for _ in range(20):
        status = proxy_request("GET", f"/v1/ingest/status/{job_id}")
        if status["status"] != "running":
            break
        time.sleep(0.25)
    else:
        pytest.fail(f"ingest job {job_id} did not complete in time: {status}")

    assert status["status"] == "succeeded", status
    assert status["documents_written"] == 1
    assert status["chunks_written"] == 1
