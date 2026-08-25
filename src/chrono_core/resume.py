from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from chrono_core import services
from chrono_core.capture.git import read_git_state
from chrono_core.config import default_workspace_root
from chrono_core.domain.models import ResumeContext
from chrono_core.workspace.resolver import resolve_project


def validate_resume_path(context: ResumeContext) -> ResumeContext:
    """Reject stored project locations that can no longer be resumed safely."""
    if context.project_path and not Path(context.project_path).is_dir():
        raise FileNotFoundError(
            f"stored resume path no longer exists: {context.project_path}"
        )
    return context


def get_resume_context(args: Namespace) -> ResumeContext:
    """Resolve project and return branch-scoped resume context from the store."""
    project_path = Path(getattr(args, "cwd", "."))
    workspace_root = Path(getattr(args, "workspace_root", None) or default_workspace_root())
    project = resolve_project(project_path, workspace_root=workspace_root)

    db_path = getattr(args, "db_path", None)
    store = services.open_store(db_path)

    include_all = getattr(args, "all", False)
    branch = getattr(args, "branch", None)
    if not include_all and branch is None:
        branch = read_git_state(project_path).branch

    context = store.get_resume_context(
        store.resolve_project_id(project),
        branch=branch,
        include_all=include_all,
        limit=getattr(args, "limit", 20),
    )
    return validate_resume_path(context)


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

    scope = "all branches" if context.branch == "" else context.branch
    if context.active_blockers or context.hidden_blockers:
        lines.append(f"\nOpen blockers ({scope}):")
        for blocker in context.active_blockers:
            lines.append(f"  - [{blocker.get('id', '')}] {blocker.get('title', '')}")
        if context.hidden_blockers:
            lines.append(
                f"  (+{context.hidden_blockers} more on other branches: --all to show)"
            )

    if context.next_actions or context.hidden_actions:
        lines.append(f"\nNext actions ({scope}):")
        for action in context.next_actions:
            lines.append(f"  - [{action.get('id', '')}] {action.get('text', '')}")
        if context.hidden_actions:
            lines.append(
                f"  (+{context.hidden_actions} more on other branches: --all to show)"
            )

    if context.recent_decisions:
        lines.append("\nRecent decisions:")
        for decision in context.recent_decisions:
            lines.append(f"  - {decision.get('title', '')}")

    return "\n".join(lines)


def resume_command(args: Namespace) -> int:
    """CLI entry point for chrono resume."""
    context = get_resume_context(args)
    as_json = getattr(args, "json", False)
    print(format_resume(context, as_json=as_json))
    return 0
