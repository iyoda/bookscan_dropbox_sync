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
    - HTTPフローの最小版（失敗は握り潰し）
    - デバッグ入力（HTML/ディレクトリ/ワイルドカード/http(s)URL/生HTML）をサポート
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session: requests.Session = requests.Session()
        self.session.headers.update({"User-Agent": self.settings.USER_AGENT})
        self.base_url: str = self.settings.BOOKSCAN_BASE_URL.rstrip("/")
        self.timeout: int = self.settings.HTTP_TIMEOUT

    def login(self) -> None:
        """
        ログインし、セッションを確立する（最小版）
        - BOOKSCAN_DEBUG_HTML_PATH が指定されていればスキップ
        - 資格情報（BOOKSCAN_EMAIL/BOOKSCAN_PASSWORD）が未設定ならスキップ
        - BOOKSCAN_LOGIN_URL が設定されていればフォームPOSTを試みる
        - いずれも失敗しても例外は投げずに戻る（M1はドライラン優先）
        """
        debug_path = getattr(self.settings, "BOOKSCAN_DEBUG_HTML_PATH", None)
        if debug_path:
            return

        email = getattr(self.settings, "BOOKSCAN_EMAIL", None)
        password = getattr(self.settings, "BOOKSCAN_PASSWORD", None)
        if not email or not password:
            return

        try:
            # Cookie確立のためのウォームアップ
            try:
                self.session.get(self.base_url, timeout=self.timeout).raise_for_status()
            except Exception:
                # base_urlへのウォームアップ失敗は無視（後続POSTで成功する可能性もある）
                pass

            login_url = getattr(self.settings, "BOOKSCAN_LOGIN_URL", None)
            if not login_url:
                # ログインURL未指定の場合はここまで（ウォームアップのみ）
                return

            payload: Dict[str, str] = {
                getattr(self.settings, "BOOKSCAN_LOGIN_EMAIL_FIELD", "email"): str(email),
                getattr(self.settings, "BOOKSCAN_LOGIN_PASSWORD_FIELD", "password"): str(password),
            }
            # 将来のTOTP手動入力/外部供給を想定（自動生成はM4）
            totp_field = getattr(self.settings, "BOOKSCAN_LOGIN_TOTP_FIELD", "otp")
            totp_value = None  # 未実装（M4でpyotp対応予定）
            if totp_field and totp_value:
                payload[totp_field] = totp_value

            self.session.post(login_url, data=payload, timeout=self.timeout).raise_for_status()
        except Exception:
            # M1では例外を伝播しない
            return

    def list_downloadables(self) -> List[ItemMeta]:
        """
        ダウンロード可能一覧を返す。
        優先順位:
        1) BOOKSCAN_DEBUG_HTML_PATH が指定されていれば、それに基づくデバッグ入力をパース
           - ファイル/ディレクトリ/ワイルドカード/http(s)URL/生HTML をサポート
        2) 上記が無い場合で BOOKSCAN_LIST_URL_TEMPLATE が設定されているときはHTTP取得
           - {page} を含む場合は1..BOOKSCAN_LIST_MAX_PAGES で繰り返し取得
           - ページが空になった時点で停止（BOOKSCAN_LIST_STOP_ON_EMPTY が True の場合）
        3) それ以外は空配列
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
                elif debug_src.startswith("http://") or debug_src.startswith("https://"):
                    try:
                        resp = self.session.get(debug_src, timeout=self.timeout)
                        resp.raise_for_status()
                        html_docs = [resp.text]
                    except Exception:
                        html_docs = []
                elif "<" in debug_src:
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

        # HTTPでの一覧取得
        template = getattr(self.settings, "BOOKSCAN_LIST_URL_TEMPLATE", None)
        if not template:
            # HTTPテンプレート未設定ならM1では何もしない
            return []

        try:
            max_pages = int(getattr(self.settings, "BOOKSCAN_LIST_MAX_PAGES", 1) or 1)
            stop_on_empty = bool(getattr(self.settings, "BOOKSCAN_LIST_STOP_ON_EMPTY", True))
        except Exception:
            max_pages = 1
            stop_on_empty = True

        items: List[ItemMeta] = []
        try:
            for page in range(1, max_pages + 1):
                url = template.replace("{page}", str(page)) if "{page}" in template else template
                try:
                    resp = self.session.get(url, timeout=self.timeout)
                    resp.raise_for_status()
                    html = resp.text
                except Exception:
                    # 一時的失敗は次のページへ（または停止）
                    if "{page}" not in template or stop_on_empty:
                        break
                    else:
                        continue

                part = self.parse_downloadables(html)
                if not part and stop_on_empty:
                    break
                items.extend(part)

                # {page} が無ければ1ページのみ
                if "{page}" not in template:
                    break
        except Exception:
            return []

        return items

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
