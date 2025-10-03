from __future__ import annotations

from pathlib import Path

from bds.config import Settings
from bds.state_store import StateStore
from bds.transfer import TransferEngine
from bds.util import dropbox_content_hash


# ---- Fakes ----
class FlakyBookscanClient:
    """
    download() が一時的に失敗し、その後成功するフェイク
    """

    def __init__(self, fail_times: int = 2) -> None:
        self.fail_times = fail_times

    def download(self, item, dest_path: str) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            # TransferEngine側の分類では "timed out" を timeout としてretryable=Trueにする
            raise TimeoutError("timed out")
        size = int(item.get("size") or 3)
        # 要求サイズのダミーコンテンツを書き込む
        content = b"A" * size
        with open(dest_path, "wb") as f:
            f.write(content)


class StableBookscanClient:
    """
    常に成功するBookscanクライアント
    """

    def download(self, item, dest_path: str) -> None:
        size = int(item.get("size") or 3)
        with open(dest_path, "wb") as f:
            f.write(b"B" * size)


class MemoryDropboxClient:
    """
    メモリ内でファイルメタデータを管理するDropboxクライアントのフェイク
    - ensure_folder: 何もしない
    - get_metadata: 登録済みファイルのメタを返す
    - upload_file: ローカルファイルから content_hash/size を保存
    """

    def __init__(self) -> None:
        self.files = {}

    def ensure_folder(self, path: str) -> None:
        return

    def get_metadata(self, dropbox_path: str):
        dp = dropbox_path if dropbox_path.startswith("/") else f"/{dropbox_path}"
        if dp in self.files:
            md = self.files[dp]
            return {
                "exists": True,
                "path": dp,
                "name": dp.split("/")[-1],
                "type": "file",
                "size": md["size"],
                "content_hash": md["content_hash"],
            }
        return {"exists": False, "path": dp}

    def upload_file(self, local_path: str, dropbox_path: str) -> None:
        dp = dropbox_path if dropbox_path.startswith("/") else f"/{dropbox_path}"
        size = Path(local_path).stat().st_size
        ch = dropbox_content_hash(local_path)
        self.files[dp] = {"size": size, "content_hash": ch}


class FlakyUploadDropboxClient(MemoryDropboxClient):
    """
    upload_file() が一時的に失敗し、その後成功するフェイク
    """

    def __init__(self, fail_times: int = 1) -> None:
        super().__init__()
        self.fail_times = fail_times

    def upload_file(self, local_path: str, dropbox_path: str) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            # TransferEngine側の分類では "429" / "Too Many Requests" で retryable=True
            raise Exception("HTTP 429 Too Many Requests")
        return super().upload_file(local_path, dropbox_path)


# ---- Tests ----
def test_retry_download_eventual_success(tmp_path: Path) -> None:
    s = Settings()
    s.DOWNLOAD_DIR = str(tmp_path / "downloads")
    s.STATE_BACKEND = "json"
    s.STATE_PATH = str(tmp_path / "state.json")
    s.FAILURE_LOG_PATH = str(tmp_path / "fail.jsonl")
    # リトライを高速化
    s.RETRY_MAX_ATTEMPTS = 3
    s.RETRY_BACKOFF_MULTIPLIER = 0.01
    s.RETRY_BACKOFF_MAX = 0.05

    store = StateStore(s)
    bookscan = FlakyBookscanClient(fail_times=2)
    dropbox = MemoryDropboxClient()
    engine = TransferEngine(s, bookscan, dropbox, store)

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

    # ダウンロードは2回失敗後に成功し、最終的にアップロードまで完了する
    engine.run(plan, dry_run=False)

    state = store.read()
    assert "42" in state["items"]
    meta = state["items"]["42"]
    assert int(meta["size"]) == 3
    assert meta["dropbox_path"].endswith("/file.pdf")
    # メモリDropboxにもファイルが存在している
    assert any(p.endswith("/file.pdf") for p in dropbox.files)


def test_retry_upload_429_eventual_success(tmp_path: Path) -> None:
    s = Settings()
    s.DOWNLOAD_DIR = str(tmp_path / "downloads2")
    s.STATE_BACKEND = "json"
    s.STATE_PATH = str(tmp_path / "state2.json")
    s.FAILURE_LOG_PATH = str(tmp_path / "fail2.jsonl")
    # リトライを高速化
    s.RETRY_MAX_ATTEMPTS = 3
    s.RETRY_BACKOFF_MULTIPLIER = 0.01
    s.RETRY_BACKOFF_MAX = 0.05

    store = StateStore(s)
    bookscan = StableBookscanClient()
    dropbox = FlakyUploadDropboxClient(fail_times=1)
    engine = TransferEngine(s, bookscan, dropbox, store)

    plan = [
        {
            "action": "upload",
            "book_id": "43",
            "title": "T2",
            "ext": "pdf",
            "size": 4,
            "relpath": "file2.pdf",
            "updated_at": "2024-08-05",
        }
    ]

    # 最初のuploadは429で失敗するが、再試行で成功する
    engine.run(plan, dry_run=False)

    state = store.read()
    assert "43" in state["items"]
    meta = state["items"]["43"]
    assert int(meta["size"]) == 4
    assert meta["dropbox_path"].endswith("/file2.pdf")
    # メモリDropboxにもファイルが存在している
    assert any(p.endswith("/file2.pdf") for p in dropbox.files)
