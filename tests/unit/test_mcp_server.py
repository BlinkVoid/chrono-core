from __future__ import annotations

from pathlib import Path

from continuity_core.domain.models import GitState, HandoffPayload
from continuity_core.mcp_server import (
    DEFAULT_WORKSPACE_ROOT,
    get_resume_context_tool,
    handle_get_resume_context,
    handle_resolve_project,
    handle_session_handoff,
    resolve_project_tool,
    session_handoff_tool,
)
from continuity_core.store.store import Store
from continuity_core.workspace.resolver import resolve_project


def test_handle_resolve_project_finds_marker(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "example"
    nested = project / "src"
    nested.mkdir(parents=True)
    (project / ".git").mkdir()

    result = handle_resolve_project(str(nested), workspace_root=str(workspace))

    assert result["name"] == "example"
    assert result["marker"] == ".git"
    assert result["relative_path"] == "example"
    assert "project_id" in result


def test_handle_resolve_project_defaults(tmp_path: Path):
    project = tmp_path / "some-project"
    project.mkdir(parents=True)
    (project / "README.md").write_text("hello")

    result = handle_resolve_project(str(project), workspace_root=str(tmp_path))

    assert result["name"] == "some-project"
    assert result["marker"] == "README.md"


def test_resolve_project_tool_wraps_handler(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname = \"proj\"\n")

    result = resolve_project_tool(str(project), workspace_root=str(tmp_path))

    assert result["name"] == "proj"
    assert result["marker"] == "pyproject.toml"


def test_handle_session_handoff_persists_records(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    db_path = tmp_path / "continuity.db"

    result = handle_session_handoff(
        str(project),
        "Implemented MCP handlers.",
        workspace_root=str(workspace),
        db_path=str(db_path),
        files_changed=["src/mcp_server.py"],
        tests=["pytest: passed"],
        decisions=[{"title": "Use FastMCP", "rationale": "simple"}],
        blockers=[{"title": "Need tests", "status": "open"}],
        next_actions=["Add docs"],
        risks=["Tool naming"],
        agent_name="test-agent",
    )

    assert result["ok"] is True
    assert "project_id" in result
    assert "session_id" in result
    assert "Need tests" in result["resume_hint"]

    store = Store(str(db_path))
    context = store.get_resume_context(result["project_id"])
    assert context.project_name == "example"
    assert context.summary == "Implemented MCP handlers."
    assert len(context.active_blockers) == 1
    assert len(context.next_actions) == 1


def test_session_handoff_tool_wraps_handler(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    db_path = tmp_path / "continuity.db"

    result = session_handoff_tool(
        str(project),
        "Tool test.",
        workspace_root=str(workspace),
        db_path=str(db_path),
    )

    assert result["ok"] is True
    assert result["resume_hint"] == "Tool test."


def test_handle_get_resume_context_for_existing_project(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    db_path = tmp_path / "continuity.db"

    store = Store(str(db_path))
    store.init_schema()
    resolved = resolve_project(project, workspace_root=workspace)
    store.get_or_create_project(resolved)
    payload = HandoffPayload(summary="Earlier work.", next_actions=["Step 1"])
    session_id = store.create_session(resolved.project_id, payload, GitState(branch="main"))
    store.record_next_actions(resolved.project_id, session_id, payload.next_actions)

    result = handle_get_resume_context(
        str(project),
        workspace_root=str(workspace),
        db_path=str(db_path),
    )

    assert result["project_name"] == "example"
    assert result["summary"] == "Earlier work."
    assert len(result["next_actions"]) == 1


def test_handle_get_resume_context_for_unknown_project(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    db_path = tmp_path / "continuity.db"

    result = handle_get_resume_context(
        str(project),
        workspace_root=str(workspace),
        db_path=str(db_path),
    )

    assert result["project_name"] == "unknown"


def test_get_resume_context_tool_passes_max_tokens(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    db_path = tmp_path / "continuity.db"

    result = get_resume_context_tool(
        str(project),
        workspace_root=str(workspace),
        db_path=str(db_path),
        max_tokens=4096,
    )

    assert result["project_name"] == "unknown"
    assert result["max_tokens"] == 4096


def test_mcp_server_constants():
    assert Path(DEFAULT_WORKSPACE_ROOT).name == "workspace"
