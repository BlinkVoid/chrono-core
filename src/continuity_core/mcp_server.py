from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from continuity_core.capture.git import read_git_state
from continuity_core.capture.handoff import persist_handoff
from continuity_core.config import default_db_path, default_workspace_root
from continuity_core.domain.models import HandoffPayload
from continuity_core.management.distill import distill_project
from continuity_core.resume import validate_resume_path
from continuity_core.store.store import Store
from continuity_core.workspace.resolver import resolve_project

DEFAULT_DB_PATH = default_db_path()


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
    store = Store(db_path or DEFAULT_DB_PATH)
    return persist_handoff(store, project, payload, git_state, agent_name=agent_name)


def handle_get_resume_context(
    cwd: str,
    *,
    workspace_root: str | None = None,
    db_path: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Return a compact resume context for the project at *cwd*."""
    ws = Path(workspace_root or default_workspace_root())
    project = resolve_project(Path(cwd), workspace_root=ws)
    store = Store(db_path or DEFAULT_DB_PATH)
    store.init_schema()
    context = validate_resume_path(store.get_resume_context(project.project_id))
    result = context.to_dict()
    if max_tokens:
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
    store = Store(db_path or DEFAULT_DB_PATH)
    store.init_schema()
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
    store = Store(db_path or DEFAULT_DB_PATH)
    store.init_schema()
    project_id = store.get_or_create_project(project)
    blocker = {"title": title, "status": status, "detail": detail or ""}
    store.record_blockers(project_id, None, [blocker])
    return {
        "ok": True,
        "project_id": project_id,
        "recorded_count": 1,
        "blocker": blocker,
    }


def handle_resolve_blocker(blocker_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    """Mark a previously recorded blocker as resolved."""
    store = Store(db_path or DEFAULT_DB_PATH)
    store.init_schema()
    resolved = store.resolve_blocker(blocker_id)
    return {
        "ok": resolved,
        "blocker_id": blocker_id,
        "status": "resolved" if resolved else "not_found",
    }


def handle_complete_action(action_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    """Mark a previously recorded next action as done."""
    store = Store(db_path or DEFAULT_DB_PATH)
    store.init_schema()
    completed = store.complete_next_action(action_id)
    return {
        "ok": completed,
        "action_id": action_id,
        "status": "done" if completed else "not_found",
    }


def handle_search_observations(
    query: str,
    *,
    project_id: str | None = None,
    db_path: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Full-text search captured observations across projects."""
    store = Store(db_path or DEFAULT_DB_PATH)
    store.init_schema()
    results = store.search_observations(query, project_id=project_id, limit=limit)
    return {"ok": True, "query": query, "count": len(results), "results": results}


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
        store=Store(db_path or DEFAULT_DB_PATH),
    )


mcp = FastMCP("continuity-core")


@mcp.tool(name="continuity_core_resolve_project")
def resolve_project_tool(cwd: str, workspace_root: str | None = None) -> dict[str, Any]:
    """Resolve the project that contains *cwd* within the workspace."""
    return handle_resolve_project(cwd, workspace_root)


@mcp.tool(name="continuity_core_session_handoff")
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


@mcp.tool(name="continuity_core_get_resume_context")
def get_resume_context_tool(
    cwd: str,
    workspace_root: str | None = None,
    db_path: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Return a compact resume context for the project at *cwd*."""
    return handle_get_resume_context(
        cwd,
        workspace_root=workspace_root,
        db_path=db_path,
        max_tokens=max_tokens,
    )


@mcp.tool(name="continuity_core_record_decision")
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


@mcp.tool(name="continuity_core_record_blocker")
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


@mcp.tool(name="continuity_core_resolve_blocker")
def resolve_blocker_tool(blocker_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Mark an open blocker as resolved so resume context stops reporting it."""
    return handle_resolve_blocker(blocker_id, db_path=db_path)


@mcp.tool(name="continuity_core_complete_action")
def complete_action_tool(action_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Mark an open next action as done so resume context stops reporting it."""
    return handle_complete_action(action_id, db_path=db_path)


@mcp.tool(name="continuity_core_search_observations")
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


@mcp.tool(name="continuity_core_distill_project")
def distill_project_tool(
    cwd: str,
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Distill captured continuity records into compact project state."""
    return handle_distill_project(cwd, workspace_root=workspace_root, db_path=db_path)


def main() -> int:
    """Run the Continuity Core MCP server over stdio."""
    mcp.run(transport="stdio")
    return 0
