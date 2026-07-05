from __future__ import annotations

import json
from pathlib import Path

from continuity_core import mcp_server
from continuity_core.domain.models import GitState, HandoffPayload
from continuity_core.store.store import Store
from continuity_core.workspace.resolver import resolve_project


def _seed_busy_project(db_path: Path, workspace: Path) -> Path:
    store = Store(db_path)
    store.init_schema()
    project_path = workspace / "example"
    project_path.mkdir(parents=True)
    project = resolve_project(project_path, workspace_root=workspace)
    project_id = store.get_or_create_project(project)
    payload = HandoffPayload(
        summary="A fairly long session summary describing everything that happened. " * 5,
        decisions=[{"title": f"Decision number {i} with rationale", "rationale": "x" * 80}
                   for i in range(10)],
        blockers=[{"title": f"Blocker number {i}", "status": "open"} for i in range(10)],
        next_actions=[f"Next action number {i} with some detail" for i in range(10)],
    )
    session_id = store.create_session(project_id, payload, GitState(branch="main"))
    store.record_decisions(project_id, session_id, payload.decisions)
    store.record_blockers(project_id, session_id, payload.blockers)
    store.record_next_actions(project_id, session_id, payload.next_actions)
    return project_path


def test_max_tokens_trims_result_to_budget(tmp_path: Path):
    db_path = tmp_path / "continuity.db"
    project_path = _seed_busy_project(db_path, tmp_path / "workspace")

    result = mcp_server.handle_get_resume_context(
        str(project_path),
        workspace_root=str(tmp_path / "workspace"),
        db_path=str(db_path),
        max_tokens=150,
    )

    assert result["truncated"] is True
    assert len(json.dumps(result)) // 4 <= 150
    assert len(result["recent_decisions"]) < 10


def test_generous_max_tokens_keeps_everything(tmp_path: Path):
    db_path = tmp_path / "continuity.db"
    project_path = _seed_busy_project(db_path, tmp_path / "workspace")

    result = mcp_server.handle_get_resume_context(
        str(project_path),
        workspace_root=str(tmp_path / "workspace"),
        db_path=str(db_path),
        max_tokens=100_000,
    )

    assert result["truncated"] is False
    assert len(result["active_blockers"]) == 10
    assert len(result["next_actions"]) == 10
    assert len(result["recent_decisions"]) == 10


def test_tiny_budget_still_returns_project_identity(tmp_path: Path):
    db_path = tmp_path / "continuity.db"
    project_path = _seed_busy_project(db_path, tmp_path / "workspace")

    result = mcp_server.handle_get_resume_context(
        str(project_path),
        workspace_root=str(tmp_path / "workspace"),
        db_path=str(db_path),
        max_tokens=1,
    )

    assert result["truncated"] is True
    assert result["project_name"] == "example"
    assert result["active_blockers"] == []
    assert result["next_actions"] == []
    assert result["recent_decisions"] == []


def test_no_max_tokens_leaves_result_untouched(tmp_path: Path):
    db_path = tmp_path / "continuity.db"
    project_path = _seed_busy_project(db_path, tmp_path / "workspace")

    result = mcp_server.handle_get_resume_context(
        str(project_path),
        workspace_root=str(tmp_path / "workspace"),
        db_path=str(db_path),
    )

    assert "truncated" not in result
    assert len(result["recent_decisions"]) == 10
