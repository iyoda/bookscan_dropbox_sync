from __future__ import annotations

from pathlib import Path
from typing import Any

from bds.bookscan_client import BookscanClient
from bds.config import Settings


def test_parse_showbook_html_single_item() -> None:
    p = Path("samples/showbook_sample.html")
    assert p.exists(), "sample showbook file missing"
    html = p.read_text(encoding="utf-8", errors="ignore")
    s = Settings()
    c = BookscanClient(s)
    items = c._parse_showbook_page(html)
    assert isinstance(items, list)
    assert len(items) == 1
    it = items[0]
    assert it["id"] == "1001"
    assert "Sample Book Title" in str(it["title"])  # title extracted without .pdf
    assert it["ext"] == "pdf"
    # download link present on page
    assert "pdf_url" in it and str(it["pdf_url"]).startswith("/download.php")


class DummyResp:
    def __init__(self, data: bytes, status: int = 200) -> None:
        self._data = data
        self.status_code = status

    def raise_for_status(self) -> None:  # no-op
        return None

    @property
    def content(self) -> bytes:
        return self._data


def test_download_resolves_root_relative_url(tmp_path: Path, monkeypatch: Any) -> None:
    s = Settings()
    s.BOOKSCAN_BASE_URL = "https://example.test"
    c = BookscanClient(s)

    item = {
        "id": "1",
        "title": "T",
        "ext": "pdf",
        "size": 3,
        "updated_at": "",
        "pdf_url": "/download.php?x=1",
    }

    def fake_get(url: str, timeout: int) -> DummyResp:
        assert url == "https://example.test/download.php?x=1"
        return DummyResp(b"PDF")

    monkeypatch.setattr(c.session, "get", fake_get)

    dest = tmp_path / "file.pdf"
    c.download(item, str(dest))
    assert dest.read_bytes() == b"PDF"

