from __future__ import annotations

import logging
import typer

from .config import load_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Bookscan→Dropbox 同期CLI")

# sync サブコマンド
sync_app = typer.Typer(help="Bookscan→Dropbox 同期CLI")


@sync_app.callback(invoke_without_command=True)
def sync(
    dry_run: bool = typer.Option(False, help="Dropboxへアップロードせず計画のみ表示"),
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


# list サブコマンド（M2の一部を前倒し：取得一覧/State表示）
list_app = typer.Typer(help="取得一覧/State表示")


@list_app.callback(invoke_without_command=True)
def list_cmd(
    source: str = typer.Option(
        "bookscan",
        "-s",
        "--source",
        help="表示対象: 'bookscan'（取得一覧） もしくは 'state'（保存済みState）",
    ),
) -> None:
    """
    取得一覧（Bookscan）または保存済みStateを表示する簡易コマンド。
    - source=bookscan: BOOKSCAN_DEBUG_HTML_PATH や HTTPテンプレートに従い一覧を取得
    - source=state: StateStore から既存の同期情報を表示
    """
    settings = load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("bds")

    if source.lower() == "state":
        from .state_store import StateStore

        store = StateStore(settings)
        state = store.read()
        items = state.get("items", {})
        items = items if isinstance(items, dict) else {}
        typer.echo(f"[LIST] state items: {len(items)}")
        for book_id, meta in items.items():
            typer.echo(
                f"[STATE] book_id={book_id} updated_at={meta.get('updated_at','')} "
                f"size={meta.get('size')} path={meta.get('dropbox_path','')}"
            )
        logger.info("list state complete count=%d", len(items))
        return

    # source=bookscan（既定）
    from .bookscan_client import BookscanClient

    client = BookscanClient(settings)
    try:
        client.login()
    except Exception:
        pass

    try:
        items = client.list_downloadables()
    except Exception:
        items = []
    typer.echo(f"[LIST] bookscan items: {len(items)}")
    for it in items:
        typer.echo(
            f"[BOOKSCAN] id={it.get('id')} title='{it.get('title','')}' ext={it.get('ext')} "
            f"size={it.get('size')} updated={it.get('updated_at')}"
        )
    logger.info("list bookscan complete count=%d", len(items))
    return


app.add_typer(sync_app, name="sync")
app.add_typer(list_app, name="list")

if __name__ == "__main__":
    app()
