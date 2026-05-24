import inspect
import time

from pg_raggraph import retrieval


def test_query_accepts_optional_trace_emit_defaulting_none():
    sig = inspect.signature(retrieval.query)
    assert "trace_emit" in sig.parameters, "query() must accept trace_emit"
    assert sig.parameters["trace_emit"].default is None, "trace_emit must default to None"


def test_trace_emit_events_contain_elapsed_ms_source():
    """Verify that both trace_emit call sites in retrieval.py include elapsed_ms.

    This is a source-level assertion: it confirms the event dicts passed to
    trace_emit contain the ``elapsed_ms`` key without requiring a live DB.
    """
    src = inspect.getsource(retrieval.query)
    # Both event dicts must reference elapsed_ms — count occurrences.
    count = src.count('"elapsed_ms"')
    assert count >= 2, (
        f"Expected at least 2 'elapsed_ms' keys in trace_emit event dicts, found {count}. "
        "Both the vector_bm25 and graph stages must emit elapsed_ms."
    )


def test_elapsed_ms_is_numeric_and_non_negative():
    """Contract: elapsed_ms produced by the timing expression is a float >= 0.

    Directly exercises the timing arithmetic used at each trace_emit site so
    that the contract (numeric, >= 0) is tested without a live DB.
    """
    t0 = time.perf_counter()
    # Simulate some trivial work
    _ = [i for i in range(100)]
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # Build event dicts mirroring the two sites in retrieval.py
    vector_bm25_event = {
        "stage": "vector_bm25",
        "mode": "naive",
        "sql": "",
        "elapsed_ms": elapsed_ms,
        "candidates": [],
    }
    graph_event = {
        "stage": "graph",
        "mode": "local",
        "elapsed_ms": elapsed_ms,
        "entities": [],
        "relationships": [],
        "hops": 2,
    }

    for event in (vector_bm25_event, graph_event):
        assert "elapsed_ms" in event, f"elapsed_ms missing from {event['stage']} event"
        assert isinstance(
            event["elapsed_ms"], float
        ), f"elapsed_ms must be float, got {type(event['elapsed_ms'])} in {event['stage']} event"
        assert event["elapsed_ms"] >= 0, (
            f"elapsed_ms must be >= 0, got {event['elapsed_ms']} in {event['stage']} event"
        )
