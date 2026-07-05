from __future__ import annotations

import json
from pathlib import Path

from continuity_core import mcp_server
from continuity_core.cli import build_parser, main
from continuity_core.domain.models import GitState, HandoffPayload
from continuity_core.management.distill import distill_project
from continuity_core.resume import format_resume
from continuity_core.store.store import Store
from continuity_core.workspace.resolver import resolve_project


def _seed_project_with_records(store: Store, workspace: Path) -> tuple[str, str, str]:
    """Create a project with one open blocker and one open next action."""
    store.init_schema()
    project_path = workspace / "example"
    project_path.mkdir(parents=True)
    project = resolve_project(project_path, workspace_root=workspace)
    project_id = store.get_or_create_project(project)
    payload = HandoffPayload(
        summary="Session with open work.",
        blockers=[{"title": "Need credentials", "status": "open"}],
        next_actions=["Ship lifecycle"],
    )
    session_id = store.create_session(project_id, payload, GitState(branch="main"))
    store.record_blockers(project_id, session_id, payload.blockers)
    store.record_next_actions(project_id, session_id, payload.next_actions)

    context = store.get_resume_context(project_id)
    blocker_id = context.active_blockers[0]["id"]
    action_id = context.next_actions[0]["id"]
    return project_id, blocker_id, action_id


def test_resolve_blocker_clears_it_from_resume_context(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    project_id, blocker_id, _ = _seed_project_with_records(store, tmp_path / "workspace")

    assert store.resolve_blocker(blocker_id) is True

    context = store.get_resume_context(project_id)
    assert context.active_blockers == []
    row = (
        store._connect()
        .execute("SELECT status, resolved_at FROM blockers WHERE id = ?", (blocker_id,))
        .fetchone()
    )
    assert row["status"] == "resolved"
    assert row["resolved_at"] is not None


def test_complete_next_action_clears_it_from_resume_context(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    project_id, _, action_id = _seed_project_with_records(store, tmp_path / "workspace")

    assert store.complete_next_action(action_id) is True

    context = store.get_resume_context(project_id)
    assert context.next_actions == []
    row = (
        store._connect()
        .execute("SELECT status, completed_at FROM next_actions WHERE id = ?", (action_id,))
        .fetchone()
    )
    assert row["status"] == "done"
    assert row["completed_at"] is not None


def test_resolve_blocker_returns_false_for_unknown_id(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.init_schema()
    assert store.resolve_blocker("blk_missing") is False
    assert store.complete_next_action("act_missing") is False


def test_distill_reports_active_after_blocker_resolved(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    workspace = tmp_path / "workspace"
    _, blocker_id, _ = _seed_project_with_records(store, workspace)
    store.resolve_blocker(blocker_id)

    result = distill_project(cwd=workspace / "example", workspace_root=workspace, store=store)

    assert result["phase"] == "active"
    assert result["active_blocker_count"] == 0


def test_blocker_resolve_parser_defaults():
    args = build_parser().parse_args(["blocker", "resolve", "blk_abc"])

    assert args.command == "blocker"
    assert args.blocker_command == "resolve"
    assert args.blocker_id == "blk_abc"


def test_action_complete_parser_defaults():
    args = build_parser().parse_args(["action", "complete", "act_abc"])

    assert args.command == "action"
    assert args.action_command == "complete"
    assert args.action_id == "act_abc"


def test_blocker_resolve_main_emits_json(tmp_path: Path, capsys):
    db_path = tmp_path / "continuity.db"
    store = Store(db_path)
    _, blocker_id, _ = _seed_project_with_records(store, tmp_path / "workspace")

    code = main(["blocker", "resolve", blocker_id, "--db-path", str(db_path)])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["ok"] is True
    assert data["blocker_id"] == blocker_id
    assert data["status"] == "resolved"


def test_blocker_resolve_main_fails_for_unknown_id(tmp_path: Path, capsys):
    db_path = tmp_path / "continuity.db"
    Store(db_path).init_schema()

    code = main(["blocker", "resolve", "blk_missing", "--db-path", str(db_path)])

    data = json.loads(capsys.readouterr().out)
    assert code == 1
    assert data["ok"] is False


def test_action_complete_main_emits_json(tmp_path: Path, capsys):
    db_path = tmp_path / "continuity.db"
    store = Store(db_path)
    _, _, action_id = _seed_project_with_records(store, tmp_path / "workspace")

    code = main(["action", "complete", action_id, "--db-path", str(db_path)])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["ok"] is True
    assert data["action_id"] == action_id
    assert data["status"] == "done"


def test_mcp_handle_resolve_blocker(tmp_path: Path):
    db_path = tmp_path / "continuity.db"
    store = Store(db_path)
    _, blocker_id, _ = _seed_project_with_records(store, tmp_path / "workspace")

    result = mcp_server.handle_resolve_blocker(blocker_id, db_path=str(db_path))

    assert result["ok"] is True
    assert result["blocker_id"] == blocker_id
    assert result["status"] == "resolved"


def test_mcp_handle_complete_action(tmp_path: Path):
    db_path = tmp_path / "continuity.db"
    store = Store(db_path)
    _, _, action_id = _seed_project_with_records(store, tmp_path / "workspace")

    result = mcp_server.handle_complete_action(action_id, db_path=str(db_path))

    assert result["ok"] is True
    assert result["action_id"] == action_id
    assert result["status"] == "done"


def test_mcp_lifecycle_tools_registered():
    import anyio

    tools = anyio.run(mcp_server.mcp.list_tools)
    names = {tool.name for tool in tools}
    assert "continuity_core_resolve_blocker" in names
    assert "continuity_core_complete_action" in names


def test_format_resume_shows_ids_for_blockers_and_actions(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    project_id, blocker_id, action_id = _seed_project_with_records(
        store, tmp_path / "workspace"
    )

    text = format_resume(store.get_resume_context(project_id))

    assert f"[{blocker_id}] Need credentials" in text
    assert f"[{action_id}] Ship lifecycle" in text
