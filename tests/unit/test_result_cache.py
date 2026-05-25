"""Unit tests for the in-process LRU result cache (SC-202, SC-205)."""

from __future__ import annotations

from pg_raggraph.models import QueryResult
from pg_raggraph.result_cache import ResultCache


def test_put_get_roundtrip():
    c = ResultCache(maxsize=4)
    r = QueryResult(summary="s")
    c.put("id1", r)
    assert c.get("id1") is r


def test_missing_returns_none():
    assert ResultCache(maxsize=4).get("nope") is None


def test_lru_eviction():
    c = ResultCache(maxsize=2)
    c.put("a", QueryResult())
    c.put("b", QueryResult())
    c.get("a")  # touch a → b now LRU
    c.put("c", QueryResult())  # evicts b
    assert c.get("b") is None
    assert c.get("a") is not None
    assert c.get("c") is not None


def test_maxsize_zero_disables():
    c = ResultCache(maxsize=0)
    c.put("a", QueryResult())
    assert c.get("a") is None
