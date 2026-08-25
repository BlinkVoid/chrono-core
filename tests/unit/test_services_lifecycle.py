from pathlib import Path

from chrono_core.services import (
    cancel_action,
    edit_action,
    open_store,
    reopen_action,
    supersede_action,
)


def _seed(db_path: Path) -> str:
    store = open_store(str(db_path))
    pid = store.upsert_project(project_id="p", name="p", path="/tmp/p", relative_path="p")
    store.record_next_actions(pid, None, ["first cut"])
    return store._connect().execute(
        "SELECT id FROM next_actions LIMIT 1"
    ).fetchone()["id"]


def test_service_roundtrip(tmp_path: Path):
    db = str(tmp_path / "s.db")
    aid = _seed(tmp_path / "s.db")

    edited = edit_action(db, aid, "second cut")
    assert edited["ok"] is True and edited["verb"] == "edit"

    cancelled = cancel_action(db, aid, reason="obsolete")
    assert cancelled["ok"] is True and cancelled["status"] == "cancelled"

    reopened = reopen_action(db, aid)
    assert reopened["status"] == "open"

    sup = supersede_action(db, aid, "third cut")
    assert sup["new_action_id"].startswith("act_")


def test_open_store_is_cached(tmp_path: Path):
    db = str(tmp_path / "c.db")
    s1 = open_store(db)
    s2 = open_store(db)
    assert s1 is s2
