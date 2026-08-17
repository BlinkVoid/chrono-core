from __future__ import annotations

import json
from pathlib import Path

from chrono_core.cli import build_parser, main
from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.management.distill import distill_project
from chrono_core.mcp_server import distill_project_tool, handle_distill_project
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


def _seed_project(store: Store, workspace: Path) -> Path:
    project_path = workspace / "example"
    project_path.mkdir(parents=True)
    (project_path / ".git").mkdir()
    project = resolve_project(project_path, workspace_root=workspace)
    store.init_schema()
    store.get_or_create_project(project)
    payload = HandoffPayload(
        summary="Implemented management state capture.",
        blockers=[{"title": "Need stale-doc detector", "status": "open"}],
        next_actions=["Add reconciliation workflow"],
        decisions=[{"title": "Use deterministic distillation", "rationale": "Keep MVP local"}],
    )
    session_id = store.create_session(project.project_id, payload, GitState(branch="main"))
    store.record_blockers(project.project_id, session_id, payload.blockers)
    store.record_next_actions(project.project_id, session_id, payload.next_actions)
    store.record_decisions(project.project_id, session_id, payload.decisions)
    return project_path


def test_distill_project_updates_project_state(tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    store = Store(db_path)
    project_path = _seed_project(store, workspace)

    result = distill_project(
        cwd=project_path,
        workspace_root=workspace,
        store=Store(db_path),
    )

    assert result["ok"] is True
    assert result["phase"] == "blocked"
    assert result["summary"] == "Implemented management state capture."
    assert result["active_blocker_count"] == 1
    assert result["next_action_count"] == 1
    assert result["recent_decision_count"] == 1

    row = (
        Store(db_path)
        ._connect()
        .execute("SELECT phase, summary FROM projects WHERE id = ?", (result["project_id"],))
        .fetchone()
    )
    assert row["phase"] == "blocked"
    assert row["summary"] == "Implemented management state capture."


def test_distill_project_for_project_without_sessions_is_unknown(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project_path = workspace / "empty"
    project_path.mkdir(parents=True)
    (project_path / ".git").mkdir()
    store = Store(tmp_path / "chrono.db")

    result = distill_project(cwd=project_path, workspace_root=workspace, store=store)

    assert result["ok"] is True
    assert result["phase"] == "unknown"
    assert result["summary"] == "No sessions captured yet."


def test_distill_parser_defaults():
    args = build_parser().parse_args(["distill"])

    assert args.command == "distill"
    assert args.cwd == "."
    from chrono_core.config import default_db_path

    assert args.db_path == default_db_path()


def test_distill_main_emits_json(tmp_path: Path, capsys):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    project_path = _seed_project(Store(db_path), workspace)

    code = main(
        [
            "distill",
            "--cwd",
            str(project_path),
            "--workspace-root",
            str(workspace),
            "--db-path",
            str(db_path),
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["ok"] is True
    assert data["phase"] == "blocked"


def test_mcp_distill_project_wraps_handler(tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    project_path = _seed_project(Store(db_path), workspace)

    handler_result = handle_distill_project(
        str(project_path),
        workspace_root=str(workspace),
        db_path=str(db_path),
    )
    tool_result = distill_project_tool(
        str(project_path),
        workspace_root=str(workspace),
        db_path=str(db_path),
    )

    assert handler_result["phase"] == "blocked"
    assert tool_result["phase"] == "blocked"
