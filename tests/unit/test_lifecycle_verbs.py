from chrono_core.store.store import Store


def _seed_action(store: Store, text: str = "do thing") -> str:
    store.init_schema()
    pid = store.upsert_project(project_id="p", name="p", path="/tmp/p", relative_path="p")
    store.record_next_actions(pid, None, [text])
    row = store._connect().execute(
        "SELECT id FROM next_actions ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return row["id"]


def _seed_blocker(store: Store, title: str = "blocked thing") -> str:
    store.init_schema()
    pid = store.upsert_project(project_id="p", name="p", path="/tmp/p", relative_path="p")
    store.record_blockers(pid, None, [{"title": title}])
    row = store._connect().execute(
        "SELECT id FROM blockers ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return row["id"]


def test_cancel_then_reopen(tmp_path):
    store = Store(tmp_path / "d.db")
    aid = _seed_action(store)
    r1 = store.cancel_next_action(aid, reason="stale")
    assert r1 == {"ok": True, "already": False, "action_id": aid, "status": "cancelled"}
    r2 = store.cancel_next_action(aid)
    assert r2["already"] is True
    history = store._connect().execute(
        "SELECT raw_history_json, cancelled_at FROM next_actions WHERE id=?", (aid,)
    ).fetchone()
    assert "stale" in history["raw_history_json"]
    assert history["cancelled_at"]
    r3 = store.reopen_next_action(aid)
    assert r3["status"] == "open"


def test_cancel_rejected_for_superseded_action(tmp_path):
    store = Store(tmp_path / "d.db")
    old_id = _seed_action(store, "wrong wording")
    sup = store.supersede_next_action(old_id, "right wording")
    assert sup["ok"] is True
    r = store.cancel_next_action(old_id)
    assert r == {
        "ok": False,
        "action_id": old_id,
        "status": "superseded",
        "error": "already superseded; reopen or supersede instead",
    }
    row = store._connect().execute(
        "SELECT status FROM next_actions WHERE id=?", (old_id,)
    ).fetchone()
    assert row["status"] == "superseded"


def test_edit_appends_history(tmp_path):
    store = Store(tmp_path / "d.db")
    aid = _seed_action(store, "old text")
    r = store.edit_next_action(aid, "corrected text")
    assert r["ok"] is True
    row = store._connect().execute(
        "SELECT text, raw_history_json FROM next_actions WHERE id=?", (aid,)
    ).fetchone()
    assert row["text"] == "corrected text"
    assert "old text" in row["raw_history_json"]


def test_supersede_links_new_to_old(tmp_path):
    store = Store(tmp_path / "d.db")
    old_id = _seed_action(store, "wrong wording")
    r = store.supersede_next_action(old_id, "right wording")
    assert r["ok"] is True and r["status"] == "superseded"
    new_id = r["new_action_id"]
    row = store._connect().execute(
        "SELECT supersedes_id, status FROM next_actions WHERE id=?", (new_id,)
    ).fetchone()
    assert row["supersedes_id"] == old_id
    assert row["status"] == "open"


def test_supersede_already_superseded(tmp_path):
    store = Store(tmp_path / "d.db")
    old_id = _seed_action(store, "first")
    r1 = store.supersede_next_action(old_id, "second")
    assert r1["ok"] is True
    r2 = store.supersede_next_action(old_id, "third")
    assert r2 == {
        "ok": True,
        "already": True,
        "action_id": old_id,
        "status": "superseded",
        "new_action_id": None,
    }


def test_reopen_clears_completed_and_cancelled(tmp_path):
    store = Store(tmp_path / "d.db")
    aid = _seed_action(store)
    store.complete_next_action(aid)
    store.cancel_next_action(aid)
    r = store.reopen_next_action(aid)
    assert r == {"ok": True, "already": False, "action_id": aid, "status": "open"}
    r2 = store.reopen_next_action(aid)
    assert r2["already"] is True
    row = store._connect().execute(
        "SELECT status, completed_at, cancelled_at FROM next_actions WHERE id=?", (aid,)
    ).fetchone()
    assert row["status"] == "open"
    assert row["completed_at"] is None
    assert row["cancelled_at"] is None


def test_edit_preserves_status(tmp_path):
    store = Store(tmp_path / "d.db")
    aid = _seed_action(store)
    store.cancel_next_action(aid)
    r = store.edit_next_action(aid, "new wording")
    assert r["status"] == "cancelled"


def test_cancel_blocker_then_reopen(tmp_path):
    store = Store(tmp_path / "d.db")
    bid = _seed_blocker(store)
    r1 = store.cancel_blocker(bid, reason="obsolete")
    assert r1 == {"ok": True, "already": False, "blocker_id": bid, "status": "cancelled"}
    r2 = store.cancel_blocker(bid)
    assert r2["already"] is True
    row = store._connect().execute(
        "SELECT status, cancelled_at FROM blockers WHERE id=?", (bid,)
    ).fetchone()
    assert row["status"] == "cancelled"
    assert row["cancelled_at"]
    r3 = store.reopen_blocker(bid)
    assert r3 == {"ok": True, "already": False, "blocker_id": bid, "status": "open"}
    r4 = store.reopen_blocker(bid)
    assert r4["already"] is True
    row2 = store._connect().execute(
        "SELECT status, resolved_at, cancelled_at FROM blockers WHERE id=?", (bid,)
    ).fetchone()
    assert row2["status"] == "open"
    assert row2["resolved_at"] is None
    assert row2["cancelled_at"] is None


def test_resolve_then_reopen_blocker(tmp_path):
    store = Store(tmp_path / "d.db")
    bid = _seed_blocker(store)
    store.resolve_blocker(bid)
    r = store.reopen_blocker(bid)
    assert r == {"ok": True, "already": False, "blocker_id": bid, "status": "open"}
    row = store._connect().execute(
        "SELECT status, resolved_at FROM blockers WHERE id=?", (bid,)
    ).fetchone()
    assert row["status"] == "open"
    assert row["resolved_at"] is None


def test_edit_blocker_swaps_title(tmp_path):
    store = Store(tmp_path / "d.db")
    bid = _seed_blocker(store, "old title")
    r = store.edit_blocker(bid, "new title")
    assert r == {"ok": True, "already": False, "blocker_id": bid, "status": "open"}
    row = store._connect().execute(
        "SELECT title FROM blockers WHERE id=?", (bid,)
    ).fetchone()
    assert row["title"] == "new title"


def test_unknown_id_not_found(tmp_path):
    store = Store(tmp_path / "d.db")
    store.init_schema()
    assert store.cancel_next_action("act_missing") == {
        "ok": False,
        "action_id": "act_missing",
        "status": "not_found",
    }
    assert store.reopen_next_action("act_missing")["status"] == "not_found"
    assert store.edit_next_action("act_missing", "x")["status"] == "not_found"
    assert store.supersede_next_action("act_missing", "x")["status"] == "not_found"
    assert store.edit_blocker("blk_missing", "x")["status"] == "not_found"
    assert store.cancel_blocker("blk_missing")["status"] == "not_found"
    assert store.reopen_blocker("blk_missing")["status"] == "not_found"
