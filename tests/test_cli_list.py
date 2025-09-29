from __future__ import annotations

from typer.testing import CliRunner

from bds.cli import app


def test_cli_list_bookscan_from_debug_html() -> None:
    runner = CliRunner()
    env = {"BOOKSCAN_DEBUG_HTML_PATH": "samples/bookscan_list_sample.html"}
    result = runner.invoke(app, ["list"], env=env)
    assert result.exit_code == 0
    # サンプルHTMLは2件
    assert "[LIST] bookscan items: 2" in result.stdout


def test_cli_list_state_empty(tmp_path) -> None:
    runner = CliRunner()
    state_path = tmp_path / "state.json"
    env = {
        "STATE_BACKEND": "json",
        "STATE_PATH": str(state_path),
    }
    result = runner.invoke(app, ["list", "--source", "state"], env=env)
    assert result.exit_code == 0
    assert "[LIST] state items: 0" in result.stdout
