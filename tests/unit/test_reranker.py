"""Unit tests for the reranker module.

Currently focused on the import-error contract (PR-305): when fastembed's
cross-encoder submodule is missing, the user must get an actionable
`ImportError` with an install hint, not a bare `ModuleNotFoundError` from
deep inside the import chain.
"""

from __future__ import annotations

import builtins

import pytest

from pg_raggraph.reranker import FastEmbedReranker


def test_load_raises_actionable_importerror_when_cross_encoder_missing(monkeypatch):
    """PR-305: simulate a missing fastembed.rerank.cross_encoder. The
    raised ImportError must (a) be ImportError (not bare
    ModuleNotFoundError leaking from the chain), (b) name the missing
    module, and (c) include an actionable `pip install` hint so the
    user knows how to fix it.
    """
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "fastembed.rerank.cross_encoder":
            raise ImportError("No module named fastembed.rerank.cross_encoder")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    r = FastEmbedReranker()
    with pytest.raises(ImportError) as exc_info:
        r._load()

    msg = str(exc_info.value)
    # Actionable install hint must be present.
    assert "pip install" in msg
    assert "fastembed" in msg
    # The original error must be chained so a debugger sees the full
    # provenance via `__cause__`.
    assert exc_info.value.__cause__ is not None


def test_load_is_idempotent_after_success(monkeypatch):
    """PR-305 regression guard: once _load() succeeds, calling it again
    must be a no-op — no re-import, no re-instantiate. Otherwise
    every query pays the model-load cost."""

    class _StubModel:
        def rerank(self, q, texts):
            return [0.5] * len(texts)

    r = FastEmbedReranker()
    # Pretend the model is already loaded.
    r._model = _StubModel()

    # _load should bail out without touching imports at all. We can
    # verify by patching the import to raise — if _load tried to
    # import, this test would fail with ImportError.
    real_import = builtins.__import__

    def trap_import(name, *args, **kwargs):
        if name == "fastembed.rerank.cross_encoder":
            raise AssertionError("re-imported after load — should be cached")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", trap_import)
    r._load()  # must not raise
    assert r._model is not None
