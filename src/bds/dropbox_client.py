from __future__ import annotations

from typing import Dict, Optional

import dropbox
from dropbox.exceptions import ApiError, BadInputError
from dropbox.files import FileMetadata, FolderMetadata, WriteMode, UploadSessionCursor, CommitInfo

from .config import Settings
from .util import RateLimiter


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
        qps = getattr(self.settings, "DROPBOX_RATE_LIMIT_QPS", None)
        if qps is None:
            qps = getattr(self.settings, "RATE_LIMIT_QPS", 0.0)
        self._rl = RateLimiter(qps)

    def _client(self) -> dropbox.Dropbox:
        token = self.settings.DROPBOX_ACCESS_TOKEN
        if not token:
            raise ValueError("DROPBOX_ACCESS_TOKEN is required for Dropbox operations in M1.")
        if self._dbx is None:
            self._dbx = dropbox.Dropbox(
                oauth2_access_token=token,
                timeout=self.settings.HTTP_TIMEOUT,
                user_agent=self.settings.USER_AGENT,
                max_retries_on_error=5,
                max_retries_on_rate_limit=5,
            )
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
                self._rl.throttle()
                dbx.files_create_folder_v2(next_cur)
            except (ApiError, BadInputError):
                # 既存や権限不足/競合などは無視
                pass
            cur = next_cur

    def upload_file(self, local_path: str, dropbox_path: str) -> None:
        """
        ローカルファイルをDropboxへアップロード。
        - 小サイズ: files_upload
        - 大サイズ: アップロードセッションでチャンクアップロード
        既存ファイルとの衝突は WriteMode.add（上書きしない）。
        """
        dbx = self._client()
        dp = self._normalize_path(dropbox_path)

        # 設定から閾値/チャンクサイズを取得（未設定時は安全な既定値）
        try:
            threshold = int(getattr(self.settings, "DROPBOX_CHUNK_UPLOAD_THRESHOLD", 8 * 1024 * 1024))
        except Exception:
            threshold = 8 * 1024 * 1024
        try:
            chunk_size = int(getattr(self.settings, "DROPBOX_CHUNK_SIZE", 8 * 1024 * 1024))
        except Exception:
            chunk_size = 8 * 1024 * 1024
        if chunk_size <= 0:
            chunk_size = 8 * 1024 * 1024

        file_size = None
        try:
            from pathlib import Path
            file_size = Path(local_path).stat().st_size
        except Exception:
            pass

        if file_size is not None and file_size > threshold:
            # セッション方式
            with open(local_path, "rb") as f:
                # 先頭チャンク
                self._rl.throttle()
                start_res = dbx.files_upload_session_start(f.read(chunk_size))
                cursor = UploadSessionCursor(session_id=start_res.session_id, offset=f.tell())
                commit = CommitInfo(path=dp, mode=WriteMode.add, mute=True, strict_conflict=False)

                while True:
                    self._rl.throttle()
                    bytes_remaining = (file_size - f.tell()) if file_size is not None else None
                    if bytes_remaining is not None and bytes_remaining <= chunk_size:
                        dbx.files_upload_session_finish(f.read(chunk_size), cursor, commit)
                        break
                    data = f.read(chunk_size)
                    if not data:
                        # 念のため: 残りがなければ終了（小数点誤差等）
                        dbx.files_upload_session_finish(b"", cursor, commit)
                        break
                    dbx.files_upload_session_append_v2(data, cursor)
                    cursor.offset = f.tell()
        else:
            # 一括アップロード（小サイズ前提）
            with open(local_path, "rb") as f:
                data = f.read()
            self._rl.throttle()
            dbx.files_upload(data, dp, mode=WriteMode.add, mute=True, strict_conflict=False)

    def get_metadata(self, dropbox_path: str) -> Dict[str, object]:
        """
        Dropbox上のファイル/フォルダのメタデータ取得（同名判定の基礎）。
        見つからない場合は {"exists": False, "path": "..."} を返す。
        """
        dbx = self._client()
        dp = self._normalize_path(dropbox_path)
        try:
            self._rl.throttle()
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

    def revoke_token(self) -> None:
        """
        Revoke the current access token (auth_token_revoke).
        """
        dbx = self._client()
        self._rl.throttle()
        dbx.auth_token_revoke()
