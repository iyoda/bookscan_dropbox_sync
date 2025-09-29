from __future__ import annotations

from typing import Dict, Optional

import dropbox
from dropbox.exceptions import ApiError, BadInputError
from dropbox.files import FileMetadata, FolderMetadata, WriteMode

from .config import Settings


class DropboxClient:
    """
    Dropboxへのフォルダ/ファイル操作を行うクライアント（M1: 固定アクセストークン想定）
    - 単純アップロード（小サイズ前提）
    - フォルダ作成（存在時は無視）
    - 簡易メタデータ取得
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._dbx: Optional[dropbox.Dropbox] = None

    def _client(self) -> dropbox.Dropbox:
        token = self.settings.DROPBOX_ACCESS_TOKEN
        if not token:
            raise ValueError("DROPBOX_ACCESS_TOKEN is required for Dropbox operations in M1.")
        if self._dbx is None:
            self._dbx = dropbox.Dropbox(oauth2_access_token=token, timeout=self.settings.HTTP_TIMEOUT)
        return self._dbx

    @staticmethod
    def _normalize_path(path: str) -> str:
        return path if path.startswith("/") else f"/{path}"

    def ensure_folder(self, path: str) -> None:
        """
        Dropbox上にフォルダを作成（存在していれば何もしない）
        ネストされたフォルダも順次作成する。
        - 特殊パス '/Apps' はDropboxの予約領域のため作成をスキップ
        """
        dbx = self._client()
        p = self._normalize_path(path).rstrip("/")
        if not p or p == "/":
            return
        segments = [seg for seg in p.split("/") if seg]
        cur = ""
        for seg in segments:
            next_cur = f"{cur}/{seg}"
            # '/Apps' は作成対象外（予約ルート）
            if next_cur.lower() == "/apps":
                cur = next_cur
                continue
            try:
                dbx.files_create_folder_v2(next_cur)
            except (ApiError, BadInputError):
                # 既存や権限不足/競合などは無視
                pass
            cur = next_cur

    def upload_file(self, local_path: str, dropbox_path: str) -> None:
        """
        ローカルファイルをDropboxへアップロード（小サイズ前提、追記しない）
        既存ファイルとの衝突はWriteMode.add（上書きしない）。
        """
        dbx = self._client()
        dp = self._normalize_path(dropbox_path)
        with open(local_path, "rb") as f:
            data = f.read()
        dbx.files_upload(data, dp, mode=WriteMode.add, mute=True, strict_conflict=False)

    def get_metadata(self, dropbox_path: str) -> Dict[str, object]:
        """
        Dropbox上のファイル/フォルダのメタデータ取得（同名判定の基礎）。
        見つからない場合は {"exists": False, "path": "..."} を返す。
        """
        dbx = self._client()
        dp = self._normalize_path(dropbox_path)
        try:
            md = dbx.files_get_metadata(dp)
        except ApiError:
            return {"exists": False, "path": dp}
        out: Dict[str, object] = {"exists": True, "path": dp, "name": md.name, "id": getattr(md, "id", None)}
        if isinstance(md, FileMetadata):
            out.update(
                {
                    "type": "file",
                    "size": md.size,
                    "client_modified": md.client_modified.isoformat() if hasattr(md, "client_modified") else None,
                    "server_modified": md.server_modified.isoformat() if hasattr(md, "server_modified") else None,
                    "content_hash": md.content_hash,
                }
            )
        elif isinstance(md, FolderMetadata):
            out.update({"type": "folder"})
        else:
            out.update({"type": "unknown"})
        return out
