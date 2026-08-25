from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chrono_core.domain.models import GitState, HandoffPayload, ResumeContext
from chrono_core.store.schema import DDL, SCHEMA_VERSION
from chrono_core.workspace.resolver import ResolvedProject


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def make_session_id() -> str:
    return f"sess_{uuid.uuid4().hex}"


def make_entity_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Store:
    """SQLite-backed persistence for Chrono Core."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._tx_depth = 0

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
        return self._conn

    def _commit(self) -> None:
        """Commit unless inside an explicit transaction() block."""
        if self._tx_depth == 0 and self._conn is not None:
            self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group store calls into one atomic commit (nesting joins the outer block)."""
        conn = self._connect()
        self._tx_depth += 1
        try:
            yield
        except BaseException:
            self._tx_depth -= 1
            if self._tx_depth == 0:
                conn.rollback()
            raise
        else:
            self._tx_depth -= 1
            if self._tx_depth == 0:
                conn.commit()

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
        applied = {
            row["version"] for row in conn.execute("SELECT version FROM schema_migrations")
        }
        if SCHEMA_VERSION >= 2 and 2 not in applied:
            # Version 2 added FTS sync triggers; reindex rows written before them.
            conn.execute("INSERT INTO observation_fts (observation_fts) VALUES ('rebuild')")

        from chrono_core.store.migrations import apply_pending

        apply_pending(conn)
        self._commit()

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

    def find_project_id_by_path(self, path: str) -> str | None:
        """Return the id already registered for *path*, or None."""
        conn = self._connect()
        row = conn.execute("SELECT id FROM projects WHERE path = ?", (path,)).fetchone()
        return row["id"] if row else None

    def resolve_project_id(self, project: ResolvedProject) -> str:
        """Canonical id for *project*, without creating a row.

        The read-only counterpart to get_or_create_project. A project's
        computed id hashes its workspace-*relative* path, so the same
        directory resolves to different ids under different workspace
        roots. The absolute path is the stable identity, so readers must
        prefer an id already registered for that path — otherwise records
        captured under one root are invisible from another.
        """
        return self.find_project_id_by_path(project.path) or project.project_id

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
            ON CONFLICT(path) DO UPDATE SET
                name=excluded.name,
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
        self._commit()
        # The same path may already be registered under a different id (e.g.
        # resolved under another workspace root); that row's id stays canonical.
        return self.find_project_id_by_path(path) or project_id

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
        self._commit()
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
        self._commit()

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
        self._commit()

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
        self._commit()

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
        self._commit()

    def resolve_blocker(self, blocker_id: str) -> bool:
        conn = self._connect()
        cursor = conn.execute(
            "UPDATE blockers SET status = 'resolved', resolved_at = ? WHERE id = ?",
            (utc_now(), blocker_id),
        )
        self._commit()
        return cursor.rowcount > 0

    def complete_next_action(self, action_id: str) -> bool:
        conn = self._connect()
        cursor = conn.execute(
            "UPDATE next_actions SET status = 'done', completed_at = ? WHERE id = ?",
            (utc_now(), action_id),
        )
        self._commit()
        return cursor.rowcount > 0

    @staticmethod
    def _append_history(current_json: str | None, entry: dict[str, Any]) -> str:
        try:
            history = json.loads(current_json or "[]")
        except ValueError:
            history = []
        history.append(entry)
        return json.dumps(history, ensure_ascii=False)

    def _load_entity(self, table: str, entity_id: str) -> sqlite3.Row | None:
        return (
            self._connect()
            .execute(f"SELECT * FROM {table} WHERE id = ?", (entity_id,))
            .fetchone()
        )

    def cancel_next_action(self, action_id: str, reason: str | None = None) -> dict[str, Any]:
        row = self._load_entity("next_actions", action_id)
        if row is None:
            return {"ok": False, "action_id": action_id, "status": "not_found"}
        if row["status"] == "cancelled":
            return {"ok": True, "already": True, "action_id": action_id, "status": "cancelled"}
        now = utc_now()
        conn = self._connect()
        conn.execute(
            """
            UPDATE next_actions
            SET status = 'cancelled', cancelled_at = ?, raw_history_json = ?
            WHERE id = ?
            """,
            (
                now,
                self._append_history(
                    row["raw_history_json"],
                    {"op": "cancel", "at": now, "reason": reason or ""},
                ),
                action_id,
            ),
        )
        self._commit()
        return {"ok": True, "already": False, "action_id": action_id, "status": "cancelled"}

    def reopen_next_action(self, action_id: str) -> dict[str, Any]:
        row = self._load_entity("next_actions", action_id)
        if row is None:
            return {"ok": False, "action_id": action_id, "status": "not_found"}
        if row["status"] == "open":
            return {"ok": True, "already": True, "action_id": action_id, "status": "open"}
        conn = self._connect()
        conn.execute(
            """
            UPDATE next_actions
            SET status = 'open', completed_at = NULL, cancelled_at = NULL,
                raw_history_json = ?
            WHERE id = ?
            """,
            (
                self._append_history(
                    row["raw_history_json"], {"op": "reopen", "at": utc_now()}
                ),
                action_id,
            ),
        )
        self._commit()
        return {"ok": True, "already": False, "action_id": action_id, "status": "open"}

    def edit_next_action(self, action_id: str, new_text: str) -> dict[str, Any]:
        row = self._load_entity("next_actions", action_id)
        if row is None:
            return {"ok": False, "action_id": action_id, "status": "not_found"}
        now = utc_now()
        conn = self._connect()
        conn.execute(
            """
            UPDATE next_actions
            SET text = ?, raw_history_json = ?
            WHERE id = ?
            """,
            (
                new_text,
                self._append_history(
                    row["raw_history_json"],
                    {"op": "edit", "at": now, "previous_text": row["text"]},
                ),
                action_id,
            ),
        )
        self._commit()
        return {"ok": True, "already": False, "action_id": action_id, "status": row["status"]}

    def supersede_next_action(self, old_action_id: str, new_text: str) -> dict[str, Any]:
        old = self._load_entity("next_actions", old_action_id)
        if old is None:
            return {"ok": False, "action_id": old_action_id, "status": "not_found"}
        if old["status"] == "superseded":
            return {
                "ok": True,
                "already": True,
                "action_id": old_action_id,
                "status": "superseded",
                "new_action_id": None,
            }
        now = utc_now()
        new_id = make_entity_id("act")
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO next_actions
                (id, project_id, session_id, text, status, supersedes_id, created_at)
            VALUES (?, ?, ?, ?, 'open', ?, ?)
            """,
            (new_id, old["project_id"], old["session_id"], new_text, old_action_id, now),
        )
        conn.execute(
            """
            UPDATE next_actions
            SET status = 'superseded', raw_history_json = ?
            WHERE id = ?
            """,
            (
                self._append_history(
                    old["raw_history_json"],
                    {"op": "superseded_by", "at": now, "successor": new_id},
                ),
                old_action_id,
            ),
        )
        self._commit()
        return {
            "ok": True,
            "already": False,
            "action_id": old_action_id,
            "status": "superseded",
            "new_action_id": new_id,
        }

    def cancel_blocker(self, blocker_id: str, reason: str | None = None) -> dict[str, Any]:
        row = self._load_entity("blockers", blocker_id)
        if row is None:
            return {"ok": False, "blocker_id": blocker_id, "status": "not_found"}
        if row["status"] == "cancelled":
            return {
                "ok": True,
                "already": True,
                "blocker_id": blocker_id,
                "status": "cancelled",
            }
        conn = self._connect()
        conn.execute(
            "UPDATE blockers SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
            (utc_now(), blocker_id),
        )
        self._commit()
        return {"ok": True, "already": False, "blocker_id": blocker_id, "status": "cancelled"}

    def edit_blocker(self, blocker_id: str, new_title: str) -> dict[str, Any]:
        row = self._load_entity("blockers", blocker_id)
        if row is None:
            return {"ok": False, "blocker_id": blocker_id, "status": "not_found"}
        conn = self._connect()
        conn.execute("UPDATE blockers SET title = ? WHERE id = ?", (new_title, blocker_id))
        self._commit()
        return {"ok": True, "already": False, "blocker_id": blocker_id, "status": row["status"]}

    def reopen_blocker(self, blocker_id: str) -> dict[str, Any]:
        row = self._load_entity("blockers", blocker_id)
        if row is None:
            return {"ok": False, "blocker_id": blocker_id, "status": "not_found"}
        if row["status"] == "open":
            return {"ok": True, "already": True, "blocker_id": blocker_id, "status": "open"}
        conn = self._connect()
        conn.execute(
            "UPDATE blockers SET status = 'open', resolved_at = NULL, cancelled_at = NULL"
            " WHERE id = ?",
            (blocker_id,),
        )
        self._commit()
        return {"ok": True, "already": False, "blocker_id": blocker_id, "status": "open"}

    def search_observations(
        self, query: str, *, project_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        sql = """
            SELECT o.id, o.project_id, o.session_id, o.kind, o.content, o.source, o.observed_at
            FROM observation_fts f
            JOIN observations o ON o.rowid = f.rowid
            WHERE observation_fts MATCH ?
        """
        params: list[Any] = [query]
        if project_id is not None:
            sql += " AND o.project_id = ?"
            params.append(project_id)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        return [dict(row) for row in conn.execute(sql, params).fetchall()]

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
        self._commit()

    def get_resume_context(
        self,
        project_id: str,
        *,
        branch: str | None = None,
        include_all: bool = False,
        limit: int | None = 20,
    ) -> ResumeContext:
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

        scoped = include_all or branch is None
        branch_filter = "" if scoped else """
            AND (s.git_branch IS NULL OR s.git_branch = :branch)
        """
        hidden_filter = "1=1" if scoped else """
            s.git_branch IS NOT NULL AND s.git_branch != :branch
        """

        session_row = conn.execute(
            """
            SELECT summary, git_branch, git_head, git_dirty
            FROM sessions
            WHERE project_id = :pid
            ORDER BY ended_at DESC
            LIMIT 1
            """,
            {"pid": project_id},
        ).fetchone()

        blockers = conn.execute(
            f"""
            SELECT b.id, b.title, b.status, b.detail
            FROM blockers b
            LEFT JOIN sessions s ON s.id = b.session_id
            WHERE b.project_id = :pid AND b.status = 'open'
            {branch_filter}
            ORDER BY b.created_at DESC
            {'' if limit is None else 'LIMIT :limit'}
            """,
            {"pid": project_id, "branch": branch, "limit": limit},
        ).fetchall()

        actions = conn.execute(
            f"""
            SELECT na.id, na.text, na.status, na.priority
            FROM next_actions na
            LEFT JOIN sessions s ON s.id = na.session_id
            WHERE na.project_id = :pid AND na.status = 'open'
            {branch_filter}
            ORDER BY na.created_at DESC
            {'' if limit is None else 'LIMIT :limit'}
            """,
            {"pid": project_id, "branch": branch, "limit": limit},
        ).fetchall()

        if scoped:
            hidden_actions = 0
            hidden_blockers = 0
        else:
            hidden_blockers = conn.execute(
                f"""
                SELECT COUNT(*) AS n
                FROM blockers b
                LEFT JOIN sessions s ON s.id = b.session_id
                WHERE b.project_id = :pid AND b.status = 'open' AND {hidden_filter}
                """,
                {"pid": project_id, "branch": branch},
            ).fetchone()["n"]

            hidden_actions = conn.execute(
                f"""
                SELECT COUNT(*) AS n
                FROM next_actions na
                LEFT JOIN sessions s ON s.id = na.session_id
                WHERE na.project_id = :pid AND na.status = 'open' AND {hidden_filter}
                """,
                {"pid": project_id, "branch": branch},
            ).fetchone()["n"]

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
            branch_name = session_row["git_branch"] or "unknown"
            current_status = f"Latest session on {branch_name}{dirty_text}."
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
            branch=branch or "",
            hidden_actions=hidden_actions,
            hidden_blockers=hidden_blockers,
        )

    def report_bug(
        self,
        project_id: str | None,
        title: str,
        *,
        detail: str = "",
        severity: str = "medium",
        found_in_session_id: str | None = None,
    ) -> str:
        from chrono_core.domain.models import BUG_SEVERITIES

        if severity not in BUG_SEVERITIES:
            raise ValueError(
                f"invalid severity '{severity}'; expected one of {BUG_SEVERITIES}"
            )
        conn = self._connect()
        now = utc_now()
        bug_id = make_entity_id("bug")
        conn.execute(
            """
            INSERT INTO bugs (
                id, project_id, title, detail, severity, status,
                found_in_session_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (bug_id, project_id, title, detail, severity, found_in_session_id, now, now),
        )
        self._commit()
        return bug_id

    def list_bugs(
        self,
        *,
        status: str | None = "open",
        severity: str | None = None,
        project_id: str | None = None,
        include_workspace_wide: bool = True,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT b.*, COALESCE(p.name, '(workspace)') AS project_name
            FROM bugs b LEFT JOIN projects p ON p.id = b.project_id
            WHERE 1=1
        """
        params: list[Any] = []
        if status is not None:
            sql += " AND b.status = ?"
            params.append(status)
        if severity is not None:
            sql += " AND b.severity = ?"
            params.append(severity)
        if project_id is not None:
            sql += " AND b.project_id = ?"
            params.append(project_id)
        elif not include_workspace_wide:
            sql += " AND b.project_id IS NOT NULL"
        sql += " ORDER BY b.created_at DESC"
        return [dict(r) for r in self._connect().execute(sql, params).fetchall()]

    def get_bug(self, bug_id: str) -> dict[str, Any] | None:
        row = self._connect().execute(
            """
            SELECT b.*, COALESCE(p.name, '(workspace)') AS project_name
            FROM bugs b LEFT JOIN projects p ON p.id = b.project_id
            WHERE b.id = ?
            """,
            (bug_id,),
        ).fetchone()
        return dict(row) if row else None

    def update_bug(
        self,
        bug_id: str,
        *,
        status: str | None = None,
        severity: str | None = None,
        detail: str | None = None,
        fixed_in_session_id: str | None = None,
    ) -> dict[str, Any]:
        from chrono_core.domain.models import BUG_SEVERITIES, BUG_STATUSES

        if status is not None and status not in BUG_STATUSES:
            raise ValueError(f"invalid status '{status}'; expected one of {BUG_STATUSES}")
        if severity is not None and severity not in BUG_SEVERITIES:
            raise ValueError(f"invalid severity '{severity}'")
        current = self.get_bug(bug_id)
        if current is None:
            return {"ok": False, "bug_id": bug_id, "status": "not_found"}
        closed = {"fixed", "wont_fix", "cancelled"}
        # resolved_at is written directly (not COALESCE'd): an explicit status
        # transition stamps/clears it, while a field-only edit preserves the
        # current value.
        resolved_at = current["resolved_at"]
        if status is not None:
            resolved_at = utc_now() if status in closed else None
        self._connect().execute(
            """
            UPDATE bugs SET
                status = COALESCE(?, status),
                severity = COALESCE(?, severity),
                detail = COALESCE(?, detail),
                fixed_in_session_id = COALESCE(?, fixed_in_session_id),
                resolved_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, severity, detail, fixed_in_session_id, resolved_at, utc_now(), bug_id),
        )
        self._commit()
        return {"ok": True, "already": False, "bug_id": bug_id, "bug": self.get_bug(bug_id)}

    def search_bugs(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._connect().execute(
            """
            SELECT b.* FROM bug_fts f JOIN bugs b ON b.rowid = f.rowid
            WHERE bug_fts MATCH ? ORDER BY rank LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
