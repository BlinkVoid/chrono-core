from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.mcp_server import (
    get_resume_context_tool,
    handle_get_resume_context,
    handle_record_blocker,
    handle_record_decision,
    handle_resolve_project,
    handle_session_handoff,
    record_blocker_tool,
    record_decision_tool,
    resolve_project_tool,
    session_handoff_tool,
)
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


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
    db_path = tmp_path / "chrono.db"

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
    db_path = tmp_path / "chrono.db"

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
    db_path = tmp_path / "chrono.db"

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


def _seed_two_branch_project(workspace: Path, db_path: Path) -> Path:
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    store = Store(str(db_path))
    store.init_schema()
    resolved = resolve_project(project, workspace_root=workspace)
    pid = store.get_or_create_project(resolved)
    for branch, text in (
        ("feat/novel", "novel action"),
        ("feat/platform", "platform action"),
    ):
        sid = store.create_session(
            pid, HandoffPayload(summary=f"{branch} session"), GitState(branch=branch)
        )
        store.record_next_actions(pid, sid, [text])
    return project


def test_handle_get_resume_context_defaults_to_current_branch(
    monkeypatch, tmp_path: Path
):
    from chrono_core.domain.models import GitState as _GitState

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db_path = tmp_path / "chrono.db"
    project = _seed_two_branch_project(workspace, db_path)

    monkeypatch.setattr(
        "chrono_core.mcp_server.read_git_state",
        lambda _: _GitState(branch="feat/novel"),
    )

    result = handle_get_resume_context(
        str(project),
        workspace_root=str(workspace),
        db_path=str(db_path),
    )

    assert [a["text"] for a in result["next_actions"]] == ["novel action"]
    assert result["hidden_actions"] > 0
    assert result["hidden_blockers"] >= 0


def test_handle_get_resume_context_include_all_shows_everything(
    monkeypatch, tmp_path: Path
):
    from chrono_core.domain.models import GitState as _GitState

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db_path = tmp_path / "chrono.db"
    project = _seed_two_branch_project(workspace, db_path)

    monkeypatch.setattr(
        "chrono_core.mcp_server.read_git_state",
        lambda _: _GitState(branch="feat/novel"),
    )

    result = handle_get_resume_context(
        str(project),
        workspace_root=str(workspace),
        db_path=str(db_path),
        include_all=True,
    )

    assert sorted(a["text"] for a in result["next_actions"]) == [
        "novel action",
        "platform action",
    ]
    assert result["hidden_actions"] == 0


def test_handle_get_resume_context_explicit_branch(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db_path = tmp_path / "chrono.db"
    project = _seed_two_branch_project(workspace, db_path)

    monkeypatch.setattr(
        "chrono_core.mcp_server.read_git_state",
        lambda _: pytest.fail("read_git_state must not run when branch is explicit"),
    )

    result = handle_get_resume_context(
        str(project),
        workspace_root=str(workspace),
        db_path=str(db_path),
        branch="feat/platform",
    )

    assert [a["text"] for a in result["next_actions"]] == ["platform action"]


def test_get_resume_context_tool_passes_scoping_params(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}

    def fake_handler(cwd, *, branch=None, include_all=False, limit=20, **kwargs):
        captured.update(branch=branch, include_all=include_all, limit=limit)
        return {"project_name": "example"}

    monkeypatch.setattr("chrono_core.mcp_server.handle_get_resume_context", fake_handler)

    get_resume_context_tool(
        str(tmp_path),
        branch="feat/x",
        include_all=False,
        limit=5,
    )

    assert captured == {"branch": "feat/x", "include_all": False, "limit": 5}


def test_handle_get_resume_context_for_unknown_project(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    db_path = tmp_path / "chrono.db"

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
    db_path = tmp_path / "chrono.db"

    result = get_resume_context_tool(
        str(project),
        workspace_root=str(workspace),
        db_path=str(db_path),
        max_tokens=4096,
    )

    assert result["project_name"] == "unknown"
    assert result["truncated"] is False


def test_handle_record_decision_persists_sessionless_decision(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    db_path = tmp_path / "chrono.db"

    result = handle_record_decision(
        str(project),
        "Adopt sessionless management notes",
        rationale="Management sessions need to record state without a handoff.",
        workspace_root=str(workspace),
        db_path=str(db_path),
    )

    assert result["ok"] is True
    assert result["recorded_count"] == 1
    assert result["decision"]["title"] == "Adopt sessionless management notes"

    store = Store(str(db_path))
    context = store.get_resume_context(result["project_id"])
    assert context.project_name == "example"
    assert context.recent_decisions[0]["title"] == "Adopt sessionless management notes"


def test_handle_record_blocker_persists_sessionless_blocker(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    db_path = tmp_path / "chrono.db"

    result = handle_record_blocker(
        str(project),
        "Need live credentials",
        detail="Smoke test cannot run until credentials exist.",
        status="open",
        workspace_root=str(workspace),
        db_path=str(db_path),
    )

    assert result["ok"] is True
    assert result["recorded_count"] == 1
    assert result["blocker"]["title"] == "Need live credentials"

    store = Store(str(db_path))
    context = store.get_resume_context(result["project_id"])
    assert context.project_name == "example"
    assert context.active_blockers[0]["title"] == "Need live credentials"


def test_record_decision_and_blocker_tools_wrap_handlers(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    db_path = tmp_path / "chrono.db"

    decision = record_decision_tool(
        str(project),
        "Use narrow MCP tools",
        workspace_root=str(workspace),
        db_path=str(db_path),
    )
    blocker = record_blocker_tool(
        str(project),
        "Await operator review",
        workspace_root=str(workspace),
        db_path=str(db_path),
    )

    assert decision["ok"] is True
    assert decision["decision"]["title"] == "Use narrow MCP tools"
    assert blocker["ok"] is True
    assert blocker["blocker"]["status"] == "open"


def test_mcp_server_falls_back_to_cwd_without_env(monkeypatch, tmp_path):
    from chrono_core.config import default_workspace_root

    monkeypatch.delenv("CHRONO_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("CONTINUITY_WORKSPACE_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    assert Path(default_workspace_root()) == tmp_path


def test_cancel_action_via_handle(monkeypatch, tmp_path):
    from chrono_core import services
    from chrono_core.mcp_server import handle_cancel_action

    db = str(tmp_path / "m.db")
    store = services.open_store(db)
    pid = store.upsert_project(project_id="p", name="p", path="/tmp/p", relative_path="p")
    store.record_next_actions(pid, None, ["x"])
    aid = store._connect().execute("SELECT id FROM next_actions").fetchone()["id"]

    result = handle_cancel_action(aid, db_path=db)
    assert result["ok"] is True and result["status"] == "cancelled"


def test_registered_tools_include_lifecycle():
    from chrono_core.mcp_server import mcp

    registered = asyncio.run(mcp.list_tools())
    names = {t.name for t in registered}
    assert {
        "chrono_core_cancel_action",
        "chrono_core_edit_action",
        "chrono_core_reopen_action",
        "chrono_core_supersede_action",
        "chrono_core_cancel_blocker",
        "chrono_core_edit_blocker",
        "chrono_core_reopen_blocker",
    } <= names


def test_registered_tools_include_bugs():
    from chrono_core.mcp_server import mcp

    registered = asyncio.run(mcp.list_tools())
    names = {t.name for t in registered}
    assert {
        "chrono_core_report_bug",
        "chrono_core_list_bugs",
        "chrono_core_update_bug",
    } <= names


def test_report_bug_tool_round_trip(tmp_path: Path):
    from chrono_core.mcp_server import (
        list_bugs_tool,
        report_bug_tool,
        update_bug_tool,
    )

    workspace = tmp_path / "workspace"
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    db = str(tmp_path / "chrono.db")

    reported = report_bug_tool(
        str(project),
        "Resume shows stale actions",
        severity="high",
        detail="Flat query leaks other workstreams.",
        workspace_root=str(workspace),
        db_path=db,
    )
    assert reported["ok"] is True
    assert reported["bug"]["severity"] == "high"
    bug_id = reported["bug_id"]

    open_list = list_bugs_tool(db_path=db)
    assert open_list["count"] == 1
    assert open_list["bugs"][0]["id"] == bug_id

    updated = update_bug_tool(bug_id, status="confirmed", db_path=db)
    assert updated["ok"] is True and updated["bug"]["status"] == "confirmed"

    closed = list_bugs_tool(status="open", db_path=db)
    assert closed["count"] == 0
    confirmed = list_bugs_tool(status="confirmed", db_path=db)
    assert confirmed["count"] == 1


def test_report_bug_tool_workspace_wide(tmp_path: Path):
    from chrono_core.mcp_server import report_bug_tool

    db = str(tmp_path / "ws.db")

    result = report_bug_tool(
        str(tmp_path),
        "Workspace-wide defect",
        workspace=True,
        db_path=db,
    )
    assert result["ok"] is True
    assert result["project_id"] is None


def test_update_bug_tool_rejects_unknown_bug(tmp_path: Path):
    from chrono_core.mcp_server import update_bug_tool

    db = str(tmp_path / "none.db")
    result = update_bug_tool("nope", status="fixed", db_path=db)
    assert result["ok"] is False
