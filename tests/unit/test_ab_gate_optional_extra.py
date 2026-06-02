"""Unit test for the missing-extra ImportError UX (SC-017)."""

import sys
from unittest.mock import patch

import pytest


def test_missing_llm_judge_yields_clear_import_error():
    """SC-017: when llm_judge is unimportable, the seam raises with install instructions."""
    from pg_raggraph.ab_gate import judge_seam

    # Force-reload the seam module with llm_judge made unimportable.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def _import_killer(name, *args, **kwargs):
        if name == "llm_judge" or name.startswith("llm_judge."):
            raise ImportError(f"No module named {name!r} (simulated)")
        return real_import(name, *args, **kwargs)

    # Drop cached llm_judge submodules so a re-import is forced.
    for mod_name in list(sys.modules):
        if mod_name == "llm_judge" or mod_name.startswith("llm_judge."):
            del sys.modules[mod_name]

    with patch("builtins.__import__", side_effect=_import_killer):
        with pytest.raises(ImportError) as exc_info:
            judge_seam._chunkshop_judge_config_to_llm_judge_provider(
                {"provider": {"kind": "mock"}}
            )

    msg = str(exc_info.value)
    assert "pg-raggraph[ab-gate]" in msg or "pg_raggraph[ab-gate]" in msg, (
        f"missing-extra error must include the install hint; got: {msg}"
    )
