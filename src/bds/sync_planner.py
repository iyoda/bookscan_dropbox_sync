from __future__ import annotations

from typing import Any, Dict, List


class SyncPlanner:
    """
    Stateとの差分計算、命名規則適用（M1で実装予定の空実装）
    - M1では新規/更新のみ抽出し、アップロード計画のリストを返す
    """

    def __init__(self) -> None:
        ...

    def plan(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """新規/更新のみ抽出（M1で実装）"""
        raise NotImplementedError
