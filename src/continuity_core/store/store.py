from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from continuity_core.domain.models import GitState, HandoffPayload, ResumeContext
from continuity_core.store.schema import DDL, SCHEMA_VERSION
from continuity_core.workspace.resolver import ResolvedProject


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def make_session_id() -> str:
    return f"sess_{uuid.uuid4().hex}"


def make_entity_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Store:
    """SQLite-backed persistence for Continuity Core."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def init_schema(self) -> None:
        conn = self._connect()
        conn.executescript(DDL)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, utc_now()),
        )
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def get_or_create_project(self, project: ResolvedProject) -> str:
        return self.upsert_project(
            project_id=project.project_id,
            name=project.name,
            path=project.path,
            relative_path=project.relative_path,
        )

    def upsert_project(
        self,
        project_id: str,
        name: str,
        path: str,
        relative_path: str,
        phase: str | None = None,
        summary: str | None = None,
    ) -> str:
        conn = self._connect()
        now = utc_now()
        conn.execute(
            """
            INSERT INTO projects (
                id, name, path, relative_path, status, phase, summary, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                path=excluded.path,
                relative_path=excluded.relative_path,
                phase=COALESCE(excluded.phase, phase),
                summary=COALESCE(excluded.summary, summary),
                updated_at=excluded.updated_at
            """,
            (
                project_id,
                name,
                path,
                relative_path,
                "active",
                phase,
                summary,
                now,
                now,
            ),
        )
        conn.commit()
        return project_id

    def create_session(
        self,
        project_id: str,
        payload: HandoffPayload,
        git_state: GitState,
        agent_name: str | None = None,
    ) -> str:
        conn = self._connect()
        session_id = make_session_id()
        now = utc_now()
        conn.execute(
            """
            INSERT INTO sessions
                (
                    id, project_id, ended_at, agent_name, summary, git_branch, git_head,
                    git_dirty, raw_payload_json
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                project_id,
                now,
                agent_name,
                payload.summary,
                git_state.branch,
                git_state.head,
                int(git_state.dirty),
                json.dumps(payload.to_dict()),
            ),
        )
        conn.commit()
        return session_id

    def record_decisions(
        self, project_id: str, session_id: str | None, decisions: list[dict[str, Any]]
    ) -> None:
        if not decisions:
            return
        conn = self._connect()
        now = utc_now()
        for decision in decisions:
            conn.execute(
                """
                INSERT INTO decisions (id, project_id, session_id, title, rationale, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    make_entity_id("dec"),
                    project_id,
                    session_id,
                    decision.get("title", ""),
                    decision.get("rationale", ""),
                    now,
                ),
            )
        conn.commit()

    def record_blockers(
        self, project_id: str, session_id: str | None, blockers: list[dict[str, Any]]
    ) -> None:
        if not blockers:
            return
        conn = self._connect()
        now = utc_now()
        for blocker in blockers:
            conn.execute(
                """
                INSERT INTO blockers (id, project_id, session_id, title, status, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    make_entity_id("blk"),
                    project_id,
                    session_id,
                    blocker.get("title", ""),
                    blocker.get("status", "open"),
                    blocker.get("detail", ""),
                    now,
                ),
            )
        conn.commit()

    def record_next_actions(
        self, project_id: str, session_id: str | None, actions: list[str]
    ) -> None:
        if not actions:
            return
        conn = self._connect()
        now = utc_now()
        for action in actions:
            conn.execute(
                """
                INSERT INTO next_actions (id, project_id, session_id, text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (make_entity_id("act"), project_id, session_id, action, now),
            )
        conn.commit()

    def record_observations(
        self,
        project_id: str,
        session_id: str | None,
        kind: str,
        items: list[str],
        source: str = "handoff",
    ) -> None:
        if not items:
            return
        conn = self._connect()
        now = utc_now()
        for item in items:
            conn.execute(
                """
                INSERT INTO observations (
                    id, project_id, session_id, kind, content, source, observed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    make_entity_id("obs"),
                    project_id,
                    session_id,
                    kind,
                    item,
                    source,
                    now,
                ),
            )
        conn.commit()

    def list_projects(self) -> list[dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT id, name, path, relative_path, status, phase, summary, updated_at
            FROM projects
            ORDER BY relative_path
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def update_project_state(
        self, project_id: str, *, phase: str | None = None, summary: str | None = None
    ) -> None:
        conn = self._connect()
        conn.execute(
            """
            UPDATE projects
            SET
                phase = COALESCE(?, phase),
                summary = COALESCE(?, summary),
                updated_at = ?
            WHERE id = ?
            """,
            (phase, summary, utc_now(), project_id),
        )
        conn.commit()

    def get_resume_context(self, project_id: str) -> ResumeContext:
        conn = self._connect()
        project_row = conn.execute(
            "SELECT id, name, path, summary FROM projects WHERE id = ?", (project_id,)
        ).fetchone()

        if project_row is None:
            return ResumeContext(
                project_id=project_id,
                project_name="unknown",
                project_path="",
                current_status="No project found in continuity database.",
            )

        session_row = conn.execute(
            """
            SELECT summary, git_branch, git_head, git_dirty
            FROM sessions
            WHERE project_id = ?
            ORDER BY ended_at DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()

        blockers = conn.execute(
            """
            SELECT id, title, status, detail
            FROM blockers
            WHERE project_id = ? AND status = 'open'
            ORDER BY created_at DESC
            """,
            (project_id,),
        ).fetchall()

        actions = conn.execute(
            """
            SELECT id, text, status, priority
            FROM next_actions
            WHERE project_id = ? AND status = 'open'
            ORDER BY created_at DESC
            """,
            (project_id,),
        ).fetchall()

        decisions = conn.execute(
            """
            SELECT id, title, rationale, status
            FROM decisions
            WHERE project_id = ?
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (project_id,),
        ).fetchall()

        current_status = ""
        summary = ""
        if session_row:
            summary = session_row["summary"] or ""
            dirty_flag = bool(session_row["git_dirty"])
            dirty_text = " (dirty)" if dirty_flag else ""
            branch = session_row["git_branch"] or "unknown"
            current_status = f"Latest session on {branch}{dirty_text}."
        else:
            current_status = "No sessions captured yet."

        return ResumeContext(
            project_id=project_id,
            project_name=project_row["name"],
            project_path=project_row["path"],
            current_status=current_status,
            summary=summary,
            active_blockers=[dict(row) for row in blockers],
            next_actions=[dict(row) for row in actions],
            recent_decisions=[dict(row) for row in decisions],
        )
