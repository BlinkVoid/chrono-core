from __future__ import annotations

from pathlib import Path

import pytest

from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.export.markdown import export_markdown
from chrono_core.store import migrations
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


def test_export_markdown_writes_project_index_and_project_page(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project_path = workspace / "example"
    project_path.mkdir(parents=True)
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    project = resolve_project(project_path, workspace_root=workspace)
    store.get_or_create_project(project)
    store.upsert_project_inventory(
        project_id=project.project_id,
        workspace_root=str(workspace),
        marker="pyproject.toml",
        depth=1,
        collected={
            "is_git": True,
            "branch": "feature",
            "detached": False,
            "head_sha": "abc123",
            "head_subject": "latest",
            "remote_name": None,
            "remote_url": None,
            "default_branch": "main",
            "dirty": True,
            "changed_count": 2,
            "untracked_count": 1,
            "error": None,
        },
    )
    payload = HandoffPayload(
        summary="Latest session.",
        next_actions=["Ship export"],
        decisions=[{"title": "Use Markdown", "rationale": "Readable"}],
        blockers=[{"title": "Need review", "status": "open"}],
    )
    session_id = store.create_session(project.project_id, payload, GitState(branch="main"))
    store.record_next_actions(project.project_id, session_id, payload.next_actions)
    store.record_decisions(project.project_id, session_id, payload.decisions)
    store.record_blockers(project.project_id, session_id, payload.blockers)

    result = export_markdown(store, tmp_path / "export")

    assert result["ok"] is True
    assert result["exported_count"] == 1
    index = (tmp_path / "export" / "Projects.md").read_text(encoding="utf-8")
    assert "# Projects" in index
    assert "- [example](projects/example-" in index

    project_page = Path(result["projects"][0]["path"])
    text = project_page.read_text(encoding="utf-8")
    assert "# example" in text
    assert "Latest session." in text
    assert "Ship export" in text
    assert "Use Markdown" in text
    assert "Need review" in text
    assert "## Live Inventory" in text
    assert "Branch: feature" in text
    assert "Dirty: true" in text
    assert "branch: feature" in index


def test_project_page_renders_catalog_metadata_without_observations(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project_path = workspace / "example"
    project_path.mkdir(parents=True)
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    project = resolve_project(project_path, workspace_root=workspace)
    project_id = store.get_or_create_project(project)
    payload = HandoffPayload(summary="Latest session summary.")
    store.create_session(project.project_id, payload, GitState(branch="main"))
    store.record_observation(
        project_id, None, "lesson", "sensitive observation detail", source="direct"
    )
    store.update_project_metadata(
        project_id,
        {
            "status": "paused",
            "lifecycle_phase": "maintenance",
            "priority": "high",
            "tags": ["infra", "cli"],
            "owner": "r345",
            "description_usage": "internal tooling",
            "notes": "mind the schema",
        },
    )
    store.update_project_progress(project_id, "catalog render wired")

    result = export_markdown(store, tmp_path / "export")

    page = Path(result["projects"][0]["path"]).read_text(encoding="utf-8")
    assert "Latest session summary." in page
    assert "Status: paused" in page
    assert "Lifecycle phase: maintenance" in page
    assert "Priority: high" in page
    assert "Tags: infra, cli" in page
    assert "Owner: r345" in page
    assert "Description/Usage: internal tooling" in page
    assert "Current progress: catalog render wired" in page
    assert "Notes: mind the schema" in page
    assert "sensitive observation detail" not in page


def test_export_markdown_initializes_schema_once_for_multi_project_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace = tmp_path / "workspace"
    seed_store = Store(tmp_path / "chrono.db")
    seed_store.init_schema()
    for name in ("alpha", "beta", "gamma"):
        project_path = workspace / name
        project_path.mkdir(parents=True)
        (project_path / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        project = resolve_project(project_path, workspace_root=workspace)
        seed_store.get_or_create_project(project)
    seed_store.close()

    init_calls: list[int] = []
    real_apply_pending = migrations.apply_pending

    def counting_apply_pending(conn):
        init_calls.append(1)
        return real_apply_pending(conn)

    monkeypatch.setattr(migrations, "apply_pending", counting_apply_pending)

    result = export_markdown(Store(tmp_path / "chrono.db"), tmp_path / "export")

    assert result["ok"] is True
    assert result["exported_count"] == 3
    assert (tmp_path / "export" / "Projects.md").exists()
    assert (tmp_path / "export" / "ReviewQueue.md").exists()
    assert len(list((tmp_path / "export" / "projects").glob("*.md"))) == 3
    assert len(init_calls) == 1


def test_export_markdown_keeps_registered_symlink_identity_and_renders_review(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    target_path = workspace / "HIVE" / "honeycomb" / "miniature-scenes"
    docs_path = target_path / "docs"
    docs_path.mkdir(parents=True)
    (target_path / "README.md").write_text("# Miniature scenes\n", encoding="utf-8")
    (docs_path / "ROADMAP.md").write_text(
        "# Roadmap\n\n## Phase 2\n\n- [ ] Publish scenes.\n",
        encoding="utf-8",
    )
    stored_path = workspace / "miniature-scenes"
    stored_path.symlink_to(target_path, target_is_directory=True)

    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    project_id = "miniature-scenes-source"
    store.upsert_project(
        project_id=project_id,
        name="Stored miniature scenes",
        path=str(stored_path),
        relative_path="miniature-scenes",
    )
    payload = HandoffPayload(summary="Keep the registered path.", next_actions=["Review"])
    session_id = store.create_session(project_id, payload, GitState(branch="main"))
    store.record_next_actions(project_id, session_id, payload.next_actions)
    before = store.list_projects()

    result = export_markdown(store, tmp_path / "export")

    assert result["exported_count"] == 1
    assert store.list_projects() == before
    assert store.get_project(str(target_path)) is None
    page = Path(result["projects"][0]["path"]).read_text(encoding="utf-8")
    assert "## Health Review" in page
    assert "## Review Queue" in page


def test_export_markdown_does_not_rewrite_existing_catalog_state(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project_path = workspace / "archived-evidence"
    project_path.mkdir(parents=True)
    (project_path / "README.md").write_text("# Archived evidence\n", encoding="utf-8")
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    project = resolve_project(project_path, workspace_root=workspace)
    project_id = store.get_or_create_project(project)
    store.update_project_metadata(
        project_id,
        {
            "status": "paused",
            "summary": "Deliberately preserved catalog summary.",
            "lifecycle_phase": "archived",
        },
    )
    store.update_project_state(
        project_id,
        phase="historical-evidence",
        summary="Deliberately preserved catalog summary.",
    )
    before = store.get_project(project_id)

    export_markdown(store, tmp_path / "export")

    assert store.get_project(project_id) == before
