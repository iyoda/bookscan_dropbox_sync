from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .bookscan_client import BookscanClient
from .config import Settings
from .dropbox_client import DropboxClient
from .state_store import StateStore
from .util import dropbox_content_hash


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
            # pdf_url（存在すれば）をダウンロード情報に引き継ぐ
            if entry.get("pdf_url"):
                item_for_download["pdf_url"] = entry["pdf_url"]
            self.bookscan.download(item_for_download, str(local_tmp))

            # Dropboxへアップロード（重複回避）
            dst = self._dropbox_dest(relpath)
            # 中間フォルダがあれば作成
            if "/" in dst.strip("/"):
                folder = "/" + "/".join(dst.strip("/").split("/")[:-1])
                if folder:
                    self.dropbox.ensure_folder(folder)

            # ローカルファイルのDropbox-Content-Hashを計算
            local_hash = dropbox_content_hash(str(local_tmp))

            md = self.dropbox.get_metadata(dst)
            uploaded_path = dst
            if md.get("exists") and md.get("type") == "file":
                # 既存ファイルと同一内容ならアップロードせずスキップ
                if str(md.get("content_hash") or "") == local_hash:
                    uploaded_path = str(md.get("path") or dst)
                else:
                    # コンフリクト: リネームして保存
                    uploaded_path = self._resolve_conflict_path(dst)
                    self.dropbox.upload_file(str(local_tmp), uploaded_path)
            else:
                # 存在しないのでそのままアップロード
                self.dropbox.upload_file(str(local_tmp), dst)

            # State更新（ハッシュ/サイズを保存）
            try:
                size_val = int(entry.get("size") or local_tmp.stat().st_size)
            except Exception:
                size_val = 0
            meta: Dict[str, Any] = {
                "updated_at": str(entry.get("updated_at") or ""),
                "size": size_val,
                "hash": local_hash,
                "dropbox_path": uploaded_path,
            }
            self.state_store.upsert_item(book_id, meta)
