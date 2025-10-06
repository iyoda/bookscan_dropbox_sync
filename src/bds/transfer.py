from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Protocol

from .config import Settings
from .failure_store import FailureStore
from .state_store import StateStore
from .sync_planner import PlanEntry
from .util import call_with_retry, create_retrying_from_settings, dropbox_content_hash


class BookscanClientProtocol(Protocol):
    def download(self, item: dict[str, Any], dest_path: str) -> None: ...


class DropboxClientProtocol(Protocol):
    def ensure_folder(self, path: str) -> None: ...
    def get_metadata(self, dropbox_path: str) -> dict[str, object]: ...
    def upload_file(self, local_path: str, dropbox_path: str) -> None: ...


class TransferEngine:
    """
    ダウンロード→一時フォルダ→Dropboxアップロードを担うエンジン（M1 最小実装）
    - 単一スレッドで直列実行（小サイズ前提）
    - 成功時にStateを更新
    """

    def __init__(
        self,
        settings: Settings,
        bookscan: BookscanClientProtocol,
        dropbox: DropboxClientProtocol,
        state_store: StateStore,
        failure_store: FailureStore | None = None,
    ) -> None:
        self.settings = settings
        self.bookscan = bookscan
        self.dropbox = dropbox
        self.state_store = state_store
        self.failure_store = failure_store or FailureStore(settings)
        self._state_lock = threading.Lock()
        self._retrying = create_retrying_from_settings(settings, self.failure_store)

    def _ensure_download_dir(self) -> Path:
        d = Path(self.settings.DOWNLOAD_DIR)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _dropbox_dest(self, relpath: str) -> str:
        """
        同期先ルート（DROPBOX_DEST_ROOT）配下の絶対パスへ正規化
        """
        # 余分なスラッシュを避けつつ正規化
        root = self.settings.DROPBOX_DEST_ROOT or "/"
        root_norm = "/" + root.strip("/")
        rel_norm = relpath.lstrip("/")
        if root_norm == "/":
            return f"/{rel_norm}"
        return f"{root_norm}/{rel_norm}"

    def _append_version_suffix(self, path: str, version: int) -> str:
        p = Path(path)
        stem = p.stem
        suffix = p.suffix
        return str(p.with_name(f"{stem} (v{version}){suffix}"))

    def _resolve_conflict_path(self, dest: str) -> str:
        """
        同名ファイルが既に存在する場合に、(v2), (v3), ... を付与して衝突しないパスを返す。
        """
        version = 2
        candidate = dest
        while True:
            md = self.dropbox.get_metadata(candidate)
            if not md.get("exists"):
                return candidate
            candidate = self._append_version_suffix(dest, version)
            version += 1

    def _call_with_retry(
        self, book_id: str, stage: str, fn: Callable, *args: Any, **kwargs: Any
    ) -> Any:
        try:
            return call_with_retry(self._retrying, fn, *args, **kwargs)
        except BaseException as e:
            # 最終的に失敗した場合のみ記録
            self.failure_store.record_failure(book_id, stage, e)
            raise

    def _resolve_conflict_path_with_retry(self, book_id: str, dest: str) -> str:
        version = 2
        candidate = dest
        while True:
            md = self._call_with_retry(book_id, "upload", self.dropbox.get_metadata, candidate)
            if not md.get("exists"):
                return candidate
            candidate = self._append_version_suffix(dest, version)
            version += 1

    def run(self, plan: list[PlanEntry], dry_run: bool = False) -> None:
        """
        与えられたアップロード計画(plan)を実行する。
        - dry_run=True の場合は計画の表示のみ
        """
        if dry_run:
            print(f"[DRY-RUN] planned actions: {len(plan)}")
            for entry in plan:
                if entry.get("action") == "upload":
                    dst = self._dropbox_dest(str(entry.get("relpath", entry.get("filename", ""))))
                    print(
                        f"[DRY-RUN] upload book_id={entry.get('book_id')} -> {dst} "
                        f"(title='{entry.get('title','')}', size={entry.get('size')}, ext={entry.get('ext')})"
                    )
            return

        if not plan:
            return

        tmp_dir = self._ensure_download_dir()
        # ルートフォルダを先に用意
        self.dropbox.ensure_folder(self.settings.DROPBOX_DEST_ROOT)

        # 並行実行: plan の各エントリをワーカーで処理
        try:
            max_workers = int(getattr(self.settings, "CONCURRENCY", 2))
        except Exception:
            max_workers = 2
        max_workers = max(1, max_workers)

        def _worker(entry: PlanEntry) -> None:
            if entry.get("action") != "upload":
                return

            book_id = str(entry.get("book_id"))
            relpath = str(entry.get("relpath") or entry.get("filename") or f"{book_id}.pdf")
            ext = str(entry.get("ext") or "pdf").lstrip(".") or "pdf"

            local_tmp = tmp_dir / f"{book_id}.{ext}"

            # Bookscanからダウンロード
            item_for_download: dict[str, Any] = {
                "id": book_id,
                "title": entry.get("title"),
                "ext": ext,
                "updated_at": entry.get("updated_at"),
                "size": entry.get("size"),
            }
            # pdf_url と showbook_url（存在すれば）をダウンロード情報に引き継ぐ
            if entry.get("pdf_url"):
                item_for_download["pdf_url"] = entry["pdf_url"]
            if entry.get("showbook_url"):
                item_for_download["showbook_url"] = entry["showbook_url"]
            self._call_with_retry(
                book_id, "download", self.bookscan.download, item_for_download, str(local_tmp)
            )
            # ダウンロード整合性チェック（サイズ/空ファイル）
            try:
                try:
                    actual_size = int(local_tmp.stat().st_size)
                except Exception:
                    actual_size = 0
                exp_size_val = entry.get("size")
                expected_size: int | None
                try:
                    expected_size = int(exp_size_val) if exp_size_val is not None else None
                except Exception:
                    expected_size = None
                if actual_size <= 0:
                    raise RuntimeError(f"downloaded file is empty: {local_tmp} (book_id={book_id})")
                if expected_size is not None and expected_size != actual_size:
                    raise RuntimeError(
                        f"download size mismatch: expected={expected_size} actual={actual_size} book_id={book_id}"
                    )
            except BaseException as e:
                self.failure_store.record_failure(book_id, "verify", e)
                raise

            # Dropboxへアップロード（重複回避）
            dst = self._dropbox_dest(relpath)
            # 中間フォルダがあれば作成
            if "/" in dst.strip("/"):
                folder = "/" + "/".join(dst.strip("/").split("/")[:-1])
                if folder:
                    self.dropbox.ensure_folder(folder)

            # ローカルファイルのDropbox-Content-Hashを計算
            local_hash = dropbox_content_hash(str(local_tmp))

            md = self._call_with_retry(book_id, "upload", self.dropbox.get_metadata, dst)
            uploaded_path = dst
            did_upload = False
            if md.get("exists") and md.get("type") == "file":
                # 既存ファイルと同一内容ならアップロードせずスキップ
                if str(md.get("content_hash") or "") == local_hash:
                    uploaded_path = str(md.get("path") or dst)
                else:
                    # コンフリクト: リネームして保存（メタ取得もリトライ）
                    uploaded_path = self._resolve_conflict_path_with_retry(book_id, dst)
                    self._call_with_retry(
                        book_id, "upload", self.dropbox.upload_file, str(local_tmp), uploaded_path
                    )
                    did_upload = True
            else:
                # 存在しないのでそのままアップロード
                self._call_with_retry(
                    book_id, "upload", self.dropbox.upload_file, str(local_tmp), dst
                )
                did_upload = True

            # アップロード検証（サイズ/ハッシュ）
            if did_upload:
                # メタデータ取得はネットワーク失敗時に再試行
                remote = self._call_with_retry(
                    book_id, "verify", self.dropbox.get_metadata, uploaded_path
                )
                try:
                    logging.getLogger("bds")
                    if not remote.get("exists") or remote.get("type") != "file":
                        raise RuntimeError(
                            f"uploaded file not found or not a file: {uploaded_path}"
                        )
                    # サイズ検証（取得できた場合）
                    try:
                        local_size = int(local_tmp.stat().st_size)
                    except Exception:
                        local_size = None
                    remote_size = remote.get("size")
                    if (
                        local_size is not None
                        and isinstance(remote_size, int)
                        and remote_size != local_size
                    ):
                        raise RuntimeError(
                            f"size mismatch after upload: local={local_size} remote={remote_size} path={uploaded_path}"
                        )
                    # ハッシュ検証（必須）
                    remote_hash = str(remote.get("content_hash") or "")
                    if remote_hash != local_hash:
                        raise RuntimeError(
                            f"content_hash mismatch after upload: local={local_hash} remote={remote_hash} path={uploaded_path}"
                        )
                except BaseException as e:
                    self.failure_store.record_failure(book_id, "verify", e)
                    raise

            # State更新（ハッシュ/サイズを保存）
            try:
                size_val = int(entry.get("size") or local_tmp.stat().st_size)
            except Exception:
                size_val = 0
            meta: dict[str, Any] = {
                "updated_at": str(entry.get("updated_at") or ""),
                "size": size_val,
                "hash": local_hash,
                "dropbox_path": uploaded_path,
            }
            # 複数スレッドからのState更新を直列化
            with self._state_lock:
                try:
                    self.state_store.upsert_item(book_id, meta)
                except BaseException as e:
                    self.failure_store.record_failure(book_id, "state_update", e)
                    raise

        errors: list[BaseException] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_worker, entry) for entry in plan]
            for fut in as_completed(futures):
                try:
                    fut.result()
                except BaseException as e:
                    errors.append(e)
        if errors:
            # 最初の例外を再送出（件数情報付き）
            raise RuntimeError(f"{len(errors)} task(s) failed, first error: {errors[0]}")
