import json
from pathlib import Path

from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.store.store import Store


def _seed(store: Store) -> str:
    store.init_schema()
    project_id = store.upsert_project(
        project_id="p_test", name="t", path="/tmp/t", relative_path="t"
    )
    for branch, text in (
        ("feat/novel", "novel action"),
        ("feat/platform", "platform action"),
    ):
        sid = store.create_session(
            project_id,
            HandoffPayload(summary=f"{branch} session"),
            GitState(branch=branch),
        )
        store.record_next_actions(project_id, sid, [text])
    return project_id


def test_default_resume_shows_only_current_branch_actions(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    pid = _seed(store)
    ctx = store.get_resume_context(pid, branch="feat/novel")
    texts = [a["text"] for a in ctx.next_actions]
    assert texts == ["novel action"]
    assert ctx.hidden_actions == 1
    assert ctx.branch == "feat/novel"


def test_include_all_returns_every_action(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    pid = _seed(store)
    ctx = store.get_resume_context(pid, include_all=True)
    assert len(ctx.next_actions) == 2
    assert ctx.hidden_actions == 0


def test_branchless_items_stay_visible(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    pid = store.upsert_project(
        project_id="p_x", name="x", path="/tmp/x", relative_path="x"
    )
    store.record_next_actions(pid, None, ["legacy action"])
    ctx = store.get_resume_context(pid, branch="feat/main")
    assert [a["text"] for a in ctx.next_actions] == ["legacy action"]


def _seed_many(store: Store, count: int) -> str:
    store.init_schema()
    project_id = store.upsert_project(
        project_id="p_bulk", name="b", path="/tmp/b", relative_path="b"
    )
    sid = store.create_session(
        project_id, HandoffPayload(summary="bulk session"), GitState(branch="feat/novel")
    )
    store.record_next_actions(project_id, sid, [f"action {i}" for i in range(count)])
    return project_id


def test_include_all_counts_hidden_beyond_limit(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    pid = _seed_many(store, 25)
    ctx = store.get_resume_context(pid, include_all=True, limit=20)
    assert len(ctx.next_actions) == 20
    assert ctx.hidden_actions == 5


def test_legacy_flat_callers_get_honest_counts_without_filtering(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    pid = _seed_many(store, 25)
    ctx = store.get_resume_context(pid)
    assert len(ctx.next_actions) == 20
    assert ctx.hidden_actions == 5


def test_limit_bounds_lists_and_reports_hidden(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    pid = _seed(store)
    sid = store.create_session(
        pid, HandoffPayload(summary="s"), GitState(branch="feat/novel")
    )
    store.record_next_actions(pid, sid, ["a1", "a2"])
    ctx = store.get_resume_context(pid, branch="feat/novel", limit=2)
    assert len(ctx.next_actions) == 2
    assert ctx.hidden_actions == 1
    d = json.loads(json.dumps(ctx.to_dict()))
    assert d["hidden_actions"] == 1
