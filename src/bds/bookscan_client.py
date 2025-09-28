from __future__ import annotations

from typing import Any, Dict, List

from .config import Settings

ItemMeta = Dict[str, Any]


class BookscanClient:
    """Bookscanから認証・一覧取得・ダウンロードを行うクライアント（M1で実装予定の空実装）"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def login(self) -> None:
        """ログインし、セッションを確立する（M1で実装）"""
        raise NotImplementedError

    def list_downloadables(self) -> List[ItemMeta]:
        """ダウンロード可能一覧を返す（M1で実装）"""
        raise NotImplementedError

    def download(self, item: ItemMeta, dest_path: str) -> None:
        """指定アイテムをdest_pathへダウンロード（M1で実装）"""
        raise NotImplementedError
