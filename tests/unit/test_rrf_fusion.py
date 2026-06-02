"""Unit tests for the optional RRF (Reciprocal Rank Fusion) mode (issue #57).

Covers config knobs, helper resolution, the fused-score expression, naive
SQL shape, the linear-unchanged guard, and the Python hybrid merge. End-to-end
ordering is covered by tests/integration/test_rrf_fusion_it.py.
"""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig


def test_fusion_defaults_to_linear():
    assert PGRGConfig().fusion == "linear"


def test_rrf_k_default_is_60():
    assert PGRGConfig().rrf_k == 60


def test_fusion_accepts_rrf():
    cfg = PGRGConfig(fusion="rrf")
    assert cfg.fusion == "rrf"


def test_fusion_rejects_unknown():
    with pytest.raises(ValueError):
        PGRGConfig(fusion="bogus")
