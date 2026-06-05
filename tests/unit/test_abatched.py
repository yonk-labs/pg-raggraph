"""Bounded-batch iterator normalization for streaming ingest (issue #46).

`_abatched` turns a sync iterable, a sync generator, or an async iterable into
an async stream of bounded-size lists — without ever materializing the whole
input. This is the primitive that makes `ingest_records` O(batch_size).
"""

from __future__ import annotations

import pytest

from pg_raggraph import _abatched


async def _collect(records, n):
    return [batch async for batch in _abatched(records, n)]


@pytest.mark.asyncio
async def test_sync_list_splits_into_bounded_batches():
    batches = await _collect([1, 2, 3, 4, 5], 2)
    assert batches == [[1, 2], [3, 4], [5]]


@pytest.mark.asyncio
async def test_batch_size_larger_than_input_yields_one_batch():
    batches = await _collect([1, 2, 3], 10)
    assert batches == [[1, 2, 3]]


@pytest.mark.asyncio
async def test_batch_size_one_yields_singletons():
    batches = await _collect([1, 2, 3], 1)
    assert batches == [[1], [2], [3]]


@pytest.mark.asyncio
async def test_empty_input_yields_no_batches():
    assert await _collect([], 4) == []


@pytest.mark.asyncio
async def test_sync_generator_is_pulled_lazily():
    """At most one batch worth of items is ever pulled ahead of consumption."""
    pulled = []

    def gen():
        for i in range(5):
            pulled.append(i)
            yield i

    high_water = 0
    consumed = 0
    async for batch in _abatched(gen(), 2):
        consumed += len(batch)
        # Never more than one batch pulled beyond what we've consumed.
        high_water = max(high_water, len(pulled) - consumed)
    assert high_water <= 2, f"pulled too far ahead: {high_water}"


@pytest.mark.asyncio
async def test_async_iterable_is_batched():
    async def agen():
        for i in range(5):
            yield i

    batches = await _collect(agen(), 2)
    assert batches == [[0, 1], [2, 3], [4]]
