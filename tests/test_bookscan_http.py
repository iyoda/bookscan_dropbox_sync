from __future__ import annotations

from typing import Any

from bds.bookscan_client import BookscanClient
from bds.config import Settings


class DummyResp:
    def __init__(self, text: str = "", status: int = 200) -> None:
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        # 最小: ステータスコードは無視（エラーを投げない）
        return None

    @property
    def content(self) -> bytes:
        return self.text.encode("utf-8")


def test_list_downloadables_with_debug_http(monkeypatch: Any) -> None:
    """
    BOOKSCAN_DEBUG_HTML_PATH に http(s) URL を与えた場合、
    そのURLから取得したHTMLをパースすることを検証。
    """
    html = """
    <div class="download-item"
         data-id="10"
         data-title="From HTTP"
         data-ext="pdf"
         data-updated="2024-09-01"
         data-size="111"></div>
    """
    settings = Settings(BOOKSCAN_DEBUG_HTML_PATH="https://example.test/list")
    client = BookscanClient(settings)

    def fake_get(url: str, timeout: int) -> DummyResp:
        assert url == "https://example.test/list"
        return DummyResp(text=html)

    monkeypatch.setattr(client.session, "get", fake_get)

    items = client.list_downloadables()
    assert isinstance(items, list)
    assert len(items) == 1
    it = items[0]
    assert it["id"] == "10"
    assert it["title"] == "From HTTP"
    assert it["ext"] == "pdf"
    assert it["updated_at"] == "2024-09-01"
    assert it["size"] == 111


def test_list_downloadables_http_template_pagination_stop_on_empty(monkeypatch: Any) -> None:
    """
    BOOKSCAN_LIST_URL_TEMPLATE が設定されている場合に、ページ1の結果が取得され、
    ページ2が空になった時点で停止（STOP_ON_EMPTY=True）することを検証。
    """
    html_page1 = """
    <div class="download-item"
         data-id="21"
         data-title="Page One Item"
         data-ext="pdf"
         data-updated="2024-09-02"
         data-size="222"></div>
    """
    html_empty = ""  # .download-item が存在しない

    settings = Settings(
        BOOKSCAN_LIST_URL_TEMPLATE="https://example.test/list?page={page}",
        BOOKSCAN_LIST_MAX_PAGES=3,
        BOOKSCAN_LIST_STOP_ON_EMPTY=True,
        BOOKSCAN_DEBUG_HTML_PATH=None,  # デバッグ入力は無効
    )
    client = BookscanClient(settings)

    def fake_get(url: str, timeout: int) -> DummyResp:
        if url == "https://example.test/list?page=1":
            return DummyResp(text=html_page1)
        elif url == "https://example.test/list?page=2":
            return DummyResp(text=html_empty)
        # ページ3以降は呼ばれない想定（STOP_ON_EMPTY=Trueのため）
        raise AssertionError(f"unexpected URL requested: {url}")

    monkeypatch.setattr(client.session, "get", fake_get)

    items = client.list_downloadables()
    assert isinstance(items, list)
    # page=1 の1件のみ
    assert len(items) == 1
    it = items[0]
    assert it["id"] == "21"
    assert it["title"] == "Page One Item"
    assert it["ext"] == "pdf"
    assert it["updated_at"] == "2024-09-02"
    assert it["size"] == 222
