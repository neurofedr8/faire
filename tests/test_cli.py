from click.testing import CliRunner

from faire.cli import main


def test_help():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "DMP" in result.output
