from __future__ import annotations

from chrono_core.capture.handoff import persist_handoff
from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


def test_canonical_handoff_persists_resume_context(tmp_path):
    workspace = tmp_path / "workspace"
    project_path = workspace / "example"
    project_path.mkdir(parents=True)
    (project_path / "hive.project.json").write_text("{}", encoding="utf-8")
    project = resolve_project(project_path, workspace_root=workspace)
    store = Store(tmp_path / "chrono.db")

    result = persist_handoff(
        store,
        project,
        HandoffPayload(
            summary="implemented persistence",
            decisions=[{"title": "Use Store", "rationale": "Single persistence path"}],
            blockers=[{"title": "MCP server pending", "status": "open"}],
            next_actions=["Add MCP server"],
            tests=["uv run pytest -q: passed"],
            files_changed=["src/chrono_core/store/store.py"],
            risks=["No migration runner yet"],
        ),
        GitState(branch="main"),
        agent_name="codex",
    )

    assert result["ok"] is True
    context = store.get_resume_context(project.project_id)
    assert context.summary == "implemented persistence"
    assert context.active_blockers[0]["title"] == "MCP server pending"
    assert context.next_actions[0]["text"] == "Add MCP server"
    assert context.recent_decisions[0]["title"] == "Use Store"
