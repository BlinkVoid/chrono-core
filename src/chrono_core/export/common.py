"""Shared helpers for the export subcommands."""
from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any

from chrono_core.store.store import Store
from chrono_core.workspace.resolver import ResolvedProject, resolve_project


def load_project_row(store: Store, project_id: str) -> Any:
    """Return the projects row for *project_id*, or None."""
    return store._connect().execute(
        "SELECT id, name, path FROM projects WHERE id = ?", (project_id,)
    ).fetchone()


def resolve_export_project(store: Store, args: Namespace) -> tuple[str, ResolvedProject | None]:
    """Resolve the export target from CLI args.

    Returns ``(project_id, fallback_project)``. The fallback supplies
    name/path metadata when a ``--cwd`` project was never registered;
    explicit unknown ``--project-id`` values get no fallback.
    """
    if getattr(args, "project_id", None):
        return args.project_id, None
    try:
        project = resolve_project(
            Path(args.cwd),
            workspace_root=Path(getattr(args, "workspace_root", ".") or "."),
        )
    except ValueError as exc:
        raise ValueError(str(exc)) from None
    return store.resolve_project_id(project), project
