from __future__ import annotations

import re


def safe_filename(name: str, max_length: int = 150) -> str:
    """
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
