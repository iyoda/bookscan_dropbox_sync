from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

from .config import load_settings
from .util import parse_timestamp

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Bookscan→Dropbox 同期CLI")

# sync サブコマンド
sync_app = typer.Typer(help="Bookscan→Dropbox 同期CLI")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # 追加情報（extra）をJSONに含める（標準属性を除外）
        for k, v in record.__dict__.items():
            if k.startswith("_"):
                continue
            if k in ("name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
                     "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
                     "relativeCreated", "thread", "threadName", "processName", "process", "asctime"):
                continue
            payload[k] = v
        return json.dumps(payload, ensure_ascii=False)

class SecretMaskFilter(logging.Filter):
    def __init__(self, secrets: Optional[List[str]] | None = None) -> None:
        self.secrets = [s for s in (secrets or []) if s]

    def _mask(self, text: Any) -> str:
        s = str(text)
        for secret in self.secrets:
            try:
                if not secret:
                    continue
                if len(secret) < 8:
                    repl = "***"
                else:
                    repl = f"{secret[:2]}...{secret[-2:]}"
                s = s.replace(secret, repl)
            except Exception:
                continue
        return s

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = self._mask(record.msg)
            if record.args:
                if isinstance(record.args, tuple):
                    record.args = tuple(self._mask(a) for a in record.args)
                elif isinstance(record.args, dict):
                    record.args = {k: self._mask(v) for k, v in record.args.items()}
            for k, v in list(record.__dict__.items()):
                if isinstance(v, str):
                    record.__dict__[k] = self._mask(v)
        except Exception:
            pass
        return True

def _collect_secrets_from_settings(settings: Any) -> List[str]:
    names = [
        "DROPBOX_ACCESS_TOKEN",
        "DROPBOX_REFRESH_TOKEN",
        "DROPBOX_APP_SECRET",
        "BOOKSCAN_PASSWORD",
        "BOOKSCAN_TOTP_SECRET",
    ]
    secrets: List[str] = []
    for n in names:
        try:
            v = getattr(settings, n, None)
        except Exception:
            v = None
        if v:
            secrets.append(str(v))
    return secrets

def _setup_logging(json_log: bool = False, log_file: Optional[str] = None, secrets_to_mask: Optional[List[str]] = None) -> logging.Logger:
    """
    ログ設定を初期化する。
    - 標準出力（StreamHandler）
    - 任意でファイル出力（.logs/bds.log 等）
    - JSONログフォーマットの選択
    """
    logger = logging.getLogger("bds")
    logger.setLevel(logging.INFO)
    logger.propagate = False  # ルートへ伝播させない

    # 既存ハンドラをクリア（再呼び出し対策）
    if logger.handlers:
        for h in list(logger.handlers):
            logger.removeHandler(h)

    if secrets_to_mask:
        logger.addFilter(SecretMaskFilter(secrets_to_mask))

    if json_log:
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    # 標準出力
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    # ファイル出力
    if log_file:
        path = Path(log_file).expanduser()
        if not path.suffix:
            # ディレクトリが指定された場合は bds.log を補完
            path = path / "bds.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


def _filter_by_since(items: List[Dict[str, Any]], since: Optional[str]) -> List[Dict[str, Any]]:
    """
    updated_at が since 以降のものだけを残す（inclusive）。
    updated_at が欠落/不正な場合は除外しない（安全側: 同期対象に含める）。
    """
    if not since:
        return items
    t = parse_timestamp(since)
    if not t:
        return items
    out: List[Dict[str, Any]] = []
    for it in items:
        ts = parse_timestamp(str(it.get("updated_at") or ""))
        if ts is None or ts >= t:
            out.append(it)
    return out


def _apply_filters(
    items: List[Dict[str, Any]],
    exclude_ext: Optional[List[str]] = None,
    min_size: Optional[int] = None,
    max_size: Optional[int] = None,
    exclude_keyword: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    追加フィルタを適用する。
    - exclude_ext: 拡張子（先頭ドットは無視、大小無視）に一致するものを除外
    - min_size/max_size: サイズ（バイト）による除外。サイズ不明は除外しない（安全側）
    - exclude_keyword: タイトルに含む場合は除外（部分一致・大小無視）
    """
    exts = {str(e).lower().lstrip(".") for e in (exclude_ext or []) if str(e).strip()}
    keywords = [str(k).lower() for k in (exclude_keyword or []) if str(k).strip()]
    if not (exts or keywords or min_size is not None or max_size is not None):
        return items

    out: List[Dict[str, Any]] = []
    for it in items:
        # ext 判定
        ext = str(it.get("ext") or "").lower().lstrip(".")
        if ext and exts and ext in exts:
            continue

        # size 判定
        size_val = it.get("size")
        size: Optional[int]
        try:
            size = int(size_val)
        except Exception:
            size = None

        if min_size is not None and size is not None and size < min_size:
            continue
        if max_size is not None and size is not None and size > max_size:
            continue

        # keyword 判定（タイトル）
        title = str(it.get("title") or "").lower()
        if keywords and any(k in title for k in keywords):
            continue

        out.append(it)
    return out


@sync_app.callback(invoke_without_command=True)
def sync(
    dry_run: bool = typer.Option(False, help="Dropboxへアップロードせず計画のみ表示"),
    since: Optional[str] = typer.Option(
        None,
        "--since",
        help="更新日でフィルタ（YYYY-MM-DD など）。指定日以降のみ対象",
    ),
    exclude_ext: Optional[List[str]] = typer.Option(
        None,
        "--exclude-ext",
        help="除外: 拡張子（繰り返し指定可）。例: --exclude-ext pdf --exclude-ext zip",
    ),
    min_size: Optional[int] = typer.Option(None, "--min-size", help="除外: 指定バイト数未満を除外"),
    max_size: Optional[int] = typer.Option(None, "--max-size", help="除外: 指定バイト数より大を除外"),
    exclude_keyword: Optional[List[str]] = typer.Option(
        None,
        "--exclude-keyword",
        help="除外: タイトルに含むキーワード（繰り返し指定可）",
    ),
    json_log: bool = typer.Option(False, "--json-log", help="ログをJSON形式で出力"),
    log_file: Optional[str] = typer.Option(
        None,
        "--log-file",
        help="ログをファイルへ出力（パス指定、未指定時は出力しない。例: .logs/bds.log または .logs/）",
    ),
) -> None:
    """
    M1 最小実装:
    - 設定読込/バリデーション
    - Bookscan一覧を取得（未実装時は空リスト）
    - Stateとの差分計画を作成し、dry-run時は一覧表示
    - 非dry-run時は転送実行
    """
    try:
        settings = load_settings()
        settings.validate_for_m1(dry_run=dry_run)
    except ValueError as e:
        typer.secho(f"設定エラー: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    logger = _setup_logging(json_log=json_log, log_file=log_file, secrets_to_mask=_collect_secrets_from_settings(settings))
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

    items = _filter_by_since(items, since)
    items = _apply_filters(
        items,
        exclude_ext=exclude_ext,
        min_size=min_size,
        max_size=max_size,
        exclude_keyword=exclude_keyword,
    )

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
    try:
        engine.run(plan, dry_run=False)
    except Exception as e:
        typer.secho(f"実行エラー: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
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
    since: Optional[str] = typer.Option(None, help="更新日でフィルタ（YYYY-MM-DD など）"),
    exclude_ext: Optional[List[str]] = typer.Option(
        None,
        "--exclude-ext",
        help="除外: 拡張子（繰り返し指定可）。例: --exclude-ext pdf --exclude-ext zip",
    ),
    min_size: Optional[int] = typer.Option(None, "--min-size", help="除外: 指定バイト数未満を除外"),
    max_size: Optional[int] = typer.Option(None, "--max-size", help="除外: 指定バイト数より大を除外"),
    exclude_keyword: Optional[List[str]] = typer.Option(
        None,
        "--exclude-keyword",
        help="除外: タイトルに含むキーワード（繰り返し指定可）",
    ),
    json_log: bool = typer.Option(False, "--json-log", help="ログをJSON形式で出力"),
    log_file: Optional[str] = typer.Option(
        None, "--log-file", help="ログをファイルへ出力（パス指定、未指定時は出力しない）"
    ),
) -> None:
    """
    取得一覧（Bookscan）または保存済みStateを表示する簡易コマンド。
    - source=bookscan: BOOKSCAN_DEBUG_HTML_PATH や HTTPテンプレートに従い一覧を取得
    - source=state: StateStore から既存の同期情報を表示
    """
    settings = load_settings()
    logger = _setup_logging(json_log=json_log, log_file=log_file, secrets_to_mask=_collect_secrets_from_settings(settings))

    if source.lower() == "state":
        from .state_store import StateStore

        store = StateStore(settings)
        state = store.read()
        items = state.get("items", {})
        items = items if isinstance(items, dict) else {}

        # since フィルタ（updated_at 基準、inclusive）。不正/欠落は除外せず通す。
        filtered = items
        if since:
            t = parse_timestamp(since)
            if t:
                tmp: Dict[str, Any] = {}
                for book_id, meta in items.items():
                    ts = parse_timestamp(str(meta.get("updated_at") or ""))
                    if ts is None or ts >= t:
                        tmp[book_id] = meta
                filtered = tmp

        typer.echo(f"[LIST] state items: {len(filtered)}")
        for book_id, meta in filtered.items():
            typer.echo(
                f"[STATE] book_id={book_id} updated_at={meta.get('updated_at','')} "
                f"size={meta.get('size')} path={meta.get('dropbox_path','')}"
            )
        logger.info("list state complete count=%d", len(filtered))
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
    items = _filter_by_since(items, since)
    items = _apply_filters(
        items,
        exclude_ext=exclude_ext,
        min_size=min_size,
        max_size=max_size,
        exclude_keyword=exclude_keyword,
    )
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
