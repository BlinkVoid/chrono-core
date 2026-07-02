from __future__ import annotations

from pathlib import Path

from continuity_core.store.store import Store
from continuity_core.workspace.discovery import DiscoveryOptions, discover_workspace
from continuity_core.workspace.resolver import make_project_id


def test_discover_workspace_finds_marker_projects_and_skips_generated_dirs(tmp_path: Path):
    workspace = tmp_path / "workspace"
    app = workspace / "app"
    package = workspace / "packages" / "worker"
    ignored = workspace / "node_modules" / "dep"
    app.mkdir(parents=True)
    package.mkdir(parents=True)
    ignored.mkdir(parents=True)
    (app / "pyproject.toml").write_text("[project]\nname = 'app'\n", encoding="utf-8")
    (package / "package.json").write_text("{}", encoding="utf-8")
    (ignored / "package.json").write_text("{}", encoding="utf-8")

    result = discover_workspace(
        workspace_root=workspace,
        options=DiscoveryOptions(max_depth=3),
    )

    assert result.ok is True
    assert result.discovered_count == 2
    assert [project.relative_path for project in result.projects] == ["app", "packages/worker"]
    assert [project.marker for project in result.projects] == ["pyproject.toml", "package.json"]


def test_discover_workspace_persists_projects(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project_path = workspace / "continuity-core"
    project_path.mkdir(parents=True)
    (project_path / "hive.project.json").write_text("{}", encoding="utf-8")
    store = Store(tmp_path / "continuity.db")

    result = discover_workspace(workspace_root=workspace, store=store)

    project_id = make_project_id("continuity-core")
    assert result.persisted_count == 1
    context = store.get_resume_context(project_id)
    assert context.project_name == "continuity-core"
    assert context.current_status == "No sessions captured yet."


def test_discover_workspace_reports_missing_root(tmp_path: Path):
    result = discover_workspace(workspace_root=tmp_path / "missing")

    assert result.ok is False
    assert result.discovered_count == 0
    assert result.skipped == [
        {"reason": "workspace_root_not_found", "path": str((tmp_path / "missing").resolve())}
    ]
