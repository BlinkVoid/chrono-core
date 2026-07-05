from __future__ import annotations

from pathlib import Path

from continuity_core.workspace.resolver import make_project_id, resolve_project


def test_resolve_project_from_nested_git_marker(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "example"
    nested = project / "src" / "pkg"
    nested.mkdir(parents=True)
    (project / ".git").mkdir()

    resolved = resolve_project(nested, workspace_root=workspace)

    assert resolved.name == "example"
    assert resolved.path == str(project.resolve())
    assert resolved.relative_path == "example"
    assert resolved.marker == ".git"
    assert resolved.project_id == make_project_id("example")


def test_resolve_project_uses_provisional_when_no_marker(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "loose"
    project.mkdir(parents=True)

    resolved = resolve_project(project, workspace_root=workspace)

    assert resolved.name == "loose"
    assert resolved.marker == "provisional"
    assert resolved.project_id


def test_resolve_project_rejects_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()

    try:
        resolve_project(outside, workspace_root=workspace)
    except ValueError as exc:
        assert "outside workspace root" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_readme_only_subdir_does_not_shadow_repo_root(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "example"
    docs = project / "docs"
    docs.mkdir(parents=True)
    (project / ".git").mkdir()
    (docs / "README.md").write_text("subdir docs")

    resolved = resolve_project(docs, workspace_root=workspace)

    assert resolved.path == str(project.resolve())
    assert resolved.marker == ".git"


def test_readme_only_project_still_resolves(tmp_path: Path):
    workspace = tmp_path / "workspace"
    notes = workspace / "notes"
    notes.mkdir(parents=True)
    (notes / "README.md").write_text("standalone notes project")

    resolved = resolve_project(notes, workspace_root=workspace)

    assert resolved.path == str(notes.resolve())
    assert resolved.marker == "README.md"
