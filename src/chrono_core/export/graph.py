from __future__ import annotations

import json
import sys
from argparse import Namespace
from typing import Any

from chrono_core import services
from chrono_core.export.common import load_project_row, resolve_export_project
from chrono_core.store.store import Store, utc_now

# (node type, table, label column) for the three sync-target record types.
_RECORD_SOURCES = (
    ("decision", "decisions", "title"),
    ("blocker", "blockers", "title"),
    ("next_action", "next_actions", "text"),
)


def build_record_graph(store: Store, project_id: str) -> dict[str, Any]:
    """Build a derived {nodes, edges} graph for a project's records.

    Read-only and status-blind. Session co-occurrence is represented through
    session hub nodes only; supersession links old actions to their successors.
    Raises ValueError on an unknown project id.
    """
    project = load_project_row(store, project_id)
    if project is None:
        raise ValueError(f"unknown project id: {project_id}")

    conn = store._connect()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    hub_ids: set[str] = set()

    for node_type, table, label_field in _RECORD_SOURCES:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE project_id = ?", (project_id,)
        ).fetchall()
        for row in rows:
            nodes.append(
                {
                    "id": row["id"],
                    "type": node_type,
                    "label": row[label_field],
                    "status": row["status"],
                    "created_at": row["created_at"],
                }
            )
            if row["session_id"]:
                hub_ids.add(row["session_id"])
                edges.append(
                    {
                        "source": row["id"],
                        "target": row["session_id"],
                        "relation": "captured_in",
                    }
                )
            if node_type == "next_action" and row["supersedes_id"]:
                edges.append(
                    {
                        "source": row["supersedes_id"],
                        "target": row["id"],
                        "relation": "superseded_by",
                    }
                )

    for session_id in sorted(hub_ids):
        row = conn.execute(
            "SELECT id, summary, ended_at FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            continue
        nodes.append(
            {
                "id": row["id"],
                "type": "session",
                "label": row["summary"] or "",
                "status": "ended",
                "created_at": row["ended_at"],
            }
        )

    nodes.sort(key=lambda n: (n["type"], n["created_at"], n["id"]))
    edges.sort(key=lambda e: (e["source"], e["relation"], e["target"]))
    return {"nodes": nodes, "edges": edges}


def export_graph_command(args: Namespace) -> int:
    """CLI entry point for ``chrono export graph``."""
    store = services.open_store(args.db_path)
    try:
        project_id, fallback = resolve_export_project(store, args)
        registered = load_project_row(store, project_id) is not None
        if not registered and fallback is None:
            raise ValueError(f"unknown project id: {project_id}")
        graph = build_record_graph(store, project_id) if registered else {
            "nodes": [],
            "edges": [],
        }
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    project = load_project_row(store, project_id)
    payload = {
        "project_id": project_id,
        "project_name": project["name"] if project else fallback.name,
        "project_path": project["path"] if project else fallback.path,
        "exported_at": utc_now(),
        "filters": {},
        **graph,
    }
    print(json.dumps(payload, indent=2))
    return 0
