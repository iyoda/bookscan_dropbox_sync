from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from .config import Settings
from .util import RateLimiter, call_with_retry, create_simple_retrying, totp

ItemMeta = dict[str, Any]


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
        qps = getattr(self.settings, "BOOKSCAN_RATE_LIMIT_QPS", None)
        if qps is None:
            qps = getattr(self.settings, "RATE_LIMIT_QPS", 0.0)
        self._rl = RateLimiter(float(qps or 0.0))
        self._retrying = create_simple_retrying(
            max_attempts=5, backoff_multiplier=1.0, backoff_max=10.0
        )

    def _call_with_retry(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        return call_with_retry(self._retrying, fn, *args, **kwargs)

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
                self._rl.throttle()
                self._call_with_retry(
                    self.session.get, self.base_url, timeout=self.timeout
                ).raise_for_status()
            except Exception:
                # base_urlへのウォームアップ失敗は無視（後続POSTで成功する可能性もある）
                pass

            login_url = getattr(self.settings, "BOOKSCAN_LOGIN_URL", None)
            if not login_url:
                # ログインURL未指定の場合はここまで（ウォームアップのみ）
                return

            payload: dict[str, str] = {
                getattr(self.settings, "BOOKSCAN_LOGIN_EMAIL_FIELD", "email"): str(email),
                getattr(self.settings, "BOOKSCAN_LOGIN_PASSWORD_FIELD", "password"): str(password),
            }
            # 将来のTOTP手動入力/外部供給を想定（自動生成はM4）
            totp_field = getattr(self.settings, "BOOKSCAN_LOGIN_TOTP_FIELD", "otp")
            secret = getattr(self.settings, "BOOKSCAN_TOTP_SECRET", None)
            if totp_field and secret:
                # TOTP生成失敗時は無視（後続で失敗した場合も例外は伝播しない）
                with contextlib.suppress(Exception):
                    payload[totp_field] = totp(secret)

            self._rl.throttle()
            self._call_with_retry(
                self.session.post, login_url, data=payload, timeout=self.timeout
            ).raise_for_status()
        except Exception:
            # M1では例外を伝播しない
            return

    def list_downloadables(self) -> list[ItemMeta]:
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
                html_docs: list[str] = []
                p = Path(debug_src)

                if p.exists():
                    if p.is_file():
                        html_docs = [p.read_text(encoding="utf-8")]
                    elif p.is_dir():
                        files = sorted(p.glob("*.html")) + sorted(p.glob("*.htm"))
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
                        self._rl.throttle()
                        resp = self._call_with_retry(
                            self.session.get, debug_src, timeout=self.timeout
                        )
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

                debug_items: list[ItemMeta] = []
                for html in html_docs:
                    parsed = self._parse_any_html(html)
                    debug_items.extend(parsed)
                return debug_items
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

        items: list[ItemMeta] = []
        try:
            for page in range(1, max_pages + 1):
                url = template.replace("{page}", str(page)) if "{page}" in template else template
                try:
                    self._rl.throttle()
                    resp = self._call_with_retry(self.session.get, url, timeout=self.timeout)
                    resp.raise_for_status()
                    html = resp.text
                except Exception:
                    # 一時的失敗は次のページへ（または停止）
                    if "{page}" not in template or stop_on_empty:
                        break
                    else:
                        continue

                part = self._parse_any_html(html)
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
            self._rl.throttle()
            resp = self._call_with_retry(self.session.get, url, timeout=self.timeout)
            resp.raise_for_status()
            dp.write_bytes(resp.content)
            return

        # ルート相対（/download.php...）は base_url に連結してHTTP扱い
        if url.startswith("/"):
            full = f"{self.base_url}{url}"
            self._rl.throttle()
            resp = self._call_with_retry(self.session.get, full, timeout=self.timeout)
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
    def parse_downloadables(html: str) -> list[ItemMeta]:
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
        items: list[ItemMeta] = []
        for el in soup.select(".download-item"):
            book_id = str(el.get("data-id") or "").strip()
            if not book_id:
                # IDが無ければスキップ
                continue

            title_raw: str | None = str(el.get("data-title") or "").strip() or None
            ext_raw = str(el.get("data-ext") or "pdf").strip()
            ext = ext_raw[1:] if ext_raw.startswith(".") else ext_raw

            updated_at = str(el.get("data-updated") or "").strip()

            size_val = 0
            size_raw = str(el.get("data-size") or "").strip()
            if size_raw:
                try:
                    size_val = int(size_raw)
                except ValueError:
                    size_val = 0

            pdf_url = str(el.get("data-url") or "").strip()

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

    # ---- additional parsers for real Bookscan pages (debug input) ----
    @staticmethod
    def _parse_showbook_page(html: str) -> list[ItemMeta]:
        """
        showbook.php ページを直接パースして1件の ItemMeta を返す（存在すれば）。
        - window.routing の path クエリから bid と f（ファイル名）を抽出
        - ダウンロードリンクの href（/download.php?...）を pdf_url として拾う
        - タイトルは f から .pdf を除去したもの、なければ h2.mybook_modal_title
        """
        import re
        from urllib.parse import parse_qs, unquote, urlparse

        soup = BeautifulSoup(html, "html.parser")
        bid: str | None = None
        title: str | None = None
        pdf_url: str | None = None

        for sc in soup.find_all("script"):
            s = sc.string or sc.get_text()
            if not s or "window.routing" not in s:
                continue
            m = re.search(r"\"path\"\s*:\s*\"([^\"]+)\"", s)
            if not m:
                continue
            path = m.group(1)
            q = parse_qs(urlparse(path).query)
            if not bid and q.get("bid"):
                bid = q["bid"][0]
            if not title and q.get("f"):
                try:
                    title = unquote(q["f"][0])
                except Exception:
                    title = q["f"][0]

        a = soup.select_one("ul.detail_navi a[href*='download.php']")
        if a:
            href = str(a.get("href") or "")
            if href:
                pdf_url = href
                # タイトルの補完（f= から）
                try:
                    from urllib.parse import parse_qs, unquote, urlparse

                    q = parse_qs(urlparse(href).query)
                    if not title and q.get("f"):
                        title = unquote(q["f"][0])
                except Exception:
                    pass

        if not title:
            h = soup.select_one("h2.mybook_modal_title")
            if h and h.get_text(strip=True):
                title = h.get_text(strip=True)

        # 最低限 bid と title が必要
        if not bid or not title:
            return []
        if title.lower().endswith(".pdf"):
            title = title[:-4]

        item: ItemMeta = {
            "id": bid,
            "title": title,
            "ext": "pdf",
            "updated_at": "",
            "size": 0,
        }
        if pdf_url:
            item["pdf_url"] = pdf_url
        return [item]

    @staticmethod
    def _parse_bookshelf_list_page(html: str) -> list[ItemMeta]:
        """
        bookshelf_all_list.php のリストページから showbook へのリンクを抽出して
        ItemMeta 配列を作成。
        - a[href*='showbook.php'] のクエリから bid と f を抽出
        - f が無い場合は近傍の h3 テキストをタイトルとして採用
        """
        import re
        from urllib.parse import parse_qs, unquote, urlparse

        soup = BeautifulSoup(html, "html.parser")
        items: list[ItemMeta] = []
        for a in soup.select("a[href*='showbook.php']"):
            href = str(a.get("href") or "")
            if not href:
                continue
            q = parse_qs(urlparse(href).query)
            bid = None
            if q.get("bid"):
                bid = q["bid"][0]
            if not bid:
                m = re.search(r"[?&]bid=(\d+)", href)
                if m:
                    bid = m.group(1)
            if not bid:
                continue
            title: str | None = None
            if q.get("f"):
                try:
                    title = unquote(q["f"][0])
                except Exception:
                    title = q["f"][0]
            if not title:
                h3 = a.find_next("h3")
                if h3 and h3.get_text(strip=True):
                    title = h3.get_text(strip=True)
            if not title:
                title = bid
            if title.lower().endswith(".pdf"):
                title = title[:-4]
            items.append(
                {
                    "id": bid,
                    "title": title,
                    "ext": "pdf",
                    "updated_at": "",
                    "size": 0,
                }
            )
        return items

    def _parse_any_html(self, html: str) -> list[ItemMeta]:
        """
        複数のパーサを順に試す（.download-item → showbook → bookshelf）。
        """
        items = self.parse_downloadables(html)
        if items:
            return items
        items = self._parse_showbook_page(html)
        if items:
            return items
        return self._parse_bookshelf_list_page(html)
