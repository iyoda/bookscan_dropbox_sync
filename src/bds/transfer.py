from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .bookscan_client import BookscanClient
from .config import Settings
from .dropbox_client import DropboxClient
from .state_store import StateStore


class TransferEngine:
    """
    ダウンロード→一時フォルダ→Dropboxアップロードを担うエンジン（M1 最小実装）
    - 単一スレッドで直列実行（小サイズ前提）
    - 成功時にStateを更新
    """

    def __init__(
        self,
        settings: Settings,
        bookscan: BookscanClient,
        dropbox: DropboxClient,
        state_store: StateStore,
    ) -> None:
        self.settings = settings
        self.bookscan = bookscan
        self.dropbox = dropbox
        self.state_store = state_store

    def _ensure_download_dir(self) -> Path:
        d = Path(self.settings.DOWNLOAD_DIR)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _dropbox_dest(self, relpath: str) -> str:
        """
        同期先ルート（DROPBOX_DEST_ROOT）配下の絶対パスへ正規化
        """
        root = self.settings.DROPBOX_DEST_ROOT.rstrip("/")
        if not root:
            root = "/"
        if relpath.startswith("/"):
            return f"{root}{relpath}"
        return f"{root}/{relpath}"

    def run(self, plan: List[Dict[str, Any]], dry_run: bool = False) -> None:
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

        for entry in plan:
            if entry.get("action") != "upload":
                continue

            book_id = str(entry.get("book_id"))
            relpath = str(entry.get("relpath") or entry.get("filename") or f"{book_id}.pdf")
            ext = str(entry.get("ext") or "pdf").lstrip(".") or "pdf"

            local_tmp = tmp_dir / f"{book_id}.{ext}"

            # Bookscanからダウンロード
            item_for_download: Dict[str, Any] = {
                "id": book_id,
                "title": entry.get("title"),
                "ext": ext,
                "updated_at": entry.get("updated_at"),
                "size": entry.get("size"),
            }
            self.bookscan.download(item_for_download, str(local_tmp))

            # Dropboxへアップロード
            dst = self._dropbox_dest(relpath)
            # 中間フォルダがあれば作成
            if "/" in dst.strip("/"):
                folder = "/" + "/".join(dst.strip("/").split("/")[:-1])
                if folder:
                    self.dropbox.ensure_folder(folder)

            self.dropbox.upload_file(str(local_tmp), dst)

            # State更新
            meta: Dict[str, Any] = {
                "updated_at": str(entry.get("updated_at") or ""),
                "size": int(entry.get("size") or 0),
                "hash": "",  # M1: 未計算
                "dropbox_path": dst,
            }
            self.state_store.upsert_item(book_id, meta)
