import json

import pytest

from pg_raggraph.profiles import load_profile_calibration, resolve_profile


def test_loads_f_informed_ladder_from_calibration_file():
    calibration = load_profile_calibration("benchmarks/matrix/profile_calibration.json")

    assert calibration.ladder_version == "f-informed-1"
    assert len(calibration.rungs) == 7
    assert [r.name for r in calibration.rungs] == [
        "cheap",
        "cheap_plus",
        "lean",
        "balanced",
        "rich",
        "stacked",
        "accurate",
    ]
    assert calibration.raw_escape_hatch == {
        "context_strategy": "classic_chunks",
        "top_k": 25,
    }


def test_calibrated_aggregate_tokens_and_accuracy_are_monotonic():
    calibration = load_profile_calibration("benchmarks/matrix/profile_calibration.json")

    tokens = [r.est_tokens["aggregate"] for r in calibration.rungs]
    accuracy = [r.est_accuracy["aggregate"] for r in calibration.rungs]

    assert tokens == sorted(tokens)
    assert accuracy == sorted(accuracy)


def test_resolve_named_integer_float_and_strategy_profiles():
    calibration = load_profile_calibration("benchmarks/matrix/profile_calibration.json")

    assert resolve_profile("balanced", calibration=calibration).index == 3
    assert resolve_profile("accurate", calibration=calibration).context_strategy == (
        "full_selected_docs@10"
    )
    assert resolve_profile(0, calibration=calibration).name == "cheap"
    assert resolve_profile(6, calibration=calibration).name == "accurate"
    assert resolve_profile(0.0, calibration=calibration).name == "cheap"
    assert resolve_profile(0.5, calibration=calibration).name == "balanced"
    assert resolve_profile("0.5", calibration=calibration).name == "balanced"
    assert resolve_profile(1.0, calibration=calibration).name == "accurate"
    assert resolve_profile(
        "doc_and_chunk_summary_toc_facts_plus_top5",
        calibration=calibration,
    ).name == "balanced"


def test_resolve_raw_escape_hatch_is_outside_ladder():
    calibration = load_profile_calibration("benchmarks/matrix/profile_calibration.json")

    spec = resolve_profile("raw", calibration=calibration)

    assert spec.raw is True
    assert spec.index is None
    assert spec.context_strategy == "classic_chunks"
    assert spec.top_k == 25


def test_invalid_profile_values_raise_clear_errors():
    calibration = load_profile_calibration("benchmarks/matrix/profile_calibration.json")

    with pytest.raises(ValueError, match="unknown retrieval profile"):
        resolve_profile("fastest", calibration=calibration)
    with pytest.raises(ValueError, match="range 0..6"):
        resolve_profile(7, calibration=calibration)
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        resolve_profile(1.1, calibration=calibration)
    with pytest.raises(ValueError, match="boolean"):
        resolve_profile(True, calibration=calibration)


def test_loader_falls_back_when_file_is_missing(tmp_path):
    missing = tmp_path / "missing-profile-calibration.json"

    calibration = load_profile_calibration(missing)

    assert calibration.source_path is None
    assert calibration.ladder_version == "f-informed-1"
    assert resolve_profile(None, calibration=calibration).name == "balanced"


def test_loader_rejects_non_contiguous_indexes(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "ladder_version": "bad",
                "rungs": [
                    {
                        "index": 1,
                        "name": "bad",
                        "strategy": "classic_chunks",
                        "match": {"context_strategy": "classic_chunks", "top_k": 25},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="contiguous"):
        load_profile_calibration(path)
