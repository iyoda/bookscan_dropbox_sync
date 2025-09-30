from __future__ import annotations

import re
import hashlib
import time
import threading
from datetime import datetime, timezone
from typing import Optional


def safe_filename(name: str, max_length: int = 150) -> str:
    r"""
    簡易なファイル名正規化（初版）:
    - OS依存で問題になりやすい文字 / \ : * ? " < > | を "_" に置換
    - 連続空白を1つに圧縮し前後の空白を除去
    - 長すぎる名前は max_length で切り詰め
    """
    s = re.sub(r'[\\/:*?"<>|]', "_", name)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_length:
        s = s[:max_length].rstrip()
    return s


def parse_timestamp(value: str) -> Optional[datetime]:
    """
    文字列の日時をパースして naive UTC の datetime を返す。
    対応例: 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM:SS', ISO8601（末尾Zは+00:00として解釈）
    パースできない場合は None。
    """
    if not value:
        return None
    v = str(value).strip()
    dt: Optional[datetime] = None
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
    except Exception:
        dt = None
    if dt is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(v, fmt)
                break
            except Exception:
                continue
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def dropbox_content_hash(path: str, chunk_size: int = 4 * 1024 * 1024) -> str:
    """
    Dropbox-Content-Hash を計算する。
    仕様: 4MB チャンクごとに SHA256 を取り、そのダイジェスト列を連結したものに対して SHA256 を取り直した16進表現。
    参考: https://www.dropbox.com/developers/reference/content-hash
    """
    overall = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            overall.update(hashlib.sha256(chunk).digest())
    return overall.hexdigest()

class RateLimiter:
    """
    単純なQPSベースのレートリミッタ（プロセス内・スレッドセーフ）。
    - qps <= 0 の場合は無効（スロットルしない）
    - acquire()/throttle() 呼び出しごとに最小間隔(1/qps)を確保
    """
    def __init__(self, qps: float) -> None:
        try:
            qps_val = float(qps)
        except Exception:
            qps_val = 0.0
        self.min_interval: float = 1.0 / qps_val if qps_val > 0 else 0.0
        self._last: float = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = self.min_interval - (now - self._last)
            if sleep_for > 0:
                time.sleep(sleep_for)
                now = time.monotonic()
            self._last = now

    # alias
    def throttle(self) -> None:
        self.acquire()
