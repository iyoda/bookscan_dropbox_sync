from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from .config import Settings

ItemMeta = Dict[str, Any]


class BookscanClient:
    """
    Bookscanから認証・一覧取得・ダウンロードを行うクライアント（M1: 最小実装の骨格）
    - 本実装のHTTPフローは後続で追加
    - まずはHTMLから一覧をパースする関数を提供（単体テスト対象）
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session: requests.Session = requests.Session()
        self.session.headers.update({"User-Agent": self.settings.USER_AGENT})
        self.base_url: str = self.settings.BOOKSCAN_BASE_URL.rstrip("/")
        self.timeout: int = self.settings.HTTP_TIMEOUT

    def login(self) -> None:
        """
        ログインし、セッションを確立する。
        M1最小版では後続実装。テスト/ドライランでは未実装のままでも進行できる。
        """
        raise NotImplementedError("BookscanClient.login: HTTPログインは後続実装予定（M1）。")

    def list_downloadables(self) -> List[ItemMeta]:
        """
        ダウンロード可能一覧を返す。
        M1最小版ではHTTP取得の実装は後続。まずはHTML文字列→ItemMeta配列のパーサ関数を提供。
        """
        raise NotImplementedError("BookscanClient.list_downloadables: 取得処理は後続実装予定（M1）。")

    def download(self, item: ItemMeta, dest_path: str) -> None:
        """
        指定アイテムをdest_pathへダウンロード。
        M1最小版では後続実装。
        """
        raise NotImplementedError("BookscanClient.download: ダウンロード処理は後続実装予定（M1）。")

    @staticmethod
    def parse_downloadables(html: str) -> List[ItemMeta]:
        """
        ダウンロード可能一覧HTMLをパースして、ItemMetaのリストを返す（最小パーサ）。
        期待する属性（柔軟に拡張可能）:
          - data-id: 必須
          - data-title: 任意（なければNone）
          - data-ext: 拡張子（例: 'pdf' or '.pdf'）※先頭ドットは取り除く
          - data-updated: 更新日時文字列
          - data-size: サイズ（数値文字列）
          - data-url: PDFのURL（任意）
        """
        soup = BeautifulSoup(html, "html.parser")
        items: List[ItemMeta] = []
        for el in soup.select(".download-item"):
            book_id = (el.get("data-id") or "").strip()
            if not book_id:
                # IDが無ければスキップ
                continue

            title_raw: Optional[str] = (el.get("data-title") or "").strip() or None
            ext_raw = (el.get("data-ext") or "pdf").strip()
            ext = ext_raw[1:] if ext_raw.startswith(".") else ext_raw

            updated_at = (el.get("data-updated") or "").strip()

            size_val = 0
            size_raw = (el.get("data-size") or "").strip()
            if size_raw:
                try:
                    size_val = int(size_raw)
                except ValueError:
                    size_val = 0

            pdf_url = (el.get("data-url") or "").strip()

            item: ItemMeta = {
                "id": book_id,
                "title": title_raw,
                "ext": ext or "pdf",
                "updated_at": updated_at,
                "size": size_val,
            }
            if pdf_url:
                item["pdf_url"] = pdf_url

            items.append(item)

        return items
