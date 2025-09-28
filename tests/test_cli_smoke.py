from __future__ import annotations

from typer.testing import CliRunner

from bds.cli import app


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # ヘルプの概要文が含まれること
    assert "Bookscan→Dropbox 同期CLI" in result.stdout


def test_sync_dry_run_smoke() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["sync", "--dry-run"])
    assert result.exit_code == 0
    # ドライランの計画出力が表示されること
    assert "[DRY-RUN] planned actions:" in result.stdout
