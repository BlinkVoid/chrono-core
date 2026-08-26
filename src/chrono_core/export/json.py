from __future__ import annotations

import json
import sys
from argparse import Namespace
from datetime import UTC, datetime
from typing import Any

from chrono_core import services
from chrono_core.export.common import load_project_row, resolve_export_project
from chrono_core.store.store import Store, utc_now

RECORD_TYPES = ("decisions", "blockers", "next_actions")

# Terminal statuses hidden from exports unless include_closed is set.
_CLOSED_STATUSES = {
    "blockers": frozenset({"resolved", "cancelled"}),
    "next_actions": frozenset({"done", "cancelled", "superseded"}),
}

_RECORD_FIELDS = {
    "decisions": ("id", "title", "rationale", "status", "created_at", "session_id"),
    "blockers": ("id", "title", "status", "detail", "created_at"),
    "next_actions": ("id", "text", "status", "priority", "created_at"),
}


def parse_since(value: str) -> datetime:
    """Parse an ISO 8601 watermark; naive values are treated as UTC."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(
            f"invalid --since timestamp {value!r}; expected ISO 8601"
            " (e.g. 2026-08-26T09:00:00+00:00)"
        ) from None
    return _as_utc(parsed)


def _as_utc(parsed: datetime) -> datetime:
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_created_at(raw: str) -> datetime:
    text = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return _as_utc(parsed)


def _fetch_records(
    store: Store,
    project_id: str,
    record_type: str,
    *,
    watermark: datetime | None,
    include_closed: bool,
) -> list[dict[str, Any]]:
    rows = store._connect().execute(
        f"SELECT * FROM {record_type} WHERE project_id = ?", (project_id,)
    ).fetchall()
    fields = _RECORD_FIELDS[record_type]
    closed = _CLOSED_STATUSES.get(record_type, frozenset())
    records: list[dict[str, Any]] = []
    for row in rows:
        created_at = _parse_created_at(row["created_at"])
        if watermark is not None and created_at < watermark:
            continue
        if not include_closed and row["status"] in closed:
            continue
        records.append({field: row[field] for field in fields})
    records.sort(key=lambda record: (record["created_at"], record["id"]))
    return records


def export_records_json(
    store: Store,
    project_id: str,
    *,
    since: str | None = None,
    include_closed: bool = False,
    record_types: list[str] | tuple[str, ...] | None = None,
    fallback_project: Any = None,
) -> dict[str, Any]:
    """Build a read-only JSON export of a project's records.

    ``fallback_project`` (a resolved project) supplies name/path metadata for
    a never-registered ``--cwd`` project, yielding empty arrays like ``resume``
    does instead of failing. Raises ValueError on an unknown explicit project
    id, malformed ``since``, or unknown record types.
    """
    project_row = load_project_row(store, project_id)
    if project_row is None:
        if fallback_project is None:
            raise ValueError(f"unknown project id: {project_id}")
        project_name = fallback_project.name
        project_path = fallback_project.path
    else:
        project_id = project_row["id"]
        project_name = project_row["name"]
        project_path = project_row["path"]

    selected = tuple(RECORD_TYPES) if record_types is None else tuple(record_types)
    unknown = [rtype for rtype in selected if rtype not in RECORD_TYPES]
    if unknown:
        raise ValueError(
            f"unknown record type(s) {unknown}; expected one of {list(RECORD_TYPES)}"
        )

    watermark = parse_since(since) if since is not None else None

    payload: dict[str, Any] = {
        "project_id": project_id,
        "project_name": project_name,
        "project_path": project_path,
        "exported_at": utc_now(),
        "filters": {"since": since, "include_closed": include_closed},
    }
    for record_type in selected:
        payload[record_type] = _fetch_records(
            store,
            project_id,
            record_type,
            watermark=watermark,
            include_closed=include_closed,
        )
    return payload


def export_json_command(args: Namespace) -> int:
    """CLI entry point for ``chrono export json``."""
    store = services.open_store(args.db_path)
    try:
        project_id, fallback = resolve_export_project(store, args)
        payload = export_records_json(
            store,
            project_id,
            since=getattr(args, "since", None),
            include_closed=getattr(args, "include_closed", False),
            record_types=getattr(args, "type", None),
            fallback_project=fallback,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2))
    return 0
