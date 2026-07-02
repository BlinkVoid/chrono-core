from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from continuity_core.capture.git import read_git_state
from continuity_core.capture.handoff import persist_handoff
from continuity_core.domain.models import HandoffPayload
from continuity_core.store.store import Store
from continuity_core.workspace.resolver import resolve_project

DEFAULT_WORKSPACE_ROOT = "~/workspace"
DEFAULT_DB_PATH = str(Path.home() / ".local" / "share" / "continuity-core" / "continuity.db")


def handle_resolve_project(cwd: str, workspace_root: str | None = None) -> dict[str, Any]:
    """Resolve a project from *cwd* and return its identity metadata."""
    ws = Path(workspace_root or DEFAULT_WORKSPACE_ROOT)
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
    ws = Path(workspace_root or DEFAULT_WORKSPACE_ROOT)
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
    ws = Path(workspace_root or DEFAULT_WORKSPACE_ROOT)
    project = resolve_project(Path(cwd), workspace_root=ws)
    store = Store(db_path or DEFAULT_DB_PATH)
    store.init_schema()
    context = store.get_resume_context(project.project_id)
    result = context.to_dict()
    if max_tokens:
        result["max_tokens"] = max_tokens
    return result


mcp = FastMCP("continuity-core")


@mcp.tool(name="continuity_core.resolve_project")
def resolve_project_tool(cwd: str, workspace_root: str | None = None) -> dict[str, Any]:
    """Resolve the project that contains *cwd* within the workspace."""
    return handle_resolve_project(cwd, workspace_root)


@mcp.tool(name="continuity_core.session_handoff")
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


@mcp.tool(name="continuity_core.get_resume_context")
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


def main() -> int:
    """Run the Continuity Core MCP server over stdio."""
    mcp.run(transport="stdio")
    return 0
