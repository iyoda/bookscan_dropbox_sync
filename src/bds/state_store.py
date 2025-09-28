from __future__ import annotations

from typing import Any, Dict

from .config import Settings


class StateStore:
    """同期済み情報の保存（JSON/SQLite）（M1以降で実装予定の空実装）"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def read(self) -> Dict[str, Any]:
        """Stateを読み込む"""
        raise NotImplementedError

    def write(self, state: Dict[str, Any]) -> None:
        """Stateを書き出す"""
        raise NotImplementedError
