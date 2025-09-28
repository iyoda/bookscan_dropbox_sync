from __future__ import annotations

from bds.bookscan_client import BookscanClient


def test_parse_downloadables_minimal() -> None:
    html = """
    <div class="download-item"
         data-id="1"
         data-title="Title One"
         data-ext=".pdf"
         data-updated="2024-08-01T12:34:56Z"
         data-size="12345"
         data-url="https://example.com/1.pdf"></div>
    <div class="download-item"
         data-id="2"
         data-title="Second: Work?"
         data-ext="pdf"
         data-updated="2024-08-02"
         data-size="0"></div>
    """
    items = BookscanClient.parse_downloadables(html)
    assert isinstance(items, list)
    assert len(items) == 2

    a, b = items[0], items[1]

    # item A
    assert a["id"] == "1"
    assert a["title"] == "Title One"
    assert a["ext"] == "pdf"  # 先頭ドットは除去される
    assert a["updated_at"] == "2024-08-01T12:34:56Z"
    assert a["size"] == 12345
    assert a["pdf_url"] == "https://example.com/1.pdf"

    # item B
    assert b["id"] == "2"
    assert b["title"] == "Second: Work?"
    assert b["ext"] == "pdf"
    assert b["updated_at"] == "2024-08-02"
    assert b["size"] == 0
    assert "pdf_url" not in b
