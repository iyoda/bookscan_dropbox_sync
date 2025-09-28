from __future__ import annotations

from typing import Dict

from .config import Settings


class DropboxClient:
    """Dropboxへのフォルダ/ファイル操作を行うクライアント（M1で実装予定の空実装）"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ensure_folder(self, path: str) -> None:
        """Dropbox上にフォルダを作成（存在していれば何もしない）"""
        raise NotImplementedError

    def upload_file(self, local_path: str, dropbox_path: str) -> None:
        """ローカルファイルをDropboxへアップロード（小サイズ前提、M1で実装）"""
        raise NotImplementedError

    def get_metadata(self, dropbox_path: str) -> Dict[str, object]:
        """Dropbox上のファイル/フォルダのメタデータ取得（同名判定の基礎、M1で実装）"""
        raise NotImplementedError
