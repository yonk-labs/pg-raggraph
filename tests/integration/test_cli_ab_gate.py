"""SC-015..SC-017: pgrg ab-gate run CLI subcommand."""

from pathlib import Path

from click.testing import CliRunner

from pg_raggraph.cli import main


def test_ab_gate_run_help_listed():
    """SC-015: `pgrg ab-gate --help` lists the `run` subcommand."""
    runner = CliRunner()
    result = runner.invoke(main, ["ab-gate", "--help"])
    assert result.exit_code == 0, result.output
    assert "run" in result.output


def test_corpus_gold_pairing_mismatch_fails():
    """SC-016: two --corpus flags + one --gold flag ⇒ click.BadParameter."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "ab-gate",
            "run",
            "--corpus",
            "A",
            "--corpus",
            "B",
            "--gold",
            "/tmp/a.yaml",
            "--mode",
            "naive_vector",
            "--out",
            "/tmp/out",
        ],
    )
    assert result.exit_code != 0
    assert "pairing" in result.output.lower() or "pair" in result.output.lower()


def test_unknown_mode_rejected():
    """SC-017: --mode bogus_mode ⇒ non-zero exit."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "ab-gate",
            "run",
            "--corpus",
            "A",
            "--gold",
            "/tmp/a.yaml",
            "--mode",
            "bogus_mode",
            "--out",
            "/tmp/out",
        ],
    )
    assert result.exit_code != 0


def test_known_modes_accepted_at_parse_time(tmp_path: Path):
    """SC-017 complement: known modes pass parse-time validation."""
    runner = CliRunner()
    bogus_gold = tmp_path / "does-not-exist.yaml"
    result = runner.invoke(
        main,
        [
            "ab-gate",
            "run",
            "--corpus",
            "A",
            "--gold",
            str(bogus_gold),
            "--mode",
            "naive_vector",
            "--mode",
            "graph_leg",
            "--mode",
            "hybrid",
            "--out",
            str(tmp_path / "out"),
        ],
    )
    out = (result.output or "") + (str(result.exception) if result.exception else "")
    assert "Invalid value" not in out or "mode" not in out.lower(), (
        f"a known mode was rejected at parse time: {out}"
    )
