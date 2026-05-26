from click.testing import CliRunner

from pg_raggraph.cli import main


def test_migrate_embeddings_group_registered():
    runner = CliRunner()
    result = runner.invoke(main, ["migrate-embeddings", "--help"])
    assert result.exit_code == 0
    for sub in ("prepare", "backfill", "build-index", "status", "cutover", "finalize"):
        assert sub in result.output
