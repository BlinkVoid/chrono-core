from __future__ import annotations

import json
from pathlib import Path

from chrono_core.cli import main
from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.export.markdown import export_markdown
from chrono_core.management.review import review_project
from chrono_core.mcp_server import handle_review_project, review_project_tool
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


def _seed_review_project(store: Store, workspace: Path) -> Path:
    project_path = workspace / "example"
    docs = project_path / "docs"
    docs.mkdir(parents=True)
    (project_path / ".git").mkdir()
    (project_path / "README.md").write_text(
        "# Example\n\nCurrent status: Phase 3 management workflows are complete.\n",
        encoding="utf-8",
    )
    (docs / "CONTEXT.md").write_text(
        "# Context\n\n## Current Phase\n\nPhase 2 MCP tool layer is implemented.\n",
        encoding="utf-8",
    )
    (docs / "ROADMAP.md").write_text(
        "# Roadmap\n\n"
        "## Phase 2\n\n- [x] Agent interface.\n\n"
        "## Phase 3\n\n- [x] Management review.\n\n"
        "## Phase 4\n\n- [ ] Cross-project intelligence.\n",
        encoding="utf-8",
    )

    project = resolve_project(project_path, workspace_root=workspace)
    store.init_schema()
    store.get_or_create_project(project)
    payload = HandoffPayload(
        summary="Finished Phase 3 review outputs.",
        blockers=[{"title": "Need external smoke credentials", "status": "open"}],
        next_actions=["Start Phase 4 pattern index"],
        decisions=[{"title": "Use deterministic review", "rationale": "Keep it local"}],
    )
    session_id = store.create_session(project.project_id, payload, GitState(branch="main"))
    store.record_blockers(project.project_id, session_id, payload.blockers)
    store.record_next_actions(project.project_id, session_id, payload.next_actions)
    store.record_decisions(project.project_id, session_id, payload.decisions)
    return project_path


def test_review_project_detects_doc_drift_and_builds_health_queue(tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    project_path = _seed_review_project(Store(db_path), workspace)

    result = review_project(
        cwd=project_path,
        workspace_root=workspace,
        store=Store(db_path),
    )

    assert result["ok"] is True
    assert result["canonical_phase"] == "Phase 4"
    assert result["health"]["status"] == "blocked"
    assert result["health"]["open_blockers"] == 1
    assert result["health"]["open_actions"] == 1
    assert any(f["kind"] == "stale_doc" for f in result["findings"])
    assert any(f["kind"] == "contradictory_doc" for f in result["findings"])
    assert any("docs/CONTEXT.md" in item["target"] for item in result["review_queue"])
    assert any("Resolve" in item["advice"] for item in result["improvement_advice"])


def test_review_health_applies_bug_pressure_penalty(tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    store = Store(db_path)
    project_path = _seed_review_project(store, workspace)
    project = resolve_project(project_path, workspace_root=workspace)
    project_id = store.get_or_create_project(project)
    for index in range(4):
        store.report_bug(project_id, f"critical flaw {index}", severity="critical")

    result = review_project(
        cwd=project_path,
        workspace_root=workspace,
        store=Store(db_path),
    )

    assert result["health"]["score"] == 85
    assert result["health"]["open_high_severity_bugs"] == 4
    assert any(
        "open high-severity bug(s) need triage" in item["advice"]
        for item in result["improvement_advice"]
    )


def test_review_parser_defaults():
    from chrono_core.cli import build_parser

    args = build_parser().parse_args(["review"])

    assert args.command == "review"
    assert args.cwd == "."
    assert args.db_path is None


def test_review_main_emits_json(tmp_path: Path, capsys):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    project_path = _seed_review_project(Store(db_path), workspace)

    code = main(
        [
            "review",
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
    assert data["canonical_phase"] == "Phase 4"


def test_mcp_review_project_wraps_handler(tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    project_path = _seed_review_project(Store(db_path), workspace)

    handler_result = handle_review_project(
        str(project_path),
        workspace_root=str(workspace),
        db_path=str(db_path),
    )
    tool_result = review_project_tool(
        str(project_path),
        workspace_root=str(workspace),
        db_path=str(db_path),
    )

    assert handler_result["health"]["status"] == "blocked"
    assert tool_result["canonical_phase"] == "Phase 4"


def test_export_markdown_includes_review_queue(tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    _seed_review_project(Store(db_path), workspace)

    result = export_markdown(Store(db_path), tmp_path / "export")

    review_queue = Path(result["review_queue_path"])
    text = review_queue.read_text(encoding="utf-8")
    assert "# Review Queue" in text
    assert "docs/CONTEXT.md" in text
    assert "Need external smoke credentials" in text


def test_export_markdown_handles_nested_projects(tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    project_path = workspace / "projects" / "example"
    project_path.mkdir(parents=True)
    (project_path / ".git").mkdir()
    (project_path / "README.md").write_text("# Nested\n", encoding="utf-8")

    store = Store(db_path)
    store.init_schema()
    project = resolve_project(project_path, workspace_root=workspace)
    store.get_or_create_project(project)

    result = export_markdown(Store(db_path), tmp_path / "export")

    assert result["ok"] is True
    assert result["exported_count"] == 1
    assert len(Store(db_path).list_projects()) == 1


def test_review_ignores_older_unfinished_backlog_when_later_phases_are_complete(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project_path = workspace / "example"
    docs = project_path / "docs"
    docs.mkdir(parents=True)
    (project_path / ".git").mkdir()
    (project_path / "README.md").write_text(
        "# Example\n\n## Current Status\n\n"
        "Phase 1 and Phase 2 are complete. Phase 3 is complete. Phase 4 is next.\n",
        encoding="utf-8",
    )
    (docs / "ROADMAP.md").write_text(
        "# Roadmap\n\n"
        "## Phase 0\n\n- [x] Design.\n- [ ] Old optional backlog.\n\n"
        "## Phase 1\n\n- [x] Local core.\n\n"
        "## Phase 2\n\n- [x] Agent interface.\n\n"
        "## Phase 3\n\n- [x] Management review.\n\n"
        "## Phase 4\n\n- [ ] Cross-project intelligence.\n",
        encoding="utf-8",
    )

    result = review_project(
        cwd=project_path,
        workspace_root=workspace,
        store=Store(tmp_path / "db.sqlite"),
    )

    assert result["canonical_phase"] == "Phase 4"
    assert result["findings"] == []
