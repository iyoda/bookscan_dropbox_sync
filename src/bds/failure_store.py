from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .config import Settings


def _now_iso() -> str:
    # UTC naive with Z suffix for readability
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


class FailureRecord(BaseModel):
    """
    同期処理中の失敗イベントを記録するレコード
    - book_id: 対象アイテムのID
    - stage: 処理段階（download|upload|verify|state_update など）
    - error_class: エラー分類（例: rate_limited, http_error, server_error, integrity_mismatch, io_error, runtime_error, unknown_error）
    - retryable: リトライ可能かの推定
    - message: 簡易なエラーメッセージ
    - ts: 発生時刻（UTC ISO8601, Z）
    """

    book_id: str
    stage: str
    error_class: str
    retryable: bool
    message: str = ""
    ts: str = Field(default_factory=_now_iso)


class FailureStore:
    """
    永続失敗の記録ストア（M3 最小実装）
    - JSONバックエンド: FAILURE_LOG_PATH に JSON Lines として追記
    - SQLiteバックエンド: STATE_PATH のDBに failures テーブルを作成してINSERT
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.backend = "json" if settings.is_json_backend else "sqlite"
        if self.backend == "json":
            path = getattr(settings, "FAILURE_LOG_PATH", ".logs/failures.jsonl")
            self.log_path = Path(path)
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.db_path = Path(settings.STATE_PATH)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._sqlite_init()

    # ---- SQLite helpers ----
    def _sqlite_connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        return con

    def _sqlite_init(self) -> None:
        with closing(self._sqlite_connect()) as con, closing(con.cursor()) as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id TEXT,
                    stage TEXT,
                    error_class TEXT,
                    retryable INTEGER,
                    message TEXT,
                    ts TEXT
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_failures_ts ON failures(ts)")
            con.commit()

    # ---- Classification ----
    def _classify_exception(self, exc: BaseException) -> tuple[str, bool]:
        """
        ざっくりとしたエラーカテゴリ分類とリトライ可否の推定。
        依存の強い型判定は避け、メッセージ/一般的な例外で判定する。
        """
        msg = str(exc)
        lower = msg.lower()

        # 明示的な整合性系は非リトライ
        if (
            "content_hash mismatch" in lower
            or "size mismatch" in lower
            or "downloaded file is empty" in lower
        ):
            return "integrity_mismatch", False

        # レート制限/サーバ側の一時エラー
        if re.search(r"\b429\b", lower) or "too many requests" in lower:
            return "rate_limited", True
        if re.search(r"\b5\d{2}\b", lower) or "server error" in lower:
            return "server_error", True

        # タイムアウト/接続系はリトライ可
        if "timeout" in lower or "timed out" in lower:
            return "timeout", True
        if (
            "connection error" in lower
            or "connection reset" in lower
            or "connection aborted" in lower
        ):
            return "http_error", True

        # 一般的なI/O
        if isinstance(exc, OSError | IOError):
            return "io_error", False

        # requests系（文字列ベースでの緩い判定）
        if "http" in lower or "request" in lower:
            # HTTP由来で詳細不明 -> とりあえずリトライ可で分類
            return "http_error", True

        # 既定
        return "runtime_error", False

    def classify_exception(self, exc: BaseException) -> tuple[str, bool]:
        """
        例外を分類して (error_class, retryable) を返す公開API。
        """
        return self._classify_exception(exc)

    # ---- Public API ----
    def record_failure(self, book_id: str, stage: str, exc: BaseException) -> FailureRecord:
        error_class, retryable = self._classify_exception(exc)
        # メッセージは肥大化しすぎないよう切り詰め
        message = str(exc)
        if len(message) > 1000:
            message = message[:1000] + "...(truncated)"
        rec = FailureRecord(
            book_id=book_id,
            stage=stage,
            error_class=error_class,
            retryable=retryable,
            message=message,
        )

        if self.backend == "json":
            assert hasattr(self, "log_path")
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec.model_dump(), ensure_ascii=False) + "\n")
        else:
            assert hasattr(self, "db_path")
            with closing(self._sqlite_connect()) as con, closing(con.cursor()) as cur:
                cur.execute(
                    """
                    INSERT INTO failures (book_id, stage, error_class, retryable, message, ts)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec.book_id,
                        rec.stage,
                        rec.error_class,
                        1 if rec.retryable else 0,
                        rec.message,
                        rec.ts,
                    ),
                )
                con.commit()
        return rec

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        直近の失敗を返す（新しい順）。テストやデバッグ用途の簡易API。
        """
        if self.backend == "json":
            assert hasattr(self, "log_path")
            if not self.log_path.exists():
                return []
            try:
                lines = self.log_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                return []
            out: list[dict[str, Any]] = []
            for line in lines[-limit:]:
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        out.append(obj)
                except Exception:
                    continue
            # JSONLは時系列順で並んでいる前提。新しい順に反転。
            return list(reversed(out))
        else:
            assert hasattr(self, "db_path")
            with closing(self._sqlite_connect()) as con, closing(con.cursor()) as cur:
                cur.execute(
                    """
                    SELECT book_id, stage, error_class, retryable, message, ts
                    FROM failures
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                )
                rows = cur.fetchall()
                result: list[dict[str, Any]] = []
                for r in rows:
                    result.append(
                        {
                            "book_id": str(r["book_id"]),
                            "stage": str(r["stage"]),
                            "error_class": str(r["error_class"]),
                            "retryable": bool(int(r["retryable"])),
                            "message": str(r["message"]) if r["message"] is not None else "",
                            "ts": str(r["ts"]),
                        }
                    )
                return result
