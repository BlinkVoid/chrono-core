from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from continuity_core.config import default_db_path
from continuity_core.domain.models import ResumeContext
from continuity_core.store.store import Store
from continuity_core.workspace.resolver import resolve_project


def _default_db_path() -> str:
    return default_db_path()


def get_resume_context(args: Namespace) -> ResumeContext:
    """Resolve project and return resume context from the store."""
    project_path = Path(getattr(args, "cwd", "."))
    workspace_root = Path(getattr(args, "workspace_root", "~/workspace"))
    project = resolve_project(project_path, workspace_root=workspace_root)

    db_path = getattr(args, "db_path", None) or _default_db_path()
    store = Store(db_path)
    store.init_schema()
    return store.get_resume_context(project.project_id)


def format_resume(context: ResumeContext, *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(context.to_dict(), indent=2)

    lines: list[str] = [
        f"Project: {context.project_name}",
        f"Path: {context.project_path}",
    ]
    if context.current_status:
        lines.append(f"Status: {context.current_status}")
    if context.summary:
        lines.append(f"Latest session: {context.summary}")

    if context.active_blockers:
        lines.append("\nOpen blockers:")
        for blocker in context.active_blockers:
            lines.append(f"  - {blocker.get('title', '')}")

    if context.next_actions:
        lines.append("\nNext actions:")
        for action in context.next_actions:
            lines.append(f"  - {action.get('text', '')}")

    if context.recent_decisions:
        lines.append("\nRecent decisions:")
        for decision in context.recent_decisions:
            lines.append(f"  - {decision.get('title', '')}")

    return "\n".join(lines)


def resume_command(args: Namespace) -> int:
    """CLI entry point for continuity resume."""
    context = get_resume_context(args)
    as_json = getattr(args, "json", False)
    print(format_resume(context, as_json=as_json))
    return 0
