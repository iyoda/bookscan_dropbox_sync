from __future__ import annotations

from typing import Any, Dict, List


class TransferEngine:
    """
    ダウンロード→一時フォルダ→Dropboxアップロードを担うエンジン（M1で実装予定の空実装）
    - M1: 単一スレッドでの最小実装（小サイズ前提）
    - 成功時にStateを更新（後続のStateStore連携で実装）
    """

    def run(self, plan: List[Dict[str, Any]], dry_run: bool = False) -> None:
        """
        与えられたアップロード計画(plan)を実行する。
        - dry_run=True の場合は計画の表示のみ
        """
        raise NotImplementedError
