from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path
import os

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
        M1最小版:
          - デバッグ用HTMLパスが指定されていればログインはスキップ。
          - 資格情報（BOOKSCAN_EMAIL/BOOKSCAN_PASSWORD）が未設定の場合もスキップ。
          - HTTPログインの本実装は後続（M1/M2）だが、ネットワークを叩いても失敗は握り潰す。
        """
        debug_path = getattr(self.settings, "BOOKSCAN_DEBUG_HTML_PATH", None)
        if debug_path:
            return
        email = getattr(self.settings, "BOOKSCAN_EMAIL", None)
        password = getattr(self.settings, "BOOKSCAN_PASSWORD", None)
        if not email or not password:
            # 資格情報がない場合は安全にスキップ（テスト/ドライランで例外を出さない）
            return
        try:
            # 最小のウォームアップ（Cookie確立）。本格的なフォームログインは後続実装。
            resp = self.session.get(self.base_url, timeout=self.timeout)
            resp.raise_for_status()
        except Exception:
            # M1では失敗しても例外を伝播させない（テスト安定性/ドライラン優先）
            return

    def list_downloadables(self) -> List[ItemMeta]:
        """
        ダウンロード可能一覧を返す。
        M1最小版（デバッグ強化）:
        - BOOKSCAN_DEBUG_HTML_PATH が指定されている場合:
          - ファイルパスを指定すると、そのHTMLをパース
          - ディレクトリを指定すると、*.html(,*.htm) を昇順で全て読み込み、結合パース（擬似ページネーション）
          - ワイルドカード（例: 'samples/*.html'）も対応
          - 直接HTML文字列（'<' を含む）も可
        - 上記以外（HTTP取得）は後続実装。現段階では空配列を返す。
        """
        debug_src = getattr(self.settings, "BOOKSCAN_DEBUG_HTML_PATH", None)
        if debug_src:
            try:
                html_docs: List[str] = []
                p = Path(debug_src)

                if p.exists():
                    if p.is_file():
                        html_docs = [p.read_text(encoding="utf-8")]
                    elif p.is_dir():
                        files = sorted(list(p.glob("*.html"))) + sorted(list(p.glob("*.htm")))
                        for f in files:
                            try:
                                html_docs.append(f.read_text(encoding="utf-8"))
                            except Exception:
                                continue
                    else:
                        # その他（ソケット等）は未対応
                        pass
                elif "<" in debug_src or "<" in debug_src:
                    html_docs = [debug_src]  # 生HTML
                else:
                    # ワイルドカードパターン対応（相対/絶対どちらも可）
                    files = sorted(Path().glob(debug_src))
                    for f in files:
                        try:
                            html_docs.append(f.read_text(encoding="utf-8"))
                        except Exception:
                            continue

                items: List[ItemMeta] = []
                for html in html_docs:
                    items.extend(self.parse_downloadables(html))
                return items
            except Exception:
                # デバッグ指定時は失敗しても空配列で継続
                return []
        # HTTPでの一覧取得は後続実装
        return []

    def download(self, item: ItemMeta, dest_path: str) -> None:
        """
        指定アイテムをdest_pathへダウンロード。
        M1最小版: pdf_url が http(s) の場合はGETして保存。
        file:// またはローカルパスの場合はコピー相当で保存。
        それ以外は size に応じた空/ダミーのファイルを書き出す。
        """
        url = str(item.get("pdf_url") or "")
        dp = Path(dest_path)
        dp.parent.mkdir(parents=True, exist_ok=True)

        if url.startswith("http://") or url.startswith("https://"):
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            dp.write_bytes(resp.content)
            return

        if url.startswith("file://"):
            src = Path(url[7:])
            if src.exists():
                dp.write_bytes(src.read_bytes())
                return

        if url and os.path.exists(url):
            src = Path(url)
            dp.write_bytes(src.read_bytes())
            return

        # フォールバック: 空（またはサイズに合わせたダミー）を書き出す
        size = 0
        try:
            size = int(item.get("size") or 0)
        except Exception:
            size = 0
        if size > 0 and size <= 10_000_000:
            dp.write_bytes(b"\0" * size)
        else:
            dp.write_bytes(b"")

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
