from __future__ import annotations

import json
import sqlite3
from contextlib import closing, suppress
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import Settings


class StateItemModel(BaseModel):
    updated_at: str | None = None
    size: int | None = None
    hash: str | None = None
    dropbox_path: str | None = None

    model_config = ConfigDict(extra="ignore")


class StateModel(BaseModel):
    version: int = 1
    items: dict[str, StateItemModel] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class StateStore:
    """
    同期済み情報の保存
    - M1: JSONバックエンド
    - M2: SQLiteバックエンドを追加（STATE_BACKEND=sqlite 時）
    どちらのバックエンドでも read()/write()/get_item()/upsert_item() のAPIは共通。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.backend = "json" if settings.is_json_backend else "sqlite"
        self.path = Path(settings.STATE_PATH)

        if self.backend == "sqlite":
            # DBディレクトリ確保と初期化
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._sqlite_init()
            self._sqlite_maybe_migrate()

    # 共通: デフォルト状態
    def _default_state(self) -> dict[str, Any]:
        return {"version": 1, "items": {}}

    # JSON バックエンド実装
    def _json_read(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default_state()
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            return self._default_state()

        if not isinstance(data, dict):
            return self._default_state()

        try:
            model = StateModel.model_validate(data)
            return model.model_dump()
        except ValidationError:
            return self._default_state()

    def _json_write(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # スキーマ検証（不正なら最小限の補正を行ってから保存）
        try:
            model = StateModel.model_validate(state)
        except ValidationError:
            items = state.get("items", {}) if isinstance(state, dict) else {}
            if not isinstance(items, dict):
                items = {}
            fixed = {
                "version": state.get("version", 1) if isinstance(state, dict) else 1,
                "items": items,
            }
            model = StateModel.model_validate(fixed)

        with self.path.open("w", encoding="utf-8") as f:
            json.dump(model.model_dump(), f, ensure_ascii=False, indent=2, sort_keys=True)

    # SQLite バックエンド実装
    def _sqlite_connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path))
        con.row_factory = sqlite3.Row
        return con

    def _sqlite_init(self) -> None:
        with closing(self._sqlite_connect()) as con, closing(con.cursor()) as cur:
            # 軽い信頼性向上（任意）
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    book_id TEXT PRIMARY KEY,
                    updated_at TEXT,
                    size INTEGER,
                    hash TEXT,
                    dropbox_path TEXT
                )
                """
            )
            # シンプルなインデックス（検索用途）
            cur.execute("CREATE INDEX IF NOT EXISTS idx_items_updated_at ON items(updated_at);")
            con.commit()

    def _sqlite_maybe_migrate(self) -> None:
        """
        STATE_BACKEND=sqlite 初回起動時に、既存のJSON Stateがあれば自動でインポートする（非破壊）。
        - itemsテーブルが空の場合のみ実行
        - 候補: <STATE_PATHの拡張子を.jsonにしたもの>, .state/state.json
        """
        # 既にデータがあれば何もしない
        try:
            with closing(self._sqlite_connect()) as con, closing(con.cursor()) as cur:
                cur.execute("SELECT COUNT(*) FROM items")
                row = cur.fetchone()
                if row and int(row[0]) > 0:
                    return
        except Exception:
            # テーブル未作成などの例外は無視（以降の処理で作成/書込み）
            return

        candidates: list[Path] = []
        try:
            if self.path.suffix:
                candidates.append(self.path.with_suffix(".json"))
        except Exception:
            pass
        candidates.append(Path(".state/state.json"))

        # 重複除去（順序維持）
        uniq: list[Path] = []
        seen = set()
        for p in candidates:
            if p in seen:
                continue
            seen.add(p)
            uniq.append(p)

        for p in uniq:
            try:
                if not p.exists():
                    continue
                with p.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    continue
                model = StateModel.model_validate(data)
                # 検証後にSQLiteへ書き込み
                self._sqlite_write(model.model_dump())
                break
            except Exception:
                # 破損/検証失敗などは次候補へ
                continue

    def _sqlite_read(self) -> dict[str, Any]:
        items: dict[str, dict[str, Any]] = {}
        if not self.path.exists():
            return {"version": 1, "items": items}
        with closing(self._sqlite_connect()) as con, closing(con.cursor()) as cur:
            cur.execute("SELECT book_id, updated_at, size, hash, dropbox_path FROM items")
            for row in cur.fetchall():
                book_id = str(row["book_id"])
                meta: dict[str, Any] = {}
                if row["updated_at"] is not None:
                    meta["updated_at"] = str(row["updated_at"])
                if row["size"] is not None:
                    with suppress(Exception):
                        meta["size"] = int(row["size"])
                if row["hash"] is not None:
                    meta["hash"] = str(row["hash"])
                if row["dropbox_path"] is not None:
                    meta["dropbox_path"] = str(row["dropbox_path"])
                items[book_id] = meta
        return {"version": 1, "items": items}

    def _sqlite_write(self, state: dict[str, Any]) -> None:
        # スキーマ検証（可能なら行う）
        try:
            model = StateModel.model_validate(state)
            data = model.model_dump()
            items = data.get("items", {})
        except ValidationError:
            # items のみ最低限取り出す
            items = state.get("items", {}) if isinstance(state, dict) else {}
            if not isinstance(items, dict):
                items = {}

        with closing(self._sqlite_connect()) as con, closing(con.cursor()) as cur:
            # 完全同期（全削除→再投入）
            cur.execute("DELETE FROM items")
            if items:
                for book_id, meta in items.items():
                    if not isinstance(meta, dict):
                        meta = {}
                    updated_at = meta.get("updated_at")
                    size = meta.get("size")
                    try:
                        size_int = int(size) if size is not None else None
                    except Exception:
                        size_int = None
                    hash_val = meta.get("hash")
                    dropbox_path = meta.get("dropbox_path")
                    cur.execute(
                        """
                        INSERT INTO items (book_id, updated_at, size, hash, dropbox_path)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(book_id) DO UPDATE SET
                            updated_at=excluded.updated_at,
                            size=excluded.size,
                            hash=excluded.hash,
                            dropbox_path=excluded.dropbox_path
                        """,
                        (str(book_id), updated_at, size_int, hash_val, dropbox_path),
                    )
            con.commit()

    # 公開API
    def read(self) -> dict[str, Any]:
        """
        Stateを読み込む。存在しない/壊れている場合は既定の空状態を返す。
        バックエンドに応じてJSON/SQLiteからロード。
        """
        if self.backend == "json":
            return self._json_read()
        return self._sqlite_read()

    def write(self, state: dict[str, Any]) -> None:
        """
        Stateを書き出す。必要なら親ディレクトリ/テーブルを作成。
        バックエンドに応じてJSON/SQLiteへ保存。
        """
        if self.backend == "json":
            self._json_write(state)
        else:
            # 念のため初期化（初回ファイル作成時）
            if not self.path.exists():
                self._sqlite_init()
            self._sqlite_write(state)

    # 便利メソッド（両バックエンド共通のシグネチャ）
    def get_item(self, book_id: str) -> dict[str, Any] | None:
        """
        指定book_idのメタ情報を返す（存在しない場合はNone）
        """
        if self.backend == "json":
            state = self.read()
            items = state.get("items", {})
            result = items.get(book_id)
            if isinstance(result, dict):
                return result
            return None

        # SQLite
        if not self.path.exists():
            return None
        with closing(self._sqlite_connect()) as con, closing(con.cursor()) as cur:
            cur.execute(
                "SELECT updated_at, size, hash, dropbox_path FROM items WHERE book_id = ?",
                (book_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            meta: dict[str, Any] = {}
            if row["updated_at"] is not None:
                meta["updated_at"] = str(row["updated_at"])
            if row["size"] is not None:
                with suppress(Exception):
                    meta["size"] = int(row["size"])
            if row["hash"] is not None:
                meta["hash"] = str(row["hash"])
            if row["dropbox_path"] is not None:
                meta["dropbox_path"] = str(row["dropbox_path"])
            return meta

    def upsert_item(self, book_id: str, meta: dict[str, Any]) -> dict[str, Any]:
        """
        指定book_idのメタ情報を追加/更新し、保存後の最新Stateを返す。
        例のmeta: {"updated_at": "...", "size": 1234, "hash": "...", "dropbox_path": "..."}
        """
        if self.backend == "json":
            state = self.read()
            items = state.get("items")
            if not isinstance(items, dict):
                items = {}
                state["items"] = items
            items[book_id] = meta
            self.write(state)
            return state

        # SQLite
        try:
            valid = StateItemModel.model_validate(meta).model_dump()
        except ValidationError:
            # 既知キーのみ採用
            valid = {
                k: meta.get(k) for k in ("updated_at", "size", "hash", "dropbox_path") if k in meta
            }
        with closing(self._sqlite_connect()) as con, closing(con.cursor()) as cur:
            size = valid.get("size")
            try:
                size_int = int(size) if size is not None else None
            except Exception:
                size_int = None
            cur.execute(
                """
                INSERT INTO items (book_id, updated_at, size, hash, dropbox_path)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    size=excluded.size,
                    hash=excluded.hash,
                    dropbox_path=excluded.dropbox_path
                """,
                (
                    book_id,
                    valid.get("updated_at"),
                    size_int,
                    valid.get("hash"),
                    valid.get("dropbox_path"),
                ),
            )
            con.commit()
        # 最新状態を返す（整合性のためreadで統一フォーマットに）
        return self.read()
