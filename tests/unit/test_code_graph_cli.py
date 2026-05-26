from click.testing import CliRunner

from pg_raggraph.cli import main


def test_code_impact_command_registered():
    runner = CliRunner()
    result = runner.invoke(main, ["code-impact", "--help"])
    assert result.exit_code == 0
    assert "--depth" in result.output
    assert "--json" in result.output
