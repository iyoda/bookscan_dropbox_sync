from __future__ import annotations

from typing import Any, TypedDict

from .config import Settings
from .util import safe_filename


class BookItem(TypedDict, total=False):
    id: str
    title: str | None
    ext: str
    updated_at: str
    size: int


class StateItem(TypedDict, total=False):
    updated_at: str
    size: int
    hash: str
    dropbox_path: str


class PlanEntry(TypedDict, total=False):
    action: str  # "upload"
    book_id: str
    relpath: str
    filename: str
    title: str
    ext: str
    updated_at: str
    size: int
    pdf_url: str
    showbook_url: str


class SyncPlanner:
    """
    Stateとの差分計算、命名規則適用（M1）
    - 新規/更新のみ抽出し、アップロード計画のリストを返す
    - 命名規則: safe_filename(title) + .ext（M1はルート直下に配置）
    """

    def __init__(self, settings: Settings, state: dict[str, Any]) -> None:
        self.settings = settings
        self.state = state

    def _build_filename(self, item: BookItem) -> str:
        ext = item.get("ext") or "pdf"
        if not ext.startswith("."):
            ext = f".{ext}"
        title = item.get("title") or item.get("id") or "unknown"
        normalized = safe_filename(str(title))
        if not normalized:
            normalized = "unknown"
        return f"{normalized}{ext}"

    def _needs_upload(self, book_id: str, item: BookItem) -> bool:
        current: StateItem | None = self.state.get("items", {}).get(book_id)
        if not current:
            return True
        # 簡易判定（M1）: updated_at または size が変わっていれば更新とみなす
        updated_at = item.get("updated_at")
        size = item.get("size")
        cur_updated = current.get("updated_at") if current else None
        cur_size = current.get("size") if current else None
        if updated_at and cur_updated and updated_at != cur_updated:
            return True
        return bool(size is not None and cur_size is not None and size != cur_size)

    def plan(self, items: list[dict[str, Any]]) -> list[PlanEntry]:
        plan: list[PlanEntry] = []
        for raw in items:
            item: BookItem = raw  # type: ignore[assignment]
            book_id = str(item.get("id") or "")
            if not book_id:
                # IDがなければスキップ
                continue
            if not self._needs_upload(book_id, item):
                continue
            filename = self._build_filename(item)
            relpath = filename  # M1: サブフォルダなし、ルート直下
            entry: PlanEntry = {
                "action": "upload",
                "book_id": book_id,
                "relpath": relpath,
                "filename": filename,
                "title": str(item.get("title") or ""),
                "ext": str(item.get("ext") or "pdf"),
                "updated_at": str(item.get("updated_at") or ""),
                "size": int(item.get("size") or 0),
            }
            if "pdf_url" in item and item.get("pdf_url"):
                entry["pdf_url"] = str(item["pdf_url"])  # type: ignore[typeddict-item]
            if "showbook_url" in item and item.get("showbook_url"):
                entry["showbook_url"] = str(item["showbook_url"])  # type: ignore[typeddict-item]
            plan.append(entry)
        return plan
