"""Read-only database health diagnostics."""
from __future__ import annotations

import json
from typing import Any

from chrono_core.store.store import Store

LEGACY_PROJECT_IDS = frozenset({"-cdb4ee2aea", "workspace-root-a3ada80145"})
SEMANTIC_OBSERVATION_KINDS = ("lesson", "pattern", "pattern_candidate")


def _check(
    status: str, findings: list[dict[str, Any]], message: str
) -> dict[str, Any]:
    return {
        "status": status,
        "count": len(findings),
        "message": message,
        "findings": findings,
    }


def _project_identity_findings(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT relative_path, COUNT(*) AS project_count,
               group_concat(id, ' | ') AS project_ids,
               group_concat(path, ' | ') AS paths
        FROM projects
        WHERE relative_path NOT IN ('', '.')
        GROUP BY relative_path
        HAVING COUNT(*) > 1
        ORDER BY relative_path
        """
    ).fetchall()
    return [
        {"type": "ambiguous_relative_path", **dict(row)}
        for row in rows
    ]


def _ownership_findings(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT 'decisions' AS table_name, c.id, c.project_id, c.session_id,
               s.project_id AS session_project_id
        FROM decisions c JOIN sessions s ON s.id = c.session_id
        WHERE c.project_id <> s.project_id
        UNION ALL
        SELECT 'blockers', c.id, c.project_id, c.session_id, s.project_id
        FROM blockers c JOIN sessions s ON s.id = c.session_id
        WHERE c.project_id <> s.project_id
        UNION ALL
        SELECT 'next_actions', c.id, c.project_id, c.session_id, s.project_id
        FROM next_actions c JOIN sessions s ON s.id = c.session_id
        WHERE c.project_id <> s.project_id
        UNION ALL
        SELECT 'observations', c.id, c.project_id, c.session_id, s.project_id
        FROM observations c JOIN sessions s ON s.id = c.session_id
        WHERE c.project_id <> s.project_id
        UNION ALL
        SELECT 'bugs.found_in_session_id', c.id, c.project_id,
               c.found_in_session_id, s.project_id
        FROM bugs c JOIN sessions s ON s.id = c.found_in_session_id
        WHERE c.project_id IS NOT NULL AND c.project_id <> s.project_id
        UNION ALL
        SELECT 'bugs.fixed_in_session_id', c.id, c.project_id,
               c.fixed_in_session_id, s.project_id
        FROM bugs c JOIN sessions s ON s.id = c.fixed_in_session_id
        WHERE c.project_id IS NOT NULL AND c.project_id <> s.project_id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _legacy_bucket(conn) -> tuple[list[dict[str, Any]], int]:
    projects = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, name, path, relative_path FROM projects
            WHERE id IN (?, ?) OR name = 'legacy-unresolved-bucket'
            """,
            tuple(sorted(LEGACY_PROJECT_IDS)),
        ).fetchall()
    ]
    record_count = 0
    for project in projects:
        project_id = project["id"]
        counts: dict[str, int] = {}
        for table in (
            "sessions",
            "decisions",
            "blockers",
            "next_actions",
            "documents",
            "observations",
            "bugs",
        ):
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE project_id = ?", (project_id,)
            ).fetchone()[0]
            if count:
                counts[table] = count
                record_count += count
        project["record_counts"] = counts
    return projects, record_count


def _unsafe_mined_patterns(conn) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for row in conn.execute(
        "SELECT id, title, projects_json FROM patterns WHERE source = 'mined'"
    ).fetchall():
        reasons: list[str] = []
        title = row["title"]
        prefix = "Recurring pattern: "
        phrase = title[len(prefix) :].strip() if title.startswith(prefix) else ""
        if len(phrase.split()) < 2:
            reasons.append("title is not a multiword recurring pattern")
        try:
            project_ids = json.loads(row["projects_json"])
        except (TypeError, ValueError):
            project_ids = None
        if not isinstance(project_ids, list) or not project_ids:
            reasons.append("projects_json is not a nonempty array")
        else:
            for project_id in project_ids:
                project = conn.execute(
                    "SELECT id, name FROM projects WHERE id = ?", (project_id,)
                ).fetchone()
                if project is None:
                    reasons.append(f"unknown project: {project_id}")
                    continue
                if (
                    project_id in LEGACY_PROJECT_IDS
                    or project["name"] == "legacy-unresolved-bucket"
                ):
                    reasons.append(f"legacy project: {project_id}")
                semantic_count = conn.execute(
                    """
                    SELECT COUNT(*) FROM observations
                    WHERE project_id = ? AND kind IN (?, ?, ?)
                    """,
                    (project_id, *SEMANTIC_OBSERVATION_KINDS),
                ).fetchone()[0]
                if semantic_count == 0:
                    reasons.append(f"no semantic evidence: {project_id}")
        if reasons:
            findings.append({"id": row["id"], "title": title, "reasons": reasons})
    return findings


def audit_store(store: Store) -> dict[str, Any]:
    """Run deterministic read-only checks against an initialized Store."""
    conn = store._connect()
    integrity_rows = [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]
    integrity_findings = (
        [] if integrity_rows == ["ok"] else [{"result": value} for value in integrity_rows]
    )
    foreign_key_findings = [
        {"table": row[0], "rowid": row[1], "parent": row[2], "fkid": row[3]}
        for row in conn.execute("PRAGMA foreign_key_check").fetchall()
    ]
    identity_findings = _project_identity_findings(conn)
    ownership_findings = _ownership_findings(conn)
    legacy_projects, legacy_records = _legacy_bucket(conn)
    unsafe_patterns = _unsafe_mined_patterns(conn)

    legacy_status = "pass"
    if legacy_projects:
        legacy_status = "fail" if legacy_records else "warn"
    legacy_check = _check(
        legacy_status,
        legacy_projects,
        (
            "No legacy collision bucket exists."
            if not legacy_projects
            else f"Legacy bucket contains {legacy_records} record(s)."
            if legacy_records
            else "Legacy bucket is empty and can be removed after review."
        ),
    )
    legacy_check["count"] = legacy_records
    checks = {
        "integrity": _check(
            "pass" if not integrity_findings else "fail",
            integrity_findings,
            "SQLite integrity is clean." if not integrity_findings else "SQLite integrity failed.",
        ),
        "foreign_keys": _check(
            "pass" if not foreign_key_findings else "fail",
            foreign_key_findings,
            "Foreign keys are clean."
            if not foreign_key_findings
            else "Foreign key violations found.",
        ),
        "project_identity": _check(
            "pass" if not identity_findings else "warn",
            identity_findings,
            "Project identities are unique."
            if not identity_findings
            else "Relative paths are reused across workspace roots; review if unexpected.",
        ),
        "session_ownership": _check(
            "pass" if not ownership_findings else "fail",
            ownership_findings,
            "Session ownership is consistent."
            if not ownership_findings
            else "Cross-project session ownership found.",
        ),
        "legacy_bucket": legacy_check,
        "unsafe_mined_patterns": _check(
            "pass" if not unsafe_patterns else "fail",
            unsafe_patterns,
            "Mined-pattern provenance is safe."
            if not unsafe_patterns
            else "Unsafe mined patterns found.",
        ),
    }
    summary = {
        status: sum(1 for check in checks.values() if check["status"] == status)
        for status in ("pass", "warn", "fail")
    }
    return {"ok": summary["fail"] == 0, "checks": checks, "summary": summary}
