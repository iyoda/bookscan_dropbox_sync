from __future__ import annotations

from typing import Any

from typer.testing import CliRunner

from bds.cli import app


def test_cli_list_since_filters_sample_html() -> None:
    runner = CliRunner()
    env = {"BOOKSCAN_DEBUG_HTML_PATH": "samples/bookscan_list_sample.html"}
    result = runner.invoke(app, ["list", "--since", "2024-08-12"], env=env)
    assert result.exit_code == 0
    # 2024-08-12 以降にフィルタされ、サンプルは 1 件になる
    assert "[LIST] bookscan items: 1" in result.stdout
    # 古い方（2024-08-10T12:00:00Z）は表示されない
    assert "updated=2024-08-10T12:00:00Z" not in result.stdout


def test_cli_list_since_invalid_returns_all() -> None:
    runner = CliRunner()
    env = {"BOOKSCAN_DEBUG_HTML_PATH": "samples/bookscan_list_sample.html"}
    result = runner.invoke(app, ["list", "--since", "invalid-date"], env=env)
    assert result.exit_code == 0
    # 無効なsinceはフィルタしない（安全側）
    assert "[LIST] bookscan items: 2" in result.stdout


def test_sync_dry_run_since_filters_plan_count(tmp_path: Any) -> None:
    runner = CliRunner()
    env = {
        "BOOKSCAN_DEBUG_HTML_PATH": "samples/bookscan_list_sample.html",
        "STATE_BACKEND": "json",
        "STATE_PATH": str(tmp_path / "state.json"),
    }
    result = runner.invoke(app, ["sync", "--dry-run", "--since", "2024-08-12"], env=env)
    assert result.exit_code == 0
    # 計画（plan）の件数がフィルタ結果を反映して 1 件になる
    assert "[DRY-RUN] planned actions: 1" in result.stdout
