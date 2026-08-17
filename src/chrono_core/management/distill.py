from __future__ import annotations

from pathlib import Path
from typing import Any

from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


def distill_project(
    *,
    cwd: str | Path,
    workspace_root: str | Path,
    store: Store,
) -> dict[str, Any]:
    """Derive and persist compact project state from captured continuity records."""
    store.init_schema()
    project = resolve_project(Path(cwd), workspace_root=Path(workspace_root))
    project_id = store.get_or_create_project(project)
    context = store.get_resume_context(project_id)

    phase = _derive_phase(context.active_blockers, context.next_actions, context.summary)
    summary = _derive_summary(context.summary, context.current_status)
    store.update_project_state(project_id, phase=phase, summary=summary)

    return {
        "ok": True,
        "project_id": project_id,
        "project_name": context.project_name,
        "project_path": context.project_path,
        "phase": phase,
        "summary": summary,
        "current_status": context.current_status,
        "active_blocker_count": len(context.active_blockers),
        "next_action_count": len(context.next_actions),
        "recent_decision_count": len(context.recent_decisions),
        "active_blockers": context.active_blockers,
        "next_actions": context.next_actions,
        "recent_decisions": context.recent_decisions,
    }


def _derive_phase(
    active_blockers: list[dict[str, Any]],
    next_actions: list[dict[str, Any]],
    summary: str,
) -> str:
    if active_blockers:
        return "blocked"
    if next_actions:
        return "active"
    if summary.strip():
        return "active"
    return "unknown"


def _derive_summary(summary: str, current_status: str) -> str:
    if summary.strip():
        return summary.strip()
    if current_status.strip():
        return current_status.strip()
    return "No continuity records captured yet."
