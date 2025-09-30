from __future__ import annotations

from typer.testing import CliRunner

from bds.cli import app


def test_sync_without_token_returns_exit_code_2() -> None:
    runner = CliRunner()
    # 明示的に空文字を渡して、環境に既存のトークンがあっても上書きする
    env = {"DROPBOX_ACCESS_TOKEN": ""}
    result = runner.invoke(app, ["sync"], env=env)
    assert result.exit_code == 2
    assert "設定エラー:" in result.stdout
