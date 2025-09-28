from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .config import Settings


class StateStore:
    """
    同期済み情報の保存（M1: JSONバックエンド）
    - 形式（初版）: {"items": {<book_id>: {<meta...>}}}
      例のメタ: {"updated_at": "...", "size": 1234, "hash": "...", "dropbox_path": "..."}
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not settings.is_json_backend:
            # M1ではJSONのみサポート
            raise NotImplementedError("Only JSON backend is supported in M1.")
        self.path = Path(settings.STATE_PATH)

    def _default_state(self) -> Dict[str, Any]:
        return {"items": {}}

    def read(self) -> Dict[str, Any]:
        """
        Stateを読み込む。存在しない/壊れている場合は既定の空状態を返す。
        """
        if not self.path.exists():
            return self._default_state()
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            return self._default_state()
        except json.JSONDecodeError:
            return self._default_state()

    def write(self, state: Dict[str, Any]) -> None:
        """
        Stateを書き出す。必要なら親ディレクトリを作成。
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)

    # 便利メソッド（M1）
    def get_item(self, book_id: str) -> Optional[Dict[str, Any]]:
        """
        指定book_idのメタ情報を返す（存在しない場合はNone）
        """
        state = self.read()
        items = state.get("items", {})
        result = items.get(book_id)
        if isinstance(result, dict):
            return result
        return None

    def upsert_item(self, book_id: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        """
        指定book_idのメタ情報を追加/更新し、保存後の最新Stateを返す。
        例のmeta: {"updated_at": "...", "size": 1234, "hash": "...", "dropbox_path": "..."}
        """
        state = self.read()
        items = state.get("items")
        if not isinstance(items, dict):
            items = {}
            state["items"] = items
        items[book_id] = meta
        self.write(state)
        return state
