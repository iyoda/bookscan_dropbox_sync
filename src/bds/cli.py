from __future__ import annotations

import logging
import typer

from .config import load_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Bookscan→Dropbox 同期CLI")


@app.command(help="Bookscan→Dropbox 同期CLI")
def sync(
    dry_run: bool = typer.Option(
        False, "--dry-run", is_flag=True, help="Dropboxへアップロードせず計画のみ表示"
    ),
) -> None:
    """
    M1 最小実装:
    - 設定読込/バリデーション
    - Bookscan一覧を取得（未実装時は空リスト）
    - Stateとの差分計画を作成し、dry-run時は一覧表示
    - 非dry-run時は転送実行
    """
    settings = load_settings()
    settings.validate_for_m1(dry_run=dry_run)

    # ロガー設定（M1: 簡易）
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("bds")
    logger.info("sync start dry_run=%s", dry_run)

    # 依存の遅延インポート（dry-run時はDropbox SDKを読み込まない）
    from .state_store import StateStore
    from .sync_planner import SyncPlanner
    from .bookscan_client import BookscanClient

    state_store = StateStore(settings)
    state = state_store.read()

    # Bookscan 認証と一覧取得（未実装でも動くようにフォールバック）
    bookscan = BookscanClient(settings)
    try:
        bookscan.login()
    except NotImplementedError:
        pass

    try:
        items = bookscan.list_downloadables()
    except NotImplementedError:
        items = []

    planner = SyncPlanner(settings, state)
    plan = planner.plan(items)

    if dry_run:
        typer.echo(f"[DRY-RUN] planned actions: {len(plan)}")
        root = settings.DROPBOX_DEST_ROOT.rstrip("/")
        for entry in plan:
            if entry.get("action") != "upload":
                continue
            rel = str(entry.get("relpath") or entry.get("filename") or "")
            dest = f"{root}/{rel}" if rel and root else (rel or root)
            typer.echo(
                f"[DRY-RUN] upload book_id={entry.get('book_id')} -> {dest} "
                f"(title='{entry.get('title','')}', size={entry.get('size')}, ext={entry.get('ext')})"
            )
        logger.info("dry-run complete actions=%d", len(plan))
        return

    # 本実行（非dry-run）
    try:
        from .dropbox_client import DropboxClient
        from .transfer import TransferEngine
    except Exception as e:
        typer.secho(f"初期化エラー: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    dropbox = DropboxClient(settings)
    engine = TransferEngine(settings, bookscan, dropbox, state_store)
    engine.run(plan, dry_run=False)
    typer.echo("sync: 完了")
    logger.info("sync complete")


if __name__ == "__main__":
    app()
