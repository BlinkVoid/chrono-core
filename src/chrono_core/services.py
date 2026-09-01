"""Shared operations used by both the CLI and the MCP server."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from chrono_core.config import default_db_path, default_workspace_root
from chrono_core.store.store import (
    AmbiguousProjectSelector,
    SchemaUpgradeRequired,
    Store,
)
from chrono_core.workspace.inventory import subprocess_runner

_STORES: dict[str, Store] = {}


def open_store(db_path: str | None = None, *, read_only: bool = False) -> Store:
    """Open a Store, caching schema-initialized writable connections."""
    resolved = str(db_path) if db_path else default_db_path()
    if read_only:
        return Store(resolved, read_only=True)
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


def plan_pattern_promotion(
    db_path: str | None,
    pattern_id: str,
    *,
    skill_path: str,
    evidence_path: str,
    scope: str = "global",
    project_root: str | None = None,
    copy: bool = False,
) -> dict[str, Any]:
    """Build a read-only GearCore promotion plan for a validated pattern."""
    from chrono_core.integrations import pattern_promotion as promotion

    resolved_db = Path(db_path or default_db_path()).expanduser()
    if not resolved_db.is_file():
        return {
            "ok": False,
            "code": "database_not_found",
            "pattern_id": pattern_id,
        }
    store = Store(resolved_db, read_only=True)
    try:
        pattern = store.get_pattern(pattern_id)
        if pattern is None:
            return {"ok": False, "code": "pattern_not_found", "pattern_id": pattern_id}
        if pattern["status"] == "promoted":
            return {
                "ok": False,
                "code": "already_promoted",
                "pattern_id": pattern_id,
                "pattern": pattern,
            }
        if pattern["status"] != "validated":
            return {
                "ok": False,
                "code": "pattern_not_eligible",
                "pattern_id": pattern_id,
                "pattern": pattern,
            }
        try:
            return promotion.build_plan(
                pattern,
                skill_path=skill_path,
                evidence_path=evidence_path,
                scope=scope,
                project_root=project_root,
                symlink=not copy,
            )
        except promotion.PatternPromotionError as exc:
            return {
                "ok": False,
                "code": exc.code,
                "pattern_id": pattern_id,
                "pattern": pattern,
            }
    finally:
        store.close()


def promote_pattern(
    db_path: str | None,
    pattern_id: str,
    *,
    skill_path: str,
    evidence_path: str,
    plan_digest: str,
    scope: str = "global",
    project_root: str | None = None,
    copy: bool = False,
    runner: Any = None,
) -> dict[str, Any]:
    """Apply an unchanged promotion plan and mark the pattern promoted."""
    from chrono_core.integrations import pattern_promotion as promotion

    planned = plan_pattern_promotion(
        db_path,
        pattern_id,
        skill_path=skill_path,
        evidence_path=evidence_path,
        scope=scope,
        project_root=project_root,
        copy=copy,
    )
    if not planned.get("ok"):
        return planned
    if plan_digest != planned["plan_digest"]:
        return {
            "ok": False,
            "code": "stale_plan",
            "pattern_id": pattern_id,
            "plan_digest": planned["plan_digest"],
        }

    result = promotion.execute(planned["argv"], runner=runner)
    command = {"argv": planned["argv"], "returncode": result.returncode}
    if result.missing:
        return {
            "ok": False,
            "code": "gearcore_missing",
            "pattern_id": pattern_id,
            "command": command,
            "error": promotion.bounded_error(result.stderr),
        }
    if result.timed_out:
        return {
            "ok": False,
            "code": "timeout",
            "pattern_id": pattern_id,
            "command": command,
            "error": promotion.bounded_error(result.stderr),
        }
    if result.returncode != 0:
        return {
            "ok": False,
            "code": "command_failed",
            "pattern_id": pattern_id,
            "command": command,
            "error": promotion.bounded_error(result.stderr),
        }

    try:
        updated = open_store(db_path).set_pattern_status(pattern_id, "promoted")
        if not updated.get("ok"):
            raise RuntimeError("pattern status row was not updated")
    except Exception:
        return {
            "ok": False,
            "partial": True,
            "code": "status_write_failed",
            "pattern_id": pattern_id,
            "command": command,
        }
    refreshed = open_store(db_path).get_pattern(pattern_id)
    return {
        "ok": True,
        "partial": False,
        "pattern_id": pattern_id,
        "status": "promoted",
        "pattern": refreshed,
        "command": command,
        "plan_digest": planned["plan_digest"],
    }


def list_projects(
    db_path: str | None,
    *,
    status: str | None = None,
    tag: str | None = None,
    limit: int | None = None,
    dirty: bool | None = None,
) -> dict[str, Any]:
    """List registered projects with optional filters (read-only)."""
    resolved = Path(db_path or default_db_path()).expanduser()
    if not resolved.is_file():
        return {
            "ok": False,
            "code": "database_not_found",
            "db_path": str(resolved),
            "count": 0,
            "projects": [],
        }
    store = Store(resolved, read_only=True)
    try:
        try:
            projects = store.list_projects(status=status, tag=tag, limit=limit, dirty=dirty)
        except SchemaUpgradeRequired:
            return {
                "ok": False,
                "code": "schema_upgrade_required",
                "db_path": str(resolved),
                "count": 0,
                "projects": [],
            }
    finally:
        store.close()
    return {"ok": True, "count": len(projects), "projects": projects}


def refresh_workspace_inventory(
    db_path: str | None,
    *,
    workspace_root: str | None = None,
    max_depth: int = 3,
    include_provisional: bool = False,
    git_runner: Any | None = None,
) -> dict[str, Any]:
    """Persist one bounded workspace discovery and current Git inventory refresh."""
    from chrono_core.workspace.discovery import DiscoveryOptions, discover_workspace

    root = Path(workspace_root or default_workspace_root()).expanduser().resolve()
    # Validate before opening a writable Store, so an invalid root performs no
    # reconciliation and does not create a new database as a side effect.
    if not root.exists() or not root.is_dir():
        reason = "workspace_root_not_found" if not root.exists() else "workspace_root_not_directory"
        return {
            "ok": False,
            "workspace_root": str(root),
            "discovered_count": 0,
            "persisted_count": 0,
            "refreshed_count": 0,
            "missing_count": 0,
            "failed_count": 0,
            "failures": [],
            "skipped": [{"reason": reason, "path": str(root)}],
        }
    resolved = Path(db_path or default_db_path()).expanduser()
    store = Store(resolved)
    try:
        store.init_schema()
        result = discover_workspace(
            workspace_root=root,
            store=store,
            options=DiscoveryOptions(
                max_depth=max_depth, include_provisional=include_provisional
            ),
            git_runner=git_runner or subprocess_runner,
        )
        return result.to_dict()
    finally:
        store.close()


def refresh_project_inventory(
    db_path: str | None,
    selector: str,
    *,
    git_runner: Any | None = None,
) -> dict[str, Any]:
    """Refresh one registered project's current inventory without auto-refreshing reads."""
    from chrono_core.workspace.inventory import collect_git_inventory
    from chrono_core.workspace.resolver import PROJECT_MARKERS

    resolved = Path(db_path or default_db_path()).expanduser()
    if not resolved.is_file():
        return {
            "ok": False,
            "code": "database_not_found",
            "db_path": str(resolved),
            "project": None,
        }
    store = Store(resolved)
    try:
        store.init_schema()
        try:
            project = store.get_project(selector)
        except SchemaUpgradeRequired:
            return {"ok": False, "code": "schema_upgrade_required", "project": None}
        except AmbiguousProjectSelector:
            return {"ok": False, "code": "ambiguous_project", "project": None}
        if project is None:
            return {"ok": False, "code": "project_not_found", "project": None}
        path = Path(project["path"])
        if not path.exists() or not path.is_dir():
            return {"ok": False, "code": "path_not_found", "project": None}
        prior = project.get("inventory")
        if prior:
            workspace = prior["workspace_root"]
            marker = prior["marker"]
            depth = int(prior["depth"])
        else:
            workspace_path = path.parent
            workspace = str(workspace_path)
            marker = next(
                (name for name in PROJECT_MARKERS if (path / name).exists()),
                "provisional",
            )
            depth = 1
        collected = (
            collect_git_inventory(path, runner=git_runner)
            if git_runner
            else collect_git_inventory(path)
        )
        store.upsert_project_inventory(
            project_id=project["id"], workspace_root=workspace, marker=marker,
            depth=depth, collected=collected,
        )
        refreshed = store.get_project(project["id"])
        return {"ok": True, "error": collected.get("error"), "project": refreshed}
    finally:
        store.close()


def get_project(db_path: str | None, selector: str) -> dict[str, Any]:
    """Show one project by exact id, absolute path, or relative path (read-only)."""
    resolved = Path(db_path or default_db_path()).expanduser()
    if not resolved.is_file():
        return {
            "ok": False,
            "code": "database_not_found",
            "db_path": str(resolved),
            "selector": selector,
            "project": None,
        }
    store = Store(resolved, read_only=True)
    try:
        try:
            project = store.get_project(selector)
        except SchemaUpgradeRequired:
            return {
                "ok": False,
                "code": "schema_upgrade_required",
                "db_path": str(resolved),
                "selector": selector,
                "project": None,
            }
    except AmbiguousProjectSelector:
        return {
            "ok": False,
            "code": "ambiguous_project",
            "selector": selector,
            "project": None,
        }
    finally:
        store.close()
    if project is None:
        return {
            "ok": False,
            "code": "project_not_found",
            "selector": selector,
            "project": None,
        }
    return {"ok": True, "project": project}


def update_project_metadata(
    db_path: str | None, selector: str, fields: dict[str, Any]
) -> dict[str, Any]:
    """Update project catalog metadata and return the refreshed record."""
    resolved = Path(db_path or default_db_path()).expanduser()
    if not resolved.is_file():
        return {
            "ok": False,
            "code": "database_not_found",
            "db_path": str(resolved),
            "project": None,
        }
    if not fields:
        return {
            "ok": False,
            "code": "empty_update",
            "error": "update rejected: no fields supplied",
        }
    store = open_store(db_path)
    try:
        try:
            project = store.get_project(selector)
        except AmbiguousProjectSelector:
            return {
                "ok": False,
                "code": "ambiguous_project",
                "selector": selector,
                "project": None,
            }
        if project is None:
            return {
                "ok": False,
                "code": "project_not_found",
                "selector": selector,
                "project": None,
            }
        try:
            updated = store.update_project_metadata(project["id"], fields)
        except ValueError as exc:
            return {"ok": False, "code": "invalid_input", "error": str(exc)}
    finally:
        store.close()
    return {"ok": True, "project": updated}


def update_project_progress(
    db_path: str | None, selector: str, text: str
) -> dict[str, Any]:
    """Update one project's current progress and return the refreshed record."""
    resolved = Path(db_path or default_db_path()).expanduser()
    if not resolved.is_file():
        return {
            "ok": False,
            "code": "database_not_found",
            "db_path": str(resolved),
            "project": None,
        }
    store = open_store(db_path)
    try:
        try:
            project = store.get_project(selector)
        except AmbiguousProjectSelector:
            return {
                "ok": False,
                "code": "ambiguous_project",
                "selector": selector,
                "project": None,
            }
        if project is None:
            return {
                "ok": False,
                "code": "project_not_found",
                "selector": selector,
                "project": None,
            }
        updated = store.update_project_progress(project["id"], text)
    finally:
        store.close()
    return {"ok": True, "project": updated}


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


def record_semantic_observation(
    db_path: str | None,
    cwd: str,
    *,
    content: str,
    kind: str = "lesson",
    workspace_root: str | None = None,
) -> dict[str, Any]:
    """Capture mineable project knowledge through a constrained public path."""
    from chrono_core.management.patterns import MINABLE_OBSERVATION_KINDS
    from chrono_core.workspace.resolver import resolve_project

    normalized = content.strip()
    if not normalized:
        return {"ok": False, "kind": kind, "error": "content must not be blank"}
    if kind not in MINABLE_OBSERVATION_KINDS:
        allowed = ", ".join(sorted(MINABLE_OBSERVATION_KINDS))
        return {
            "ok": False,
            "kind": kind,
            "error": f"invalid semantic observation kind '{kind}'; expected one of: {allowed}",
        }

    project = resolve_project(
        Path(cwd), workspace_root=Path(workspace_root or default_workspace_root())
    )
    store = open_store(db_path)
    with store.transaction():
        project_id = store.get_or_create_project(project)
        observation = store.record_observation(
            project_id,
            None,
            kind,
            normalized,
            source="direct",
        )
    return {
        "ok": True,
        "project_id": project_id,
        "recorded_count": 1,
        "observation": observation,
    }


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


def push_bug_to_github(
    db_path: str | None,
    bug_id: str,
    *,
    repo: str | None = None,
    dry_run: bool = False,
    runner: Any | None = None,
    gh_timeout: float | None = None,
) -> dict[str, Any]:
    """Push one local bug to one GitHub issue via the gh CLI (external mutation).

    SQLite stays authoritative: a successful create is linked before any
    optional close PATCH, so a failed close leaves a recoverable partial
    result and a retry updates the linked issue instead of recreating it.
    ``dry_run`` performs no network call and writes nothing. The subprocess
    *runner* is injectable for tests.
    """
    from chrono_core.integrations import github_issues as gh

    def failure(
        code: str, message: str, *, action: str | None = None, bug: dict | None = None
    ) -> dict[str, Any]:
        envelope: dict[str, Any] = {
            "ok": False,
            "bug_id": bug_id,
            "dry_run": bool(dry_run),
            "partial": False,
            "error": message,
            "code": code,
        }
        if action:
            envelope["action"] = action
        if bug is not None and bug.get("remote_url"):
            envelope["remote_url"] = bug["remote_url"]
            envelope["remote_issue_id"] = bug.get("remote_issue_id")
        return envelope

    # A dry-run must be side-effect free, including when the configured
    # database has not yet been initialized. Use a read-only connection rather
    # than ``open_store``, whose normal path initializes schema and caches a
    # writable handle.
    if dry_run:
        resolved_db = Path(db_path or default_db_path()).expanduser()
        if not resolved_db.is_file():
            return failure("database_not_found", f"database not found: {resolved_db}")
        store = Store(resolved_db, read_only=True)
    else:
        store = open_store(db_path)
    bug = store.get_bug(bug_id)
    if bug is None:
        return failure("bug_not_found", f"unknown bug: {bug_id}")

    project_path = (
        store.get_project_path(bug["project_id"]) if bug.get("project_id") else None
    )
    runner = runner if runner is not None else gh.subprocess_runner
    timeout = gh_timeout if gh_timeout is not None else gh.GH_TIMEOUT_SECONDS

    # Git-origin discovery is itself a subprocess. Preserve the dry-run
    # no-runner contract by requiring the destination explicitly for an
    # unlinked project bug; linked bugs already carry their repository.
    if dry_run and not repo and not bug.get("remote_url"):
        return failure(
            "repo_required",
            "dry-run cannot inspect git origin; pass --repo [HOST/]OWNER/REPO",
            bug=bug,
        )

    try:
        repository, issue_number = gh.resolve_push_target(
            bug, explicit_repo=repo, project_path=project_path, runner=runner
        )
    except (gh.GitHubPushError, ValueError) as exc:
        code = getattr(exc, "code", "invalid_repo")
        return failure(code, str(exc))

    if dry_run:
        plan = gh.build_push_plan(bug, repository, issue_number)
        plan["gh_timeout_seconds"] = timeout
        return plan

    if issue_number is not None:
        try:
            response = gh.update_issue(
                bug, repository, issue_number, runner=runner, timeout=timeout
            )
        except (gh.GitHubPushError, ValueError) as exc:
            code = getattr(exc, "code", "command_failed")
            envelope = failure(
                code, str(exc), action="update", bug=bug
            )
            return envelope
        return {
            "ok": True,
            "bug_id": bug_id,
            "action": "update",
            "repository": repository.slug,
            "dry_run": False,
            "remote_url": response["html_url"],
            "remote_issue_id": str(response["number"]),
            "state": response.get("state"),
            "partial": False,
        }

    try:
        response = gh.create_issue(bug, repository, runner=runner, timeout=timeout)
    except (gh.GitHubPushError, ValueError) as exc:
        code = getattr(exc, "code", "command_failed")
        return failure(code, str(exc), action="create")

    remote_url = response["html_url"]
    remote_number = str(response["number"])
    link = store.link_bug_remote(
        bug_id, remote_url=remote_url, remote_issue_id=remote_number
    )
    if not link.get("ok"):
        return failure(
            "bug_not_found",
            "issue was created, but the local bug disappeared before linking; "
            "the remote issue is unmanaged: " + remote_url,
            action="create",
        )

    try:
        target_state, state_reason = gh.lifecycle_state(str(bug.get("status") or "open"))
        final_state: str = target_state
        final_url = remote_url
        if target_state == "closed":
            closed = gh.set_issue_state(
                repository,
                response["number"],
                str(bug.get("status") or "open"),
                runner=runner,
                timeout=timeout,
            )
            final_state = closed.get("state") or target_state
            final_url = closed.get("html_url") or remote_url
    except (gh.GitHubPushError, ValueError) as exc:
        code = getattr(exc, "code", "command_failed")
        return {
            "ok": False,
            "partial": True,
            "bug_id": bug_id,
            "action": "create",
            "repository": repository.slug,
            "dry_run": False,
            "remote_url": remote_url,
            "remote_issue_id": remote_number,
            "state": "open",
            "error": "issue created and linked, but the state change failed; "
            f"a retry will update the linked issue: {exc}",
            "code": code,
        }
    return {
        "ok": True,
        "bug_id": bug_id,
        "action": "create",
        "repository": repository.slug,
        "dry_run": False,
        "remote_url": final_url,
        "remote_issue_id": remote_number,
        "state": final_state,
        "partial": False,
    }


def search_observations_safe(
    db_path: str | None, query: str, *, project_id: str | None = None, limit: int = 20
) -> dict[str, Any]:
    """Full-text search over observations and bugs; malformed FTS queries are
    reported structurally."""
    store = open_store(db_path, read_only=True)
    try:
        results = store.search_observations(
            query, project_id=project_id, limit=max(limit, 0)
        )
        bugs = store.search_bugs(query, limit=max(limit, 0))
    except sqlite3.OperationalError as exc:
        return {
            "ok": False,
            "query": query,
            "error": f"invalid query: {exc}",
            "results": [],
            "bugs": [],
            "bug_count": 0,
        }
    finally:
        store.close()
    return {
        "ok": True,
        "query": query,
        "count": len(results),
        "results": results,
        "bugs": bugs,
        "bug_count": len(bugs),
    }


def find_similar_projects(
    db_path: str | None,
    cwd: str,
    *,
    workspace_root: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Rank other registered projects against the project at *cwd* (read-only).

    The project is resolved from *cwd* within *workspace_root* and must already
    be registered in the continuity database; an unknown project is reported
    structurally and never registered as a side effect.
    """
    resolved = Path(db_path or default_db_path()).expanduser()
    if not resolved.is_file():
        return {
            "ok": False,
            "error": "database not found",
            "db_path": str(resolved),
            "count": 0,
            "results": [],
        }
    from chrono_core.workspace.resolver import resolve_project

    project = resolve_project(
        Path(cwd), workspace_root=Path(workspace_root or default_workspace_root())
    )
    store = Store(resolved, read_only=True)
    try:
        project_id = store.find_project_id_by_path(project.path)
        if project_id is None:
            return {
                "ok": False,
                "error": f"unknown project: {project.path} is not registered",
                "project_path": project.path,
                "count": 0,
                "results": [],
            }
        results = store.find_similar_projects(project_id, limit=limit)
    finally:
        store.close()
    return {
        "ok": True,
        "project_id": project_id,
        "count": len(results),
        "results": results,
    }


def run_doctor(db_path: str | None = None) -> dict[str, Any]:
    """Audit an existing database without creating or mutating it."""
    from chrono_core.management.doctor import audit_store

    resolved = Path(db_path or default_db_path()).expanduser()
    if not resolved.is_file():
        return {
            "ok": False,
            "error": "database not found",
            "db_path": str(resolved),
            "checks": {},
            "summary": {"pass": 0, "warn": 0, "fail": 1},
        }
    store = Store(resolved, read_only=True)
    try:
        result = audit_store(store)
    except sqlite3.DatabaseError as exc:
        return {
            "ok": False,
            "error": "database unreadable",
            "detail": str(exc),
            "db_path": str(resolved),
            "checks": {},
            "summary": {"pass": 0, "warn": 0, "fail": 1},
        }
    finally:
        store.close()
    result["db_path"] = str(resolved)
    return result
