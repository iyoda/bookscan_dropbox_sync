from __future__ import annotations

import json
from pathlib import Path
import pytest

from bds.config import Settings
from bds.state_store import StateStore
from bds.transfer import TransferEngine
from bds.failure_store import FailureStore


def test_failure_store_json_record_and_list(tmp_path: Path) -> None:
    s = Settings()
    s.STATE_BACKEND = "json"
    s.STATE_PATH = str(tmp_path / "state.json")
    s.FAILURE_LOG_PATH = str(tmp_path / "fail.jsonl")

    fs = FailureStore(s)
    rec = fs.record_failure("1", "download", Exception("HTTP 429 Too Many Requests"))
    assert rec.retryable is True
    assert rec.error_class in ("rate_limited", "http_error")

    # JSONLが生成され、list_recentで取得できる
    log_path = Path(s.FAILURE_LOG_PATH)
    assert log_path.exists()
    items = fs.list_recent()
    assert len(items) >= 1
    latest = items[0]
    assert latest["book_id"] == "1"
    assert latest["stage"] == "download"
    assert latest["retryable"] is True


def test_failure_store_sqlite_record_and_list(tmp_path: Path) -> None:
    s = Settings()
    s.STATE_BACKEND = "sqlite"
    s.STATE_PATH = str(tmp_path / "state.db")

    fs = FailureStore(s)
    rec = fs.record_failure("2", "upload", Exception("server error 500"))
    assert rec.retryable is True
    assert rec.error_class in ("server_error", "http_error")

    items = fs.list_recent()
    assert len(items) >= 1
    found = any(item["book_id"] == "2" and item["stage"] == "upload" for item in items)
    assert found


# ---- helpers for TransferEngine test ----
class BrokenBookscanClient:
    def download(self, item, dest_path: str) -> None:
        raise TimeoutError("timed out")  # 分類: timeout(True)


class NoopDropboxClient:
    def ensure_folder(self, path: str) -> None:
        return

    def get_metadata(self, dropbox_path: str):
        return {"exists": False, "path": dropbox_path}

    def upload_file(self, local_path: str, dropbox_path: str) -> None:
        return


def test_transfer_engine_records_download_failure(tmp_path: Path) -> None:
    s = Settings()
    s.DOWNLOAD_DIR = str(tmp_path / "downloads")
    s.STATE_BACKEND = "json"
    s.STATE_PATH = str(tmp_path / "state.json")
    s.FAILURE_LOG_PATH = str(tmp_path / "fail.jsonl")

    store = StateStore(s)
    fs = FailureStore(s)
    engine = TransferEngine(s, BrokenBookscanClient(), NoopDropboxClient(), store, failure_store=fs)

    plan = [
        {
            "action": "upload",
            "book_id": "42",
            "title": "T",
            "ext": "pdf",
            "size": 3,
            "relpath": "file.pdf",
            "updated_at": "2024-08-03",
        }
    ]

    with pytest.raises(RuntimeError):
        engine.run(plan, dry_run=False)

    # 失敗が記録されている
    items = fs.list_recent()
    assert len(items) >= 1
    latest = items[0]
    assert latest["book_id"] == "42"
    assert latest["stage"] == "download"
    # TimeoutError -> timeout として分類され、retryable=True の想定
    assert latest["retryable"] is True
