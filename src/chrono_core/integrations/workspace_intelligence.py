from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chrono_core.store.store import Store
from chrono_core.workspace.resolver import make_project_id


@dataclass
class ImportedProject:
    project_id: str
    source_project_id: str
    name: str
    relative_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "source_project_id": self.source_project_id,
            "name": self.name,
            "relative_path": self.relative_path,
        }


@dataclass
class ImportResult:
    ok: bool
    source: str
    registry_path: str
    workspace_root: str
    imported_count: int = 0
    skipped_count: int = 0
    projects: list[ImportedProject] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "source": self.source,
            "registry_path": self.registry_path,
            "workspace_root": self.workspace_root,
            "imported_count": self.imported_count,
            "skipped_count": self.skipped_count,
            "projects": [p.to_dict() for p in self.projects],
            "skipped": list(self.skipped),
        }


def import_workspace_intelligence(
    store: Store,
    *,
    registry_path: str | Path,
    workspace_root: str | Path,
) -> ImportResult:
    """Import projects from the Workspace Intelligence SQLite registry into Chrono Core."""
    registry = Path(registry_path)
    workspace = Path(workspace_root)
    result = ImportResult(
        ok=True,
        source="workspace-intelligence",
        registry_path=str(registry),
        workspace_root=str(workspace),
    )

    if not registry.exists():
        result.ok = False
        result.skipped_count = 1
        result.skipped.append({"reason": "registry_not_found", "path": str(registry)})
        return result

    store.init_schema()

    conn = sqlite3.connect(str(registry))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            p.project_id AS source_project_id,
            p.name,
            p.path,
            p.relative_path,
            p.status,
            p.priority,
            p.tags,
            p.owner,
            p.description_usage,
            p.summary,
            p.current_progress,
            p.notes,
            p.lifecycle_phase,
            p.other_factors,
            p.last_error,
            g.branch,
            g.head_sha,
            g.dirty,
            g.changed_count,
            g.untracked_count
        FROM projects p
        LEFT JOIN git_state g ON g.project_id = p.project_id
        """
    ).fetchall()

    for row in rows:
        relative_path = row["relative_path"]
        project_id = make_project_id(relative_path)
        project_path = str(workspace / relative_path)

        store.upsert_project(
            project_id=project_id,
            name=row["name"],
            path=project_path,
            relative_path=relative_path,
            phase=row["lifecycle_phase"] or None,
            summary=row["current_progress"] or row["summary"] or None,
        )

        metadata_items: list[str] = []
        git_items: list[str] = []

        if row["description_usage"]:
            metadata_items.append(f"Usage: {row['description_usage']}")
        if row["current_progress"]:
            metadata_items.append(f"Progress: {row['current_progress']}")
        if row["notes"]:
            metadata_items.append(f"Notes: {row['notes']}")
        if row["priority"]:
            metadata_items.append(f"Priority: {row['priority']}")
        if row["tags"]:
            try:
                tags = json.loads(row["tags"])
                if tags:
                    metadata_items.append(f"Tags: {', '.join(str(t) for t in tags)}")
            except json.JSONDecodeError:
                metadata_items.append(f"Tags: {row['tags']}")
        if row["status"]:
            metadata_items.append(f"Status: {row['status']}")
        if row["owner"]:
            metadata_items.append(f"Owner: {row['owner']}")
        if row["other_factors"]:
            try:
                factors = json.loads(row["other_factors"])
                if factors:
                    metadata_items.append(f"Other factors: {json.dumps(factors)}")
            except json.JSONDecodeError:
                metadata_items.append(f"Other factors: {row['other_factors']}")
        if row["last_error"]:
            metadata_items.append(f"Last error: {row['last_error']}")

        if row["branch"]:
            git_items.append(f"Branch: {row['branch']}")
        if row["head_sha"]:
            git_items.append(f"HEAD: {row['head_sha']}")
        if row["dirty"] is not None:
            git_items.append(f"Dirty: {bool(row['dirty'])}")
        if row["changed_count"] is not None:
            git_items.append(f"Changed files: {row['changed_count']}")
        if row["untracked_count"] is not None:
            git_items.append(f"Untracked files: {row['untracked_count']}")

        store.record_observations(
            project_id=project_id,
            session_id=None,
            kind="workspace_intelligence_metadata",
            items=metadata_items,
            source="workspace-intelligence",
        )
        store.record_observations(
            project_id=project_id,
            session_id=None,
            kind="workspace_intelligence_git",
            items=git_items,
            source="workspace-intelligence",
        )

        result.projects.append(
            ImportedProject(
                project_id=project_id,
                source_project_id=row["source_project_id"],
                name=row["name"],
                relative_path=relative_path,
            )
        )
        result.imported_count += 1

    conn.close()
    return result


def _find_project_tracking_source(workspace: Path) -> tuple[Path, str]:
    live_source = workspace / "project-tracking"
    if live_source.exists():
        return live_source, "project-tracking"

    archive_root = workspace / "_archive_projects"
    if archive_root.exists():
        archived_sources = sorted(
            (
                child
                for child in archive_root.iterdir()
                if child.is_dir() and child.name.startswith("project-tracking")
            ),
            key=lambda child: child.name,
            reverse=True,
        )
        if archived_sources:
            archived_source = archived_sources[0]
            return archived_source, str(archived_source.relative_to(workspace))

    return live_source, "project-tracking"


def import_project_tracking(
    store: Store,
    *,
    workspace_root: str | Path,
) -> ImportResult:
    """Import the legacy project-tracking directory as archived source evidence."""
    workspace = Path(workspace_root)
    tracking_dir, relative_path = _find_project_tracking_source(workspace)
    project_id = make_project_id("project-tracking")
    result = ImportResult(
        ok=True,
        source="project-tracking",
        registry_path=str(tracking_dir),
        workspace_root=str(workspace),
    )

    if not tracking_dir.exists():
        result.ok = False
        result.skipped_count = 1
        result.skipped.append({"reason": "directory_not_found", "path": str(tracking_dir)})
        return result

    store.init_schema()

    readme = tracking_dir / "README.md"
    readme_text = readme.read_text(encoding="utf-8") if readme.exists() else ""

    store.upsert_project(
        project_id=project_id,
        name="project-tracking",
        path=str(tracking_dir),
        relative_path=relative_path,
        phase="archived",
        summary="Legacy project-tracking placeholder, superseded by workspace-intelligence.",
    )

    evidence_items: list[str] = []
    if readme_text:
        evidence_items.append(f"README:\n{readme_text}")
    else:
        evidence_items.append("README missing.")
    evidence_items.append(
        "Status: archived / superseded by tool-project-tracker (workspace-intelligence)."
    )

    for child in sorted(tracking_dir.iterdir()):
        if child.is_file() and child.name != "README.md":
            evidence_items.append(f"File: {child.name}")

    store.record_observations(
        project_id=project_id,
        session_id=None,
        kind="archived_source_evidence",
        items=evidence_items,
        source="project-tracking",
    )

    result.projects.append(
        ImportedProject(
            project_id=project_id,
            source_project_id="project-tracking",
            name="project-tracking",
            relative_path=relative_path,
        )
    )
    result.imported_count = 1
    return result


def ingest_existing_tools(
    store: Store,
    *,
    registry_path: str | Path,
    workspace_root: str | Path,
) -> dict[str, Any]:
    """Import workspace-intelligence registry and legacy project-tracking evidence."""
    wi_result = import_workspace_intelligence(
        store,
        registry_path=registry_path,
        workspace_root=workspace_root,
    )
    pt_result = import_project_tracking(
        store,
        workspace_root=workspace_root,
    )
    return {
        "ok": wi_result.ok and pt_result.ok,
        "workspace_root": str(workspace_root),
        "registry_path": str(registry_path),
        "sources": {
            "workspace-intelligence": wi_result.to_dict(),
            "project-tracking": pt_result.to_dict(),
        },
        "imported_count": wi_result.imported_count + pt_result.imported_count,
        "skipped_count": wi_result.skipped_count + pt_result.skipped_count,
    }
