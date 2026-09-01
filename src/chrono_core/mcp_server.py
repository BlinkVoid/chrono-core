from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from chrono_core import services
from chrono_core.capture.git import read_git_state
from chrono_core.capture.handoff import persist_handoff
from chrono_core.config import default_workspace_root
from chrono_core.domain.models import HandoffPayload
from chrono_core.management.distill import distill_project
from chrono_core.management.review import review_project
from chrono_core.resume import validate_resume_path
from chrono_core.workspace.resolver import resolve_project


def handle_resolve_project(cwd: str, workspace_root: str | None = None) -> dict[str, Any]:
    """Resolve a project from *cwd* and return its identity metadata."""
    ws = Path(workspace_root or default_workspace_root())
    project = resolve_project(Path(cwd), workspace_root=ws)
    return project.to_dict()


def handle_session_handoff(
    cwd: str,
    summary: str,
    *,
    workspace_root: str | None = None,
    db_path: str | None = None,
    files_changed: list[str] | None = None,
    tests: list[str] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    blockers: list[dict[str, Any]] | None = None,
    next_actions: list[str] | None = None,
    risks: list[str] | None = None,
    agent_name: str | None = None,
) -> dict[str, Any]:
    """Capture a session handoff for the project at *cwd*."""
    ws = Path(workspace_root or default_workspace_root())
    project = resolve_project(Path(cwd), workspace_root=ws)
    payload = HandoffPayload(
        summary=summary,
        files_changed=list(files_changed or []),
        tests=list(tests or []),
        decisions=list(decisions or []),
        blockers=list(blockers or []),
        next_actions=list(next_actions or []),
        risks=list(risks or []),
    )
    git_state = read_git_state(Path(project.path))
    store = services.open_store(db_path)
    return persist_handoff(store, project, payload, git_state, agent_name=agent_name)


def handle_get_resume_context(
    cwd: str,
    *,
    workspace_root: str | None = None,
    db_path: str | None = None,
    max_tokens: int | None = None,
    branch: str | None = None,
    include_all: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    """Return a compact resume context for the project at *cwd*.

    Scopes to the project's current git branch unless *include_all* is set or an
    explicit *branch* is given (mirroring ``chrono resume`` CLI semantics).
    """
    ws = Path(workspace_root or default_workspace_root())
    project = resolve_project(Path(cwd), workspace_root=ws)
    store = services.open_store(db_path)
    if not include_all and branch is None:
        branch = read_git_state(Path(cwd)).branch
    context = validate_resume_path(
        store.get_resume_context(
            store.resolve_project_id(project),
            branch=branch,
            include_all=include_all,
            limit=limit,
        )
    )
    result = context.to_dict()
    if max_tokens is not None:
        result = _fit_to_token_budget(result, max_tokens)
    return result


def _estimate_tokens(result: dict[str, Any]) -> int:
    # Rough serialized-size heuristic: ~4 characters per token.
    return len(json.dumps(result)) // 4


def _fit_to_token_budget(result: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    """Trim resume context to an approximate token budget, least useful items first.

    Lists are ordered newest-first, so trimming drops the oldest entries.
    Project identity and current status are never removed.
    """
    result["truncated"] = False
    for key in ("recent_decisions", "next_actions", "active_blockers"):
        while _estimate_tokens(result) > max_tokens and result[key]:
            result[key].pop()
            result["truncated"] = True
    while _estimate_tokens(result) > max_tokens and result["summary"]:
        result["summary"] = result["summary"][: len(result["summary"]) // 2]
        result["truncated"] = True
    return result


def handle_record_decision(
    cwd: str,
    title: str,
    *,
    rationale: str | None = None,
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Record a project decision outside a session handoff."""
    ws = Path(workspace_root or default_workspace_root())
    project = resolve_project(Path(cwd), workspace_root=ws)
    store = services.open_store(db_path)
    project_id = store.get_or_create_project(project)
    decision = {"title": title, "rationale": rationale or ""}
    store.record_decisions(project_id, None, [decision])
    return {
        "ok": True,
        "project_id": project_id,
        "recorded_count": 1,
        "decision": decision,
    }


def handle_record_blocker(
    cwd: str,
    title: str,
    *,
    detail: str | None = None,
    status: str = "open",
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Record a project blocker outside a session handoff."""
    ws = Path(workspace_root or default_workspace_root())
    project = resolve_project(Path(cwd), workspace_root=ws)
    store = services.open_store(db_path)
    project_id = store.get_or_create_project(project)
    blocker = {"title": title, "status": status, "detail": detail or ""}
    store.record_blockers(project_id, None, [blocker])
    return {
        "ok": True,
        "project_id": project_id,
        "recorded_count": 1,
        "blocker": blocker,
    }


def handle_record_observation(
    cwd: str,
    content: str,
    *,
    kind: str = "lesson",
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Record explicitly semantic evidence for safe pattern mining."""
    return services.record_semantic_observation(
        db_path,
        cwd,
        content=content,
        kind=kind,
        workspace_root=workspace_root,
    )


def handle_resolve_blocker(blocker_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    """Mark a previously recorded blocker as resolved."""
    return services.resolve_blocker(db_path, blocker_id)


def handle_complete_action(action_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    """Mark a previously recorded next action as done."""
    return services.complete_action(db_path, action_id)


def handle_search_observations(
    query: str,
    *,
    project_id: str | None = None,
    db_path: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Full-text search captured observations across projects."""
    return services.search_observations_safe(
        db_path, query, project_id=project_id, limit=limit
    )


def handle_find_similar_projects(
    cwd: str,
    *,
    workspace_root: str | None = None,
    db_path: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Rank other managed projects by shared distilled evidence and observations."""
    return services.find_similar_projects(
        db_path, cwd, workspace_root=workspace_root, limit=limit
    )


def handle_distill_project(
    cwd: str,
    *,
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Distill captured continuity records into compact project state."""
    return distill_project(
        cwd=cwd,
        workspace_root=workspace_root or default_workspace_root(),
        store=services.open_store(db_path),
    )


def handle_review_project(
    cwd: str,
    *,
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Run a project management review with doc drift and health output."""
    return review_project(
        cwd=cwd,
        workspace_root=workspace_root or default_workspace_root(),
        store=services.open_store(db_path),
    )


mcp = FastMCP("chrono-core")


@mcp.tool(name="chrono_core_resolve_project")
def resolve_project_tool(cwd: str, workspace_root: str | None = None) -> dict[str, Any]:
    """Resolve the project that contains *cwd* within the workspace."""
    return handle_resolve_project(cwd, workspace_root)


@mcp.tool(name="chrono_core_session_handoff")
def session_handoff_tool(
    cwd: str,
    summary: str,
    workspace_root: str | None = None,
    db_path: str | None = None,
    files_changed: list[str] | None = None,
    tests: list[str] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    blockers: list[dict[str, Any]] | None = None,
    next_actions: list[str] | None = None,
    risks: list[str] | None = None,
    agent_name: str | None = None,
) -> dict[str, Any]:
    """Persist a structured session handoff for the project at *cwd*."""
    return handle_session_handoff(
        cwd,
        summary,
        workspace_root=workspace_root,
        db_path=db_path,
        files_changed=files_changed,
        tests=tests,
        decisions=decisions,
        blockers=blockers,
        next_actions=next_actions,
        risks=risks,
        agent_name=agent_name,
    )


@mcp.tool(name="chrono_core_get_resume_context")
def get_resume_context_tool(
    cwd: str,
    workspace_root: str | None = None,
    db_path: str | None = None,
    max_tokens: int | None = None,
    branch: str | None = None,
    include_all: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    """Return a compact resume context for the project at *cwd*.

    Scopes to the project's current git branch unless include_all is true or an
    explicit branch is given; limit caps returned items in every mode.
    """
    return handle_get_resume_context(
        cwd,
        workspace_root=workspace_root,
        db_path=db_path,
        max_tokens=max_tokens,
        branch=branch,
        include_all=include_all,
        limit=limit,
    )


@mcp.tool(name="chrono_core_record_decision")
def record_decision_tool(
    cwd: str,
    title: str,
    rationale: str | None = None,
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Persist a project decision outside a session handoff."""
    return handle_record_decision(
        cwd,
        title,
        rationale=rationale,
        workspace_root=workspace_root,
        db_path=db_path,
    )


@mcp.tool(name="chrono_core_record_blocker")
def record_blocker_tool(
    cwd: str,
    title: str,
    detail: str | None = None,
    status: str = "open",
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Persist a project blocker outside a session handoff."""
    return handle_record_blocker(
        cwd,
        title,
        detail=detail,
        status=status,
        workspace_root=workspace_root,
        db_path=db_path,
    )


@mcp.tool(name="chrono_core_record_observation")
def record_observation_tool(
    cwd: str,
    content: str,
    kind: str = "lesson",
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Persist a semantic lesson or pattern candidate outside a handoff."""
    return handle_record_observation(
        cwd,
        content,
        kind=kind,
        workspace_root=workspace_root,
        db_path=db_path,
    )


@mcp.tool(name="chrono_core_resolve_blocker")
def resolve_blocker_tool(blocker_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Mark an open blocker as resolved so resume context stops reporting it."""
    return handle_resolve_blocker(blocker_id, db_path=db_path)


@mcp.tool(name="chrono_core_complete_action")
def complete_action_tool(action_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Mark an open next action as done so resume context stops reporting it."""
    return handle_complete_action(action_id, db_path=db_path)


def handle_cancel_action(
    action_id: str, *, reason: str | None = None, db_path: str | None = None
) -> dict[str, Any]:
    """Close a stale or wrong next action without pretending it was done."""
    return services.cancel_action(db_path, action_id, reason)


@mcp.tool(name="chrono_core_cancel_action")
def cancel_action_tool(
    action_id: str, reason: str | None = None, db_path: str | None = None
) -> dict[str, Any]:
    """Cancel a next action so resume stops surfacing it as open work."""
    return handle_cancel_action(action_id, reason=reason, db_path=db_path)


def handle_edit_action(
    action_id: str, text: str, *, db_path: str | None = None
) -> dict[str, Any]:
    """Rewrite a next action's text truthfully while keeping its history."""
    return services.edit_action(db_path, action_id, text)


@mcp.tool(name="chrono_core_edit_action")
def edit_action_tool(
    action_id: str, text: str, db_path: str | None = None
) -> dict[str, Any]:
    """Rewrite a next action in place, keeping the previous wording in history."""
    return handle_edit_action(action_id, text, db_path=db_path)


def handle_reopen_action(action_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    """Return a completed or cancelled next action to open status."""
    return services.reopen_action(db_path, action_id)


@mcp.tool(name="chrono_core_reopen_action")
def reopen_action_tool(action_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Reopen a next action so resume context reports it as open work again."""
    return handle_reopen_action(action_id, db_path=db_path)


def handle_supersede_action(
    action_id: str, text: str, *, db_path: str | None = None
) -> dict[str, Any]:
    """Retire a next action by linking it to a newly created replacement."""
    return services.supersede_action(db_path, action_id, text)


@mcp.tool(name="chrono_core_supersede_action")
def supersede_action_tool(
    action_id: str, text: str, db_path: str | None = None
) -> dict[str, Any]:
    """Replace a next action with a linked successor and retire the original."""
    return handle_supersede_action(action_id, text, db_path=db_path)


def handle_cancel_blocker(
    blocker_id: str, *, reason: str | None = None, db_path: str | None = None
) -> dict[str, Any]:
    """Close a stale or wrong blocker without pretending it was resolved."""
    return services.cancel_blocker(db_path, blocker_id, reason)


@mcp.tool(name="chrono_core_cancel_blocker")
def cancel_blocker_tool(
    blocker_id: str, reason: str | None = None, db_path: str | None = None
) -> dict[str, Any]:
    """Cancel a blocker so resume stops surfacing it as open work."""
    return handle_cancel_blocker(blocker_id, reason=reason, db_path=db_path)


def handle_edit_blocker(
    blocker_id: str, text: str, *, db_path: str | None = None
) -> dict[str, Any]:
    """Rewrite a blocker's title truthfully while keeping its record."""
    return services.edit_blocker(db_path, blocker_id, text)


@mcp.tool(name="chrono_core_edit_blocker")
def edit_blocker_tool(
    blocker_id: str, text: str, db_path: str | None = None
) -> dict[str, Any]:
    """Rewrite a blocker's title so it stays an accurate statement of the obstacle."""
    return handle_edit_blocker(blocker_id, text, db_path=db_path)


def handle_reopen_blocker(blocker_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    """Return a resolved or cancelled blocker to open status."""
    return services.reopen_blocker(db_path, blocker_id)


@mcp.tool(name="chrono_core_reopen_blocker")
def reopen_blocker_tool(blocker_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Reopen a blocker so resume context reports it as active again."""
    return handle_reopen_blocker(blocker_id, db_path=db_path)


def handle_report_bug(
    cwd: str,
    title: str,
    *,
    severity: str = "medium",
    detail: str = "",
    workspace_wide: bool = False,
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """File a bug against the project at *cwd*, or against the whole workspace."""
    return services.report_bug(
        db_path,
        cwd,
        title=title,
        severity=severity,
        detail=detail,
        workspace_wide=workspace_wide,
        workspace_root=workspace_root,
    )


def handle_list_bugs(
    *,
    status: str | None = "open",
    severity: str | None = None,
    project_id: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """List bugs filtered by status, severity, and/or project."""
    return services.list_bugs(
        db_path, status=status, severity=severity, project_id=project_id
    )


def handle_update_bug(
    bug_id: str,
    *,
    status: str | None = None,
    severity: str | None = None,
    detail: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Update mutable fields on an existing bug."""
    fields: dict[str, Any] = {}
    if status is not None:
        fields["status"] = status
    if severity is not None:
        fields["severity"] = severity
    if detail is not None:
        fields["detail"] = detail
    return services.update_bug(db_path, bug_id, **fields)


@mcp.tool(name="chrono_core_search_observations")
def search_observations_tool(
    query: str,
    project_id: str | None = None,
    db_path: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Full-text search captured observations (files, tests, risks, imported metadata)."""
    return handle_search_observations(
        query, project_id=project_id, db_path=db_path, limit=limit
    )


@mcp.tool(name="chrono_core_report_bug")
def report_bug_tool(
    cwd: str,
    title: str,
    severity: str = "medium",
    detail: str = "",
    workspace: bool = False,
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """File a bug against the project at cwd, or workspace-wide."""
    return handle_report_bug(
        cwd,
        title,
        severity=severity,
        detail=detail,
        workspace_wide=workspace,
        workspace_root=workspace_root,
        db_path=db_path,
    )


@mcp.tool(name="chrono_core_list_bugs")
def list_bugs_tool(
    status: str | None = "open",
    severity: str | None = None,
    project_id: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """List bugs, defaulting to open ones across the workspace."""
    return handle_list_bugs(
        status=status, severity=severity, project_id=project_id, db_path=db_path
    )


@mcp.tool(name="chrono_core_update_bug")
def update_bug_tool(
    bug_id: str,
    status: str | None = None,
    severity: str | None = None,
    detail: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Update a bug's status, severity, or detail."""
    return handle_update_bug(
        bug_id, status=status, severity=severity, detail=detail, db_path=db_path
    )


def handle_list_projects(
    *,
    status: str | None = None,
    tag: str | None = None,
    limit: int | None = None,
    dirty: bool | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """List registered projects with optional status/tag/limit filters."""
    return services.list_projects(db_path, status=status, tag=tag, limit=limit, dirty=dirty)


def handle_discover_projects(
    *,
    workspace_root: str | None = None,
    max_depth: int = 3,
    include_provisional: bool = False,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Persist a bounded workspace inventory refresh and reconciliation."""
    return services.refresh_workspace_inventory(
        db_path,
        workspace_root=workspace_root,
        max_depth=max_depth,
        include_provisional=include_provisional,
    )


def handle_refresh_project(
    project: str, *, db_path: str | None = None
) -> dict[str, Any]:
    """Refresh current Git inventory for one registered project."""
    return services.refresh_project_inventory(db_path, project)


def handle_get_project(project: str, *, db_path: str | None = None) -> dict[str, Any]:
    """Show one project by exact id, absolute path, or relative path."""
    return services.get_project(db_path, project)


def handle_update_project_metadata(
    project: str,
    *,
    status: str | None = None,
    lifecycle_phase: str | None = None,
    priority: str | None = None,
    tags: list[str] | None = None,
    owner: str | None = None,
    description_usage: str | None = None,
    summary: str | None = None,
    notes: str | None = None,
    other_factors: dict[str, Any] | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Update project catalog metadata and return the refreshed record."""
    fields: dict[str, Any] = {}
    for key, value in (
        ("status", status),
        ("lifecycle_phase", lifecycle_phase),
        ("priority", priority),
        ("tags", tags),
        ("owner", owner),
        ("description_usage", description_usage),
        ("summary", summary),
        ("notes", notes),
        ("other_factors", other_factors),
    ):
        if value is not None:
            fields[key] = value
    return services.update_project_metadata(db_path, project, fields)


def handle_update_project_progress(
    project: str, text: str, *, db_path: str | None = None
) -> dict[str, Any]:
    """Update one project's current progress and return the refreshed record."""
    return services.update_project_progress(db_path, project, text)


def handle_push_bug_to_github(
    bug_id: str,
    *,
    repo: str | None = None,
    dry_run: bool = False,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Push one local bug to one GitHub issue through the gh CLI REST bridge."""
    return services.push_bug_to_github(db_path, bug_id, repo=repo, dry_run=dry_run)


@mcp.tool(name="chrono_core_push_bug_to_github")
def push_bug_to_github_tool(
    bug_id: str,
    repo: str | None = None,
    dry_run: bool = False,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Push one local bug to GitHub; this mutates the external repository.

    ``dry_run`` returns a plan without any side effect.
    """
    return handle_push_bug_to_github(bug_id, repo=repo, dry_run=dry_run, db_path=db_path)


@mcp.tool(name="chrono_core_list_projects")
def list_projects_tool(
    status: str | None = None,
    tag: str | None = None,
    limit: int | None = None,
    dirty: bool | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """List registered projects with optional metadata and dirty-state filters."""
    return handle_list_projects(
        status=status, tag=tag, limit=limit, dirty=dirty, db_path=db_path
    )


@mcp.tool(name="chrono_core_discover_projects")
def discover_projects_tool(
    workspace_root: str | None = None,
    max_depth: int = 3,
    include_provisional: bool = False,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Discover and persist current project inventory; this mutates local state."""
    return handle_discover_projects(
        workspace_root=workspace_root,
        max_depth=max_depth,
        include_provisional=include_provisional,
        db_path=db_path,
    )


@mcp.tool(name="chrono_core_refresh_project")
def refresh_project_tool(project: str, db_path: str | None = None) -> dict[str, Any]:
    """Refresh one registered project's current Git inventory."""
    return handle_refresh_project(project, db_path=db_path)


@mcp.tool(name="chrono_core_get_project")
def get_project_tool(
    project: str, db_path: str | None = None
) -> dict[str, Any]:
    """Show one project by exact id, absolute path, or workspace-relative path."""
    return handle_get_project(project, db_path=db_path)


@mcp.tool(name="chrono_core_update_project_metadata")
def update_project_metadata_tool(
    project: str,
    status: str | None = None,
    lifecycle_phase: str | None = None,
    priority: str | None = None,
    tags: list[str] | None = None,
    owner: str | None = None,
    description_usage: str | None = None,
    summary: str | None = None,
    notes: str | None = None,
    other_factors: dict[str, Any] | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Update project catalog metadata; tags replace the whole tag set."""
    return handle_update_project_metadata(
        project,
        status=status,
        lifecycle_phase=lifecycle_phase,
        priority=priority,
        tags=tags,
        owner=owner,
        description_usage=description_usage,
        summary=summary,
        notes=notes,
        other_factors=other_factors,
        db_path=db_path,
    )


@mcp.tool(name="chrono_core_update_project_progress")
def update_project_progress_tool(
    project: str, text: str, db_path: str | None = None
) -> dict[str, Any]:
    """Set a project's current progress note."""
    return handle_update_project_progress(project, text, db_path=db_path)


@mcp.tool(name="chrono_core_find_similar_projects")
def find_similar_projects_tool(
    cwd: str,
    workspace_root: str | None = None,
    db_path: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Find related projects ranked by shared distilled state and observations."""
    return handle_find_similar_projects(
        cwd, workspace_root=workspace_root, db_path=db_path, limit=limit
    )


@mcp.tool(name="chrono_core_distill_project")
def distill_project_tool(
    cwd: str,
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Distill captured continuity records into compact project state."""
    return handle_distill_project(cwd, workspace_root=workspace_root, db_path=db_path)


@mcp.tool(name="chrono_core_review_project")
def review_project_tool(
    cwd: str,
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Run doc reconciliation, health review, advice, and review queue generation."""
    return handle_review_project(cwd, workspace_root=workspace_root, db_path=db_path)


def main() -> int:
    """Run the Chrono Core MCP server over stdio."""
    try:
        mcp.run(transport="stdio")
    finally:
        services.close_stores()
    return 0
