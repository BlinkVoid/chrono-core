from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from chrono_core.cli import DEFAULT_WORKSPACE_INTELLIGENCE_REGISTRY, build_parser
from chrono_core.integrations.workspace_intelligence import (
    import_project_tracking,
    import_workspace_intelligence,
)
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import make_project_id


def test_ingest_existing_tools_defaults_to_state_registry():
    expected = str(
        Path.home() / ".local" / "state" / "workspace-intelligence" / "registry.db"
    )

    args = build_parser().parse_args(["ingest-existing-tools"])

    assert DEFAULT_WORKSPACE_INTELLIGENCE_REGISTRY == expected
    assert args.registry_path == expected


def _create_workspace_intelligence_db(path: Path, workspace: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    project = workspace / "tool-project-tracker"
    project.mkdir(parents=True)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            relative_path TEXT NOT NULL,
            discovered_at TEXT NOT NULL,
            last_refreshed_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            missing_since TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            priority TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            owner TEXT,
            description_usage TEXT,
            summary TEXT,
            current_progress TEXT,
            notes TEXT,
            lifecycle_phase TEXT NOT NULL DEFAULT 'prototype',
            other_factors TEXT NOT NULL DEFAULT '{}',
            last_error TEXT
        );
        CREATE TABLE git_state (
            project_id TEXT PRIMARY KEY,
            branch TEXT,
            detached INTEGER NOT NULL DEFAULT 0,
            head_sha TEXT,
            head_subject TEXT,
            remote_name TEXT,
            remote_url TEXT,
            default_branch TEXT,
            dirty INTEGER NOT NULL DEFAULT 0,
            changed_count INTEGER NOT NULL DEFAULT 0,
            untracked_count INTEGER NOT NULL DEFAULT 0,
            collected_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT INTO projects (
            project_id, name, path, relative_path, discovered_at, last_refreshed_at,
            last_seen_at, status, priority, tags, owner, description_usage, summary,
            current_progress, notes, lifecycle_phase, other_factors
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "workspace-intelligence-id",
            "workspace-intelligence",
            str(project),
            "tool-project-tracker",
            "2026-06-18T00:00:00+00:00",
            "2026-06-19T00:00:00+00:00",
            "2026-06-19T00:00:00+00:00",
            "active",
            "high",
            json.dumps(["management", "tracking"]),
            "operator",
            "Discovers workspace projects.",
            "Workspace Intelligence",
            "SQLite registry and MCP server are working.",
            "Canonical successor to project-tracking.",
            "validation",
            json.dumps({"source": "tool-project-tracker"}),
        ),
    )
    conn.execute(
        """
        INSERT INTO git_state (
            project_id, branch, head_sha, dirty, changed_count, untracked_count, collected_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("workspace-intelligence-id", "main", "abc123", 1, 2, 1, "2026-06-19T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()


def test_import_project_tracking_uses_archived_source_when_original_moved(tmp_path: Path):
    workspace = tmp_path / "workspace"
    archived_tracking = workspace / "_archive_projects" / "project-tracking-2026-07-02"
    archived_tracking.mkdir(parents=True)
    (archived_tracking / "README.md").write_text("# Project Tracking\n\nArchived source.")
    store = Store(tmp_path / "chrono.db")

    result = import_project_tracking(store, workspace_root=workspace)

    assert result.ok is True
    assert result.registry_path == str(archived_tracking)
    assert result.projects[0].project_id == make_project_id("project-tracking")
    assert result.projects[0].relative_path == "_archive_projects/project-tracking-2026-07-02"


def test_import_workspace_intelligence_registry_into_continuity_store(tmp_path: Path):
    workspace = tmp_path / "workspace"
    registry = tmp_path / "workspace-intelligence" / "registry.db"
    _create_workspace_intelligence_db(registry, workspace)
    store = Store(tmp_path / "chrono.db")

    result = import_workspace_intelligence(
        store,
        registry_path=registry,
        workspace_root=workspace,
    )

    continuity_project_id = make_project_id("tool-project-tracker")
    assert result.to_dict() == {
        "ok": True,
        "source": "workspace-intelligence",
        "registry_path": str(registry),
        "workspace_root": str(workspace),
        "imported_count": 1,
        "skipped_count": 0,
        "projects": [
            {
                "project_id": continuity_project_id,
                "source_project_id": "workspace-intelligence-id",
                "name": "workspace-intelligence",
                "relative_path": "tool-project-tracker",
            }
        ],
        "skipped": [],
    }

    context = store.get_resume_context(continuity_project_id)
    assert context.project_name == "workspace-intelligence"
    assert context.current_status == "No sessions captured yet."

    conn = store._connect()
    project = conn.execute(
        "SELECT id, phase, summary FROM projects WHERE id = ?",
        (continuity_project_id,),
    ).fetchone()
    assert project["phase"] == "validation"
    assert project["summary"] == "SQLite registry and MCP server are working."

    observations = conn.execute(
        "SELECT kind, content, source FROM observations WHERE project_id = ? ORDER BY kind",
        (continuity_project_id,),
    ).fetchall()
    assert {row["kind"] for row in observations} >= {
        "workspace_intelligence_metadata",
        "workspace_intelligence_git",
    }
    assert all(row["source"] == "workspace-intelligence" for row in observations)


def test_import_workspace_intelligence_missing_registry_is_structured_skip(tmp_path: Path):
    store = Store(tmp_path / "chrono.db")

    result = import_workspace_intelligence(
        store,
        registry_path=tmp_path / "missing.db",
        workspace_root=tmp_path / "workspace",
    )

    assert result.ok is False
    assert result.imported_count == 0
    assert result.skipped[0]["reason"] == "registry_not_found"
