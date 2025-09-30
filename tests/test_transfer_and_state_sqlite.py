from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

from bds.config import Settings
from bds.state_store import StateStore
from bds.transfer import TransferEngine


# ---- helpers / fakes ----
def dropbox_hash_bytes(data: bytes, chunk_size: int = 4 * 1024 * 1024) -> str:
    """
    Dropbox-Content-Hash をバイト列から計算（4MBチャンクのSHA256ダイジェストを連結→SHA256）
    """
    import hashlib

    overall = hashlib.sha256()
    for i in range(0, len(data), chunk_size):
        chunk = data[i : i + chunk_size]
        overall.update(hashlib.sha256(chunk).digest())
    return overall.hexdigest()


class FakeDropboxClient:
    """
    DropboxClient 互換の最小フェイク。
    - メモリ上に {path: {data, size, content_hash}} を保持
    - ensure_folder は no-op
    """

    def __init__(self) -> None:
        self.files: Dict[str, Dict[str, Any]] = {}
        self.upload_calls: list[str] = []

    def _norm(self, path: str) -> str:
        return path if path.startswith("/") else f"/{path}"

    def ensure_folder(self, path: str) -> None:
        # テストではフォルダ概念は持たず no-op
        return

    def get_metadata(self, dropbox_path: str) -> Dict[str, object]:
        p = self._norm(dropbox_path)
        if p in self.files:
            meta = self.files[p]
            return {
                "exists": True,
                "path": p,
                "name": Path(p).name,
                "type": "file",
                "size": meta["size"],
                "content_hash": meta["content_hash"],
            }
        return {"exists": False, "path": p}

    def upload_file(self, local_path: str, dropbox_path: str) -> None:
        p = self._norm(dropbox_path)
        data = Path(local_path).read_bytes()
        self.files[p] = {"data": data, "size": len(data), "content_hash": dropbox_hash_bytes(data)}
        self.upload_calls.append(p)


class FakeBookscanClient:
    """
    BookscanClient.download 互換の最小フェイク。
    渡された item['id'] に対応したバイト列を保存する。
    """

    def __init__(self, contents_by_id: Dict[str, bytes]) -> None:
        self.contents_by_id = contents_by_id

    def download(self, item: Dict[str, Any], dest_path: str) -> None:
        content = self.contents_by_id.get(str(item.get("id")), b"")
        Path(dest_path).write_bytes(content)


# ---- tests: TransferEngine duplicate handling ----
def _mk_settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.DOWNLOAD_DIR = str(tmp_path / "downloads")
    s.STATE_BACKEND = "json"
    s.STATE_PATH = str(tmp_path / "state.json")
    s.DROPBOX_DEST_ROOT = "/dest"
    return s


def test_transfer_skips_upload_when_same_content(tmp_path: Path) -> None:
    s = _mk_settings(tmp_path)
    store = StateStore(s)

    # 既存Dropbox上に同一内容のファイルがある想定
    dbx = FakeDropboxClient()
    remote_path = "/dest/file.pdf"
    same_data = b"AAA"
    dbx.files[remote_path] = {
        "data": same_data,
        "size": len(same_data),
        "content_hash": dropbox_hash_bytes(same_data),
    }

    # Bookscanからも同じ内容がダウンロードされる
    bookscan = FakeBookscanClient({"1": same_data})
    engine = TransferEngine(s, bookscan, dbx, store)

    plan = [
        {
            "action": "upload",
            "book_id": "1",
            "title": "Title",
            "ext": "pdf",
            "size": len(same_data),
            "relpath": "file.pdf",
            "updated_at": "2024-08-02",
        }
    ]

    engine.run(plan, dry_run=False)

    # アップロードは発生しない（既存と同一内容のため）
    assert dbx.upload_calls == []
    # 既存リモートはそのまま
    assert remote_path in dbx.files and len(dbx.files) == 1

    # State が更新され、content_hash と dropbox_path が格納される
    item = store.get_item("1")
    assert item is not None
    assert item.get("dropbox_path") == remote_path
    assert item.get("hash") == dropbox_hash_bytes(same_data)


def test_transfer_renames_on_conflict(tmp_path: Path) -> None:
    s = _mk_settings(tmp_path)
    store = StateStore(s)

    dbx = FakeDropboxClient()
    base_path = "/dest/file.pdf"
    existing_data = b"AAA"
    dbx.files[base_path] = {
        "data": existing_data,
        "size": len(existing_data),
        "content_hash": dropbox_hash_bytes(existing_data),
    }

    # ローカルは異なる内容 -> (v2) のパスにアップロードされる
    new_data = b"BBB"
    bookscan = FakeBookscanClient({"1": new_data})
    engine = TransferEngine(s, bookscan, dbx, store)

    plan = [
        {
            "action": "upload",
            "book_id": "1",
            "title": "New",
            "ext": "pdf",
            "size": len(new_data),
            "relpath": "file.pdf",
            "updated_at": "2024-08-03",
        }
    ]

    engine.run(plan, dry_run=False)

    v2_path = "/dest/file (v2).pdf"
    assert v2_path in dbx.files
    assert dbx.files[v2_path]["content_hash"] == dropbox_hash_bytes(new_data)
    # アップロード先は (v2)
    assert dbx.upload_calls == [v2_path]

    item = store.get_item("1")
    assert item is not None
    assert item.get("dropbox_path") == v2_path
    assert item.get("hash") == dropbox_hash_bytes(new_data)


def test_transfer_renames_on_multi_conflict_to_v3(tmp_path: Path) -> None:
    s = _mk_settings(tmp_path)
    store = StateStore(s)

    dbx = FakeDropboxClient()
    base_path = "/dest/file.pdf"
    v2_path = "/dest/file (v2).pdf"
    dbx.files[base_path] = {
        "data": b"AAA",
        "size": 3,
        "content_hash": dropbox_hash_bytes(b"AAA"),
    }
    dbx.files[v2_path] = {
        "data": b"CCC",
        "size": 3,
        "content_hash": dropbox_hash_bytes(b"CCC"),
    }

    new_data = b"BBB"
    bookscan = FakeBookscanClient({"1": new_data})
    engine = TransferEngine(s, bookscan, dbx, store)

    plan = [
        {
            "action": "upload",
            "book_id": "1",
            "title": "New",
            "ext": "pdf",
            "size": len(new_data),
            "relpath": "file.pdf",
            "updated_at": "2024-08-03",
        }
    ]

    engine.run(plan, dry_run=False)

    v3_path = "/dest/file (v3).pdf"
    assert v3_path in dbx.files
    assert dbx.files[v3_path]["content_hash"] == dropbox_hash_bytes(new_data)
    assert dbx.upload_calls == [v3_path]

    item = store.get_item("1")
    assert item is not None
    assert item.get("dropbox_path") == v3_path
    assert item.get("hash") == dropbox_hash_bytes(new_data)


# ---- tests: StateStore SQLite backend ----
def test_state_store_sqlite_upsert_and_get(tmp_path: Path) -> None:
    s = Settings()
    s.STATE_BACKEND = "sqlite"
    s.STATE_PATH = str(tmp_path / "state.db")

    store = StateStore(s)

    # 初期は存在しない
    assert store.get_item("1") is None

    # upsert -> get -> read
    meta = {"updated_at": "2024-08-01", "size": 123, "hash": "h1", "dropbox_path": "/p/a.pdf"}
    store.upsert_item("1", meta)
    got = store.get_item("1")
    assert got is not None
    assert got.get("updated_at") == "2024-08-01"
    assert int(got.get("size") or 0) == 123
    assert got.get("hash") == "h1"
    assert got.get("dropbox_path") == "/p/a.pdf"

    state = store.read()
    assert "items" in state and "1" in state["items"]


def test_state_store_sqlite_migrate_from_json(tmp_path: Path) -> None:
    # sqlite のパスに対して .json を隣に用意しておくと、初期化時に一度だけ取り込まれる
    db_path = tmp_path / "state.db"
    json_path = db_path.with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        '{"version":1,"items":{"42":{"updated_at":"2024-09-01","size":10,"hash":"hh","dropbox_path":"/x/y.pdf"}}}',
        encoding="utf-8",
    )

    s = Settings()
    s.STATE_BACKEND = "sqlite"
    s.STATE_PATH = str(db_path)

    store = StateStore(s)
    # 取り込み済み
    item = store.get_item("42")
    assert item is not None
    assert item.get("dropbox_path") == "/x/y.pdf"
