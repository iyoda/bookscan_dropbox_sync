from __future__ import annotations

import typer

from .config import load_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Bookscan→Dropbox 同期CLI")


@app.command()
def sync(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Dropboxへアップロードせず計画のみ表示"
    ),
) -> None:
    """
    MVP実装前のプレースホルダー（M1で実装予定）
    """
    settings = load_settings()
    typer.echo("sync: 未実装 (M1で実装予定)")
    typer.echo(f"dry_run={dry_run}")
    typer.echo(f"DROPBOX_DEST_ROOT={settings.DROPBOX_DEST_ROOT}")


if __name__ == "__main__":
    app()
