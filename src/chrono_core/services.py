"""Shared operations used by both the CLI and the MCP server."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from chrono_core.config import default_db_path, default_workspace_root
from chrono_core.store.store import Store

_STORES: dict[str, Store] = {}


def open_store(db_path: str | None = None) -> Store:
    """Open (and cache per resolved path) a schema-initialized Store."""
    resolved = str(db_path) if db_path else default_db_path()
    store = _STORES.get(resolved)
    if store is None:
        store = Store(resolved)
        store.init_schema()
        _STORES[resolved] = store
    return store


def close_stores() -> None:
    for store in _STORES.values():
        store.close()
    _STORES.clear()


def resolve_project_id_from(cwd: str, workspace_root: str | None, store: Store) -> str:
    from chrono_core.workspace.resolver import resolve_project

    project = resolve_project(
        Path(cwd), workspace_root=Path(workspace_root or default_workspace_root())
    )
    return store.resolve_project_id(project)


def lifecycle_result(entity: str, verb: str, result: dict[str, Any]) -> dict[str, Any]:
    out = {"ok": result.get("ok", False), f"{entity}_id": result.get(f"{entity}_id")}
    out.update({k: v for k, v in result.items() if k not in out})
    out["verb"] = verb
    return out


def _bool_result(entity: str, found: bool, entity_id: str, done_status: str) -> dict[str, Any]:
    return {
        "ok": found,
        f"{entity}_id": entity_id,
        "status": done_status if found else "not_found",
    }


def cancel_action(
    db_path: str | None, action_id: str, reason: str | None = None
) -> dict[str, Any]:
    return lifecycle_result(
        "action", "cancel", open_store(db_path).cancel_next_action(action_id, reason)
    )


def complete_action(db_path: str | None, action_id: str) -> dict[str, Any]:
    completed = open_store(db_path).complete_next_action(action_id)
    return lifecycle_result(
        "action", "complete", _bool_result("action", completed, action_id, "done")
    )


def edit_action(db_path: str | None, action_id: str, text: str) -> dict[str, Any]:
    return lifecycle_result(
        "action", "edit", open_store(db_path).edit_next_action(action_id, text)
    )


def reopen_action(db_path: str | None, action_id: str) -> dict[str, Any]:
    return lifecycle_result(
        "action", "reopen", open_store(db_path).reopen_next_action(action_id)
    )


def supersede_action(db_path: str | None, action_id: str, text: str) -> dict[str, Any]:
    return lifecycle_result(
        "action", "supersede", open_store(db_path).supersede_next_action(action_id, text)
    )


def resolve_blocker(db_path: str | None, blocker_id: str) -> dict[str, Any]:
    resolved = open_store(db_path).resolve_blocker(blocker_id)
    return lifecycle_result(
        "blocker", "resolve", _bool_result("blocker", resolved, blocker_id, "resolved")
    )


def cancel_blocker(
    db_path: str | None, blocker_id: str, reason: str | None = None
) -> dict[str, Any]:
    return lifecycle_result(
        "blocker", "cancel", open_store(db_path).cancel_blocker(blocker_id, reason)
    )


def edit_blocker(db_path: str | None, blocker_id: str, title: str) -> dict[str, Any]:
    return lifecycle_result(
        "blocker", "edit", open_store(db_path).edit_blocker(blocker_id, title)
    )


def reopen_blocker(db_path: str | None, blocker_id: str) -> dict[str, Any]:
    return lifecycle_result(
        "blocker", "reopen", open_store(db_path).reopen_blocker(blocker_id)
    )


def report_bug(
    db_path: str | None,
    cwd: str,
    *,
    title: str,
    severity: str = "medium",
    detail: str = "",
    workspace_wide: bool = False,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    from chrono_core.config import default_workspace_root
    from chrono_core.workspace.resolver import resolve_project

    store = open_store(db_path)
    project_id: str | None = None
    if not workspace_wide:
        project = resolve_project(
            Path(cwd), workspace_root=Path(workspace_root or default_workspace_root())
        )
        project_id = store.get_or_create_project(project)
    bug_id = store.report_bug(project_id, title, detail=detail, severity=severity)
    return {
        "ok": True,
        "bug_id": bug_id,
        "project_id": project_id,
        "bug": store.get_bug(bug_id),
    }


def list_bugs(
    db_path: str | None,
    *,
    status: str | None = "open",
    severity: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    bugs = open_store(db_path).list_bugs(
        status=status, severity=severity, project_id=project_id
    )
    return {"ok": True, "count": len(bugs), "bugs": bugs}


def update_bug(db_path: str | None, bug_id: str, **fields: Any) -> dict[str, Any]:
    try:
        return open_store(db_path).update_bug(bug_id, **fields)
    except ValueError as exc:
        return {"ok": False, "bug_id": bug_id, "error": str(exc)}


def search_observations_safe(
    db_path: str | None, query: str, *, project_id: str | None = None, limit: int = 20
) -> dict[str, Any]:
    """Full-text observation search that reports malformed FTS queries structurally."""
    try:
        results = open_store(db_path).search_observations(
            query, project_id=project_id, limit=max(limit, 0)
        )
    except sqlite3.OperationalError as exc:
        return {
            "ok": False,
            "query": query,
            "error": f"invalid query: {exc}",
            "results": [],
        }
    return {"ok": True, "query": query, "count": len(results), "results": results}
