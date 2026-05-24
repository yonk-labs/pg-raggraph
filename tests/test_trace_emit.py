import inspect

from pg_raggraph import retrieval


def test_query_accepts_optional_trace_emit_defaulting_none():
    sig = inspect.signature(retrieval.query)
    assert "trace_emit" in sig.parameters, "query() must accept trace_emit"
    assert sig.parameters["trace_emit"].default is None, "trace_emit must default to None"
