"""In-process LRU cache of recent QueryResults, addressable by result_id.

Lets a caller send the cheap summary as the answer while keeping the full
retrieved chunks available for a follow-up "give me more" — without
re-querying. In-process only; not persisted (by design, this mission).
"""

from __future__ import annotations

from collections import OrderedDict

from pg_raggraph.models import QueryResult


class ResultCache:
    """Bounded LRU map of result_id → QueryResult. maxsize=0 disables caching."""

    def __init__(self, maxsize: int = 128) -> None:
        self._maxsize = maxsize
        self._store: OrderedDict[str, QueryResult] = OrderedDict()

    def put(self, result_id: str, result: QueryResult) -> None:
        if self._maxsize <= 0:
            return
        if result_id in self._store:
            self._store.move_to_end(result_id)
        self._store[result_id] = result
        while len(self._store) > self._maxsize:
            self._store.popitem(last=False)

    def get(self, result_id: str) -> QueryResult | None:
        if result_id not in self._store:
            return None
        self._store.move_to_end(result_id)
        return self._store[result_id]
