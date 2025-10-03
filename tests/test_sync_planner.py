from __future__ import annotations

from bds.config import Settings
from bds.sync_planner import SyncPlanner


def test_plan_filters_already_synced_and_builds_filename() -> None:
    settings = Settings()
    state = {
        "items": {
            "1": {
                "updated_at": "2024-08-01",
                "size": 100,
                "hash": "",
                "dropbox_path": "/x/Existing.pdf",
            }
        }
    }
    items = [
        {"id": "1", "title": "Existing", "ext": "pdf", "updated_at": "2024-08-01", "size": 100},
        {
            "id": "2",
            "title": "New / Title?*",
            "ext": "pdf",
            "updated_at": "2024-08-02",
            "size": 200,
        },
    ]
    planner = SyncPlanner(settings, state)
    plan = planner.plan(items)

    assert isinstance(plan, list)
    assert len(plan) == 1
    entry = plan[0]
    assert entry["book_id"] == "2"
    # safe_filename + 拡張子
    assert entry["filename"] == "New _ Title__.pdf"
    assert entry["relpath"] == "New _ Title__.pdf"


def test_plan_detects_updates_by_updated_at_or_size() -> None:
    settings = Settings()
    base_state = {
        "items": {
            "1": {
                "updated_at": "2024-08-01",
                "size": 100,
                "hash": "",
                "dropbox_path": "/x/Existing.pdf",
            }
        }
    }

    # updated_at が変われば更新として抽出
    items_updated_at = [
        {"id": "1", "title": "Existing", "ext": "pdf", "updated_at": "2024-08-02", "size": 100}
    ]
    plan_a = SyncPlanner(settings, base_state).plan(items_updated_at)
    assert len(plan_a) == 1 and plan_a[0]["book_id"] == "1"

    # size が変われば更新として抽出
    items_size = [
        {"id": "1", "title": "Existing", "ext": "pdf", "updated_at": "2024-08-01", "size": 101}
    ]
    plan_b = SyncPlanner(settings, base_state).plan(items_size)
    assert len(plan_b) == 1 and plan_b[0]["book_id"] == "1"
