from __future__ import annotations

from typing import Any

from typer.testing import CliRunner

from bds.cli import app


def test_cli_list_exclude_ext_pdf_makes_zero() -> None:
    runner = CliRunner()
    env = {"BOOKSCAN_DEBUG_HTML_PATH": "samples/bookscan_list_sample.html"}
    # サンプルは2件とも pdf 拡張子（.pdf / pdf）
    result = runner.invoke(app, ["list", "--exclude-ext", "pdf"], env=env)
    assert result.exit_code == 0
    assert "[LIST] bookscan items: 0" in result.stdout


def test_cli_list_min_size_filters_small_items() -> None:
    runner = CliRunner()
    env = {"BOOKSCAN_DEBUG_HTML_PATH": "samples/bookscan_list_sample.html"}
    # min-size=5000 で 2048 の方が除外され、12345 の1件のみ
    result = runner.invoke(app, ["list", "--min-size", "5000"], env=env)
    assert result.exit_code == 0
    assert "[LIST] bookscan items: 1" in result.stdout
    # 残るのは size=12345 の方
    assert "size=12345" in result.stdout
    assert "size=2048" not in result.stdout


def test_cli_list_max_size_filters_large_items() -> None:
    runner = CliRunner()
    env = {"BOOKSCAN_DEBUG_HTML_PATH": "samples/bookscan_list_sample.html"}
    # max-size=3000 で 12345 の方が除外され、2048 の1件のみ
    result = runner.invoke(app, ["list", "--max-size", "3000"], env=env)
    assert result.exit_code == 0
    assert "[LIST] bookscan items: 1" in result.stdout
    assert "size=2048" in result.stdout
    assert "size=12345" not in result.stdout


def test_cli_list_exclude_keyword_case_insensitive() -> None:
    runner = CliRunner()
    env = {"BOOKSCAN_DEBUG_HTML_PATH": "samples/bookscan_list_sample.html"}
    # タイトルに 'Work' を含む（大小無視・部分一致）ものを除外 => 1件のみ残る
    result = runner.invoke(app, ["list", "--exclude-keyword", "work"], env=env)
    assert result.exit_code == 0
    assert "[LIST] bookscan items: 1" in result.stdout
    # 除外されたタイトルが出力に含まれないこと
    assert "Second: Work?" not in result.stdout


def test_sync_dry_run_min_size_reflects_in_plan_count(tmp_path: Any) -> None:
    runner = CliRunner()
    env = {
        "BOOKSCAN_DEBUG_HTML_PATH": "samples/bookscan_list_sample.html",
        "STATE_BACKEND": "json",
        "STATE_PATH": str(tmp_path / "state.json"),
    }
    result = runner.invoke(app, ["sync", "--dry-run", "--min-size", "5000"], env=env)
    assert result.exit_code == 0
    # フィルタ結果が計画件数に反映され 1 件
    assert "[DRY-RUN] planned actions: 1" in result.stdout
