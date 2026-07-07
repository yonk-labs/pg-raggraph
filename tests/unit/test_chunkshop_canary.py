"""Canary for the chunkshop private seams the bridge depends on (AAT-005).

``chunkshop_bridge.CorpusCodeGraph`` spills call sites by reading/clearing/
reassigning chunkshop's underscore-private ``_pending_calls`` and
``_pending_class_edges`` lists — the #79 OOM fix. Those attrs are private:
a routine chunkshop refactor can remove them and the bridge would degrade
to unbounded in-memory accumulation.

This module makes that failure a CI failure instead of a production OOM:
a lockfile bump to a chunkshop that moved the seams fails here, in CI's
``--all-extras`` lane (and locally via the dev extra), before any release.

Skips only when chunkshop is not installed at all.
"""

import logging

import pytest

pytest.importorskip("chunkshop")

from pg_raggraph.chunkshop_bridge import CorpusCodeGraph  # noqa: E402


def _load_real_extractor():
    from chunkshop.config import CodeRelationshipsExtractor as CodeRelCfg
    from chunkshop.extractors import load_extractor

    return load_extractor(CodeRelCfg(type="code_relationships"))


def test_private_spill_seams_exist():
    """The exact attrs/methods CorpusCodeGraph touches, probed on the real
    extractor. If this fails after a chunkshop bump, chunkshop moved internals
    pg-raggraph depends on — fix the bridge before raising the pyproject cap."""
    ext = _load_real_extractor()
    assert callable(ext.extract), "chunkshop extractor lost .extract()"
    assert callable(ext.finalize), "chunkshop extractor lost .finalize()"
    for attr in ("_pending_calls", "_pending_class_edges"):
        assert isinstance(getattr(ext, attr, None), list), (
            f"chunkshop moved private seam {attr!r} — the #79 OOM spill guard "
            "in chunkshop_bridge.CorpusCodeGraph no longer engages"
        )


def test_corpus_code_graph_is_spillable():
    """End-to-end: the bridge itself must come up available AND spillable
    against the installed chunkshop."""
    graph = CorpusCodeGraph()
    assert graph.available, "chunkshop extractor failed to load through the bridge"
    assert graph.spillable, "bridge is degrading to in-memory accumulation (#79 path)"


def test_non_spillable_extractor_warns_loudly(monkeypatch, caplog):
    """When the seams are missing, init must warn (once) with the chunkshop
    version — never silently degrade."""

    class _NoSeams:
        def extract(self, *a, **kw):  # pragma: no cover - never called
            pass

        def finalize(self, *a, **kw):  # pragma: no cover - never called
            return []

    import chunkshop.extractors

    monkeypatch.setattr(chunkshop.extractors, "load_extractor", lambda cfg: _NoSeams())

    from importlib.metadata import version

    with caplog.at_level(logging.WARNING, logger="pg_raggraph.chunkshop_bridge"):
        graph = CorpusCodeGraph()

    assert graph.available
    assert not graph.spillable
    warnings = [r for r in caplog.records if "moved internals" in r.getMessage()]
    assert len(warnings) == 1
    assert version("chunkshop") in warnings[0].getMessage()
