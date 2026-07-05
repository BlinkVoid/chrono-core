from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

from continuity_core.capture.git import read_git_state
from continuity_core.config import default_db_path, default_workspace_root
from continuity_core.domain.models import GitState, HandoffPayload
from continuity_core.store.store import Store
from continuity_core.workspace.resolver import ResolvedProject


def _parse_cli_value(value: str) -> dict[str, Any]:
    """Parse a CLI argument as JSON or return a simple text dict."""
    value = value.strip()
    if value.startswith("{") and value.endswith("}"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    return {"title": value}


def build_handoff_payload(args: Namespace) -> HandoffPayload:
    """Build a HandoffPayload from argparse args or a JSON payload."""
    if getattr(args, "json", None):
        source = args.json
        if source == "-":
            data = json.load(sys.stdin)
        else:
            with Path(source).open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        return HandoffPayload(
            summary=data.get("summary", ""),
            files_changed=list(data.get("files_changed", [])),
            tests=list(data.get("tests", [])),
            decisions=list(data.get("decisions", [])),
            blockers=list(data.get("blockers", [])),
            next_actions=list(data.get("next_actions", [])),
            risks=list(data.get("risks", [])),
        )

    return HandoffPayload(
        summary=getattr(args, "summary", "") or "",
        files_changed=list(getattr(args, "files_changed", []) or []),
        tests=list(getattr(args, "tests", []) or []),
        decisions=[_parse_cli_value(d) for d in (getattr(args, "decisions", []) or [])],
        blockers=[_parse_cli_value(b) for b in (getattr(args, "blockers", []) or [])],
        next_actions=list(getattr(args, "next_actions", []) or []),
        risks=list(getattr(args, "risks", []) or []),
    )


def persist_handoff(
    store: Store,
    project: ResolvedProject,
    payload: HandoffPayload,
    git_state: GitState | None = None,
    agent_name: str | None = None,
) -> dict[str, Any]:
    """Persist a handoff payload and return a result summary."""
    store.init_schema()
    git = git_state or GitState()
    with store.transaction():
        project_id = store.get_or_create_project(project)
        session_id = store.create_session(project_id, payload, git, agent_name=agent_name)

        store.record_decisions(project_id, session_id, payload.decisions)
        store.record_blockers(project_id, session_id, payload.blockers)
        store.record_next_actions(project_id, session_id, payload.next_actions)
        store.record_observations(project_id, session_id, "file", payload.files_changed)
        store.record_observations(project_id, session_id, "test", payload.tests)
        store.record_observations(project_id, session_id, "risk", payload.risks)

    open_blockers = [b for b in payload.blockers if b.get("status") == "open"]
    resume_hint = payload.summary
    if open_blockers:
        titles = ", ".join(b.get("title", "") for b in open_blockers)
        resume_hint = f"{payload.summary} Blocked on: {titles}."

    return {
        "ok": True,
        "project_id": project_id,
        "session_id": session_id,
        "resume_hint": resume_hint,
    }


def capture_handoff(args: Namespace) -> dict[str, Any]:
    """Resolve project, build payload, and persist from CLI args."""
    from continuity_core.workspace.resolver import resolve_project

    project_path = Path(getattr(args, "cwd", "."))
    workspace_root = Path(getattr(args, "workspace_root", None) or default_workspace_root())
    project = resolve_project(project_path, workspace_root=workspace_root)
    payload = build_handoff_payload(args)
    git_state = read_git_state(Path(project.path))

    db_path = getattr(args, "db_path", None) or _default_db_path()
    store = Store(db_path)
    return persist_handoff(store, project, payload, git_state)


def _default_db_path() -> str:
    return default_db_path()
