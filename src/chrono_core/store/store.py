from __future__ import annotations

import json
import math
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chrono_core.domain.models import (
    PROJECT_LIFECYCLE_PHASES,
    PROJECT_PRIORITIES,
    PROJECT_STATUSES,
    GitState,
    HandoffPayload,
    ResumeContext,
)
from chrono_core.store.schema import DDL, SCHEMA_VERSION
from chrono_core.textutil import salient_terms, tokenize
from chrono_core.workspace.resolver import ResolvedProject, make_project_id

_PATTERN_STATUS_RANK = {"candidate": 0, "validated": 1, "promoted": 2}

_PROJECT_COLUMNS = (
    "id, name, path, relative_path, status, phase, lifecycle_phase, summary, priority, tags,"
    " owner, description_usage, current_progress, notes, other_factors,"
    " created_at, updated_at"
)

_INVENTORY_COLUMNS = (
    "project_id, workspace_root, marker, depth, last_seen_at, missing_since,"
    " status_before_missing, last_error_json, is_git, branch, detached, head_sha,"
    " head_subject, remote_name, remote_url, default_branch, dirty, changed_count,"
    " untracked_count, collected_at"
)

_PROJECT_METADATA_FIELDS = {
    "status",
    "lifecycle_phase",
    "priority",
    "tags",
    "owner",
    "description_usage",
    "summary",
    "current_progress",
    "notes",
    "other_factors",
}


class AmbiguousProjectSelector(ValueError):
    """A relative-path selector matched more than one registered project."""


class SchemaUpgradeRequired(RuntimeError):
    """The database predates the schema required by a catalog read."""

    code = "schema_upgrade_required"


def _relative_path_depth(value: str) -> int:
    normalized = value.replace("\\", "/").strip("/")
    return 0 if normalized in {"", "."} else len(normalized.split("/"))


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def make_session_id() -> str:
    return f"sess_{uuid.uuid4().hex}"


def make_entity_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Store:
    """SQLite-backed persistence for Chrono Core."""

    def __init__(self, db_path: str | Path, *, read_only: bool = False) -> None:
        self.db_path = Path(db_path)
        self.read_only = read_only
        if not read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._tx_depth = 0
        self._schema_ready = False

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            if self.read_only:
                base_uri = self.db_path.resolve().as_uri()
                try:
                    self._conn = sqlite3.connect(f"{base_uri}?mode=ro", uri=True)
                    self._conn.execute("SELECT 1 FROM sqlite_schema LIMIT 1")
                except sqlite3.OperationalError:
                    if self._conn is not None:
                        self._conn.close()
                    self._conn = sqlite3.connect(
                        f"{base_uri}?mode=ro&immutable=1", uri=True
                    )
            else:
                self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            if not self.read_only:
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
        if self._schema_ready:
            return
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
        self._schema_ready = True

    def ensure_catalog_schema(self) -> None:
        """Verify catalog reads can use the current schema without writing."""
        conn = self._connect()
        try:
            recorded = {
                row["version"]
                for row in conn.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(projects)").fetchall()
            }
        except sqlite3.DatabaseError as exc:
            raise SchemaUpgradeRequired("database schema upgrade required") from exc
        required = {
            "lifecycle_phase",
            "priority",
            "tags",
            "owner",
            "description_usage",
            "current_progress",
            "notes",
            "other_factors",
        }
        if SCHEMA_VERSION not in recorded or not required.issubset(columns):
            raise SchemaUpgradeRequired(
                f"database schema upgrade required (expected v{SCHEMA_VERSION})"
            )

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
        lifecycle_phase: str | None = None,
    ) -> str:
        conn = self._connect()
        now = utc_now()
        existing = conn.execute(
            "SELECT id, relative_path FROM projects WHERE path = ?", (path,)
        ).fetchone()
        if existing:
            # The absolute path is canonical.  Resolve it before an id upsert:
            # the supplied id may already identify an unrelated project.
            stable_relative_path = existing["relative_path"]
            if _relative_path_depth(relative_path) > _relative_path_depth(
                stable_relative_path
            ):
                stable_relative_path = relative_path
            conn.execute(
                """
                UPDATE projects SET
                    name=?,
                    relative_path=?,
                    phase=COALESCE(?, phase),
                    lifecycle_phase=COALESCE(?, lifecycle_phase),
                    summary=COALESCE(?, summary),
                    updated_at=?
                WHERE id=?
                """,
                (
                    name,
                    stable_relative_path,
                    phase,
                    lifecycle_phase,
                    summary,
                    now,
                    existing["id"],
                ),
            )
            self._commit()
            return existing["id"]
        existing_id = conn.execute(
            "SELECT path FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if existing_id and existing_id["path"] != path:
            # Workspace-relative identities can collide when callers use
            # different workspace roots with the same relative project path.
            # Preserve the existing project's history and give the newcomer a
            # deterministic identity rooted in its absolute location instead.
            project_id = make_project_id(str(Path(path).expanduser().resolve()))
            fallback = conn.execute(
                "SELECT path FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if fallback and fallback["path"] != path:
                raise RuntimeError(
                    f"absolute-path project id collision for {path}: {project_id}"
                )
        conn.execute(
            """
            INSERT INTO projects (
                id, name, path, relative_path, status, phase, lifecycle_phase,
                summary, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                path=excluded.path,
                relative_path=excluded.relative_path,
                phase=COALESCE(excluded.phase, phase),
                lifecycle_phase=COALESCE(excluded.lifecycle_phase, lifecycle_phase),
                summary=COALESCE(excluded.summary, summary),
                updated_at=excluded.updated_at
            ON CONFLICT(path) DO UPDATE SET
                name=excluded.name,
                relative_path=excluded.relative_path,
                phase=COALESCE(excluded.phase, phase),
                lifecycle_phase=COALESCE(excluded.lifecycle_phase, lifecycle_phase),
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
                lifecycle_phase,
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

    def record_observation(
        self,
        project_id: str,
        session_id: str | None,
        kind: str,
        content: str,
        source: str = "direct",
    ) -> dict[str, Any]:
        """Record and return one observation."""
        observation_id = make_entity_id("obs")
        observed_at = utc_now()
        self._connect().execute(
            """
            INSERT INTO observations (
                id, project_id, session_id, kind, content, source, observed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation_id,
                project_id,
                session_id,
                kind,
                content,
                source,
                observed_at,
            ),
        )
        self._commit()
        return {
            "id": observation_id,
            "project_id": project_id,
            "session_id": session_id,
            "kind": kind,
            "content": content,
            "source": source,
            "observed_at": observed_at,
        }

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
        if row["status"] == "superseded":
            return {
                "ok": False,
                "action_id": action_id,
                "status": "superseded",
                "error": "already superseded; reopen or supersede instead",
            }
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

    @staticmethod
    def _decode_json_text(raw: Any, fallback: Any) -> Any:
        if raw is None or raw == "":
            return fallback
        try:
            return json.loads(raw)
        except ValueError:
            return fallback

    @classmethod
    def _decode_project(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        record = dict(row)
        record["tags"] = cls._decode_json_text(record.get("tags"), [])
        record["other_factors"] = cls._decode_json_text(
            record.get("other_factors"), {}
        )
        return record

    @classmethod
    def _decode_inventory(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        record = dict(row)
        record["is_git"] = bool(record["is_git"])
        record["detached"] = bool(record["detached"])
        record["dirty"] = bool(record["dirty"])
        raw_error = record.pop("last_error_json", None)
        record["last_error"] = cls._decode_json_text(raw_error, None)
        return record

    def get_project_inventory(self, project_id: str) -> dict[str, Any] | None:
        row = self._connect().execute(
            f"SELECT {_INVENTORY_COLUMNS} FROM project_inventory WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return self._decode_inventory(row)

    @staticmethod
    def _inventory_depth(relative_path: str) -> int:
        return _relative_path_depth(relative_path)

    def upsert_project_inventory(
        self,
        *,
        project_id: str,
        workspace_root: str,
        marker: str,
        depth: int,
        collected: dict[str, Any],
        now: str | None = None,
    ) -> dict[str, Any]:
        """Persist one current inventory observation, retaining Git fields on errors."""
        conn = self._connect()
        seen_at = now or utc_now()
        existing = conn.execute(
            "SELECT * FROM project_inventory WHERE project_id = ?", (project_id,)
        ).fetchone()
        error = collected.get("error")
        encoded_error = json.dumps(error, sort_keys=True) if error is not None else None
        if existing is None:
            values = {
                "is_git": bool(collected.get("is_git", False)),
                "branch": collected.get("branch"),
                "detached": bool(collected.get("detached", False)),
                "head_sha": collected.get("head_sha"),
                "head_subject": collected.get("head_subject"),
                "remote_name": collected.get("remote_name"),
                "remote_url": collected.get("remote_url"),
                "default_branch": collected.get("default_branch"),
                "dirty": bool(collected.get("dirty", False)),
                "changed_count": int(collected.get("changed_count", 0)),
                "untracked_count": int(collected.get("untracked_count", 0)),
                "collected_at": seen_at if error is None else None,
            }
            conn.execute(
                "INSERT INTO project_inventory ("
                f"{_INVENTORY_COLUMNS.replace('project_id, ', '')}, project_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    workspace_root, marker, depth, seen_at, None, None, encoded_error,
                    int(values["is_git"]), values["branch"], int(values["detached"]),
                    values["head_sha"], values["head_subject"], values["remote_name"],
                    values["remote_url"], values["default_branch"], int(values["dirty"]),
                    values["changed_count"], values["untracked_count"], values["collected_at"],
                    project_id,
                ),
            )
        else:
            if error is None:
                assignments = (
                    "workspace_root=?, marker=?, depth=?, last_seen_at=?,"
                    " missing_since=NULL, status_before_missing=NULL, last_error_json=NULL,"
                    " is_git=?, branch=?, detached=?, head_sha=?, head_subject=?,"
                    " remote_name=?, remote_url=?, default_branch=?, dirty=?,"
                    " changed_count=?, untracked_count=?, collected_at=?"
                )
                params = (
                    workspace_root,
                    marker,
                    depth,
                    seen_at,
                    int(bool(collected.get("is_git", False))),
                    collected.get("branch"), int(bool(collected.get("detached", False))),
                    collected.get("head_sha"), collected.get("head_subject"),
                    collected.get("remote_name"), collected.get("remote_url"),
                    collected.get("default_branch"), int(bool(collected.get("dirty", False))),
                    int(collected.get("changed_count", 0)),
                    int(collected.get("untracked_count", 0)),
                    seen_at, project_id,
                )
            else:
                assignments = (
                    "workspace_root=?, marker=?, depth=?, last_seen_at=?, "
                    "last_error_json=?"
                )
                params = (workspace_root, marker, depth, seen_at, encoded_error, project_id)
            conn.execute(
                f"UPDATE project_inventory SET {assignments} WHERE project_id=?", params
            )

        if existing is not None and existing["missing_since"] is not None:
            # Physical rediscovery makes the row present again even when a
            # Git command failed; retain last-good Git fields but restore the
            # catalog status and clear the stale missing marker.
            prior_status = existing["status_before_missing"]
            conn.execute(
                "UPDATE projects SET status = ? WHERE id = ?",
                (prior_status or "active", project_id),
            )
            conn.execute(
                "UPDATE project_inventory SET missing_since=NULL, "
                "status_before_missing=NULL WHERE project_id=?",
                (project_id,),
            )
        self._commit()
        return self.get_project_inventory(project_id) or {}

    def reconcile_missing_inventory(
        self,
        *,
        workspace_root: str,
        max_depth: int,
        include_provisional: bool,
        seen_project_ids: set[str],
        now: str | None = None,
    ) -> list[str]:
        """Mark only rows in the exact scan scope that were not observed."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT project_id, missing_since, status_before_missing FROM project_inventory "
            "WHERE workspace_root = ? AND depth <= ?",
            (workspace_root, max_depth),
        ).fetchall()
        marked: list[str] = []
        timestamp = now or utc_now()
        for row in rows:
            project_id = row["project_id"]
            marker = conn.execute(
                "SELECT marker FROM project_inventory WHERE project_id = ?", (project_id,)
            ).fetchone()["marker"]
            if marker == "provisional" and not include_provisional:
                continue
            if project_id in seen_project_ids or row["missing_since"] is not None:
                continue
            project = conn.execute(
                "SELECT status FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                continue
            saved_status = (
                None if project["status"] == "missing" else project["status"]
            )
            conn.execute(
                "UPDATE project_inventory SET missing_since=?, "
                "status_before_missing=? WHERE project_id=?",
                (timestamp, saved_status, project_id),
            )
            conn.execute(
                "UPDATE projects SET status='missing' WHERE id=?", (project_id,)
            )
            marked.append(project_id)
        self._commit()
        return marked

    def list_projects(
        self,
        *,
        status: str | None = None,
        tag: str | None = None,
        limit: int | None = None,
        dirty: bool | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_catalog_schema()
        conn = self._connect()
        prefixed_columns = "p." + _PROJECT_COLUMNS.replace(", ", ", p.")
        sql = (
            f"SELECT {prefixed_columns}, i.* FROM projects p "
            "LEFT JOIN project_inventory i ON i.project_id = p.id"
        )
        params: list[Any] = []
        conditions: list[str] = []
        if status is not None:
            conditions.append("p.status = ?")
            params.append(status)
        if dirty is not None:
            conditions.append("i.dirty = ?")
            params.append(int(dirty))
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY relative_path"
        records = []
        for row in conn.execute(sql, params):
            record = self._decode_project(row)
            if record is None:
                continue
            record["inventory"] = self._decode_inventory(
                conn.execute(
                    f"SELECT {_INVENTORY_COLUMNS} FROM project_inventory WHERE project_id=?",
                    (record["id"],),
                ).fetchone()
            )
            records.append(record)
        if tag is not None:
            records = [record for record in records if tag in record["tags"]]
        if limit is not None:
            records = records[: max(limit, 0)]
        return records

    def get_project(self, selector: str) -> dict[str, Any] | None:
        """Return one project by exact id, exact absolute path, or relative path.

        Selector order is fixed: exact id, then exact absolute path, then
        exact ``relative_path``. A relative path that matches several
        projects raises :class:`AmbiguousProjectSelector`.
        """
        self.ensure_catalog_schema()
        conn = self._connect()
        row = conn.execute(
            f"SELECT {_PROJECT_COLUMNS} FROM projects WHERE id = ?", (selector,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                f"SELECT {_PROJECT_COLUMNS} FROM projects WHERE path = ?", (selector,)
            ).fetchone()
        if row is None:
            matches = conn.execute(
                f"SELECT {_PROJECT_COLUMNS} FROM projects WHERE relative_path = ?"
                " ORDER BY path",
                (selector,),
            ).fetchall()
            if len(matches) > 1:
                raise AmbiguousProjectSelector(
                    f"relative path '{selector}' matches {len(matches)} projects;"
                    " use a project id or absolute path"
                )
            row = matches[0] if matches else None
        record = self._decode_project(row)
        if record is not None:
            record["inventory"] = self.get_project_inventory(record["id"])
        return record

    @staticmethod
    def _validate_project_metadata(fields: dict[str, Any]) -> dict[str, Any]:
        if not fields:
            raise ValueError("update rejected: no fields supplied")
        unknown = sorted(set(fields) - _PROJECT_METADATA_FIELDS)
        if unknown:
            raise ValueError(f"unsupported project metadata field(s): {unknown}")
        validated: dict[str, Any] = {}
        if "status" in fields:
            if fields["status"] not in PROJECT_STATUSES:
                raise ValueError(
                    f"invalid status {fields['status']!r}; expected one of {PROJECT_STATUSES}"
                )
            validated["status"] = fields["status"]
        if "lifecycle_phase" in fields:
            if fields["lifecycle_phase"] is not None and fields[
                "lifecycle_phase"
            ] not in PROJECT_LIFECYCLE_PHASES:
                raise ValueError(
                    "invalid lifecycle_phase "
                    f"{fields['lifecycle_phase']!r}; expected one of "
                    f"{PROJECT_LIFECYCLE_PHASES}"
                )
            validated["lifecycle_phase"] = fields["lifecycle_phase"]
        if "priority" in fields:
            if fields["priority"] is not None and fields["priority"] not in PROJECT_PRIORITIES:
                raise ValueError(
                    f"invalid priority {fields['priority']!r};"
                    f" expected one of {PROJECT_PRIORITIES}"
                )
            validated["priority"] = fields["priority"]
        if "tags" in fields:
            tags = fields["tags"]
            if not isinstance(tags, list) or not all(
                isinstance(item, str) for item in tags
            ):
                raise ValueError("tags must be a JSON array of strings")
            if len(set(tags)) != len(tags):
                raise ValueError("tags must be unique")
            validated["tags"] = json.dumps(tags, ensure_ascii=False)
        if "other_factors" in fields:
            factors = fields["other_factors"]
            if not isinstance(factors, dict):
                raise ValueError("other_factors must be a JSON object")
            try:
                encoded = json.dumps(factors, ensure_ascii=False)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"other_factors must be JSON-serializable: {exc}") from exc
            validated["other_factors"] = encoded
        for key in (
            "owner",
            "description_usage",
            "summary",
            "current_progress",
            "notes",
        ):
            if key in fields:
                value = fields[key]
                if value is not None and not isinstance(value, str):
                    raise ValueError(f"{key} must be a string")
                validated[key] = value
        return validated

    def update_project_metadata(
        self, project_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Validate and apply a metadata update; return the refreshed record.

        Invalid values raise ``ValueError`` before any mutation. An unknown
        *project_id* returns ``None`` without writing anything.
        """
        validated = self._validate_project_metadata(fields)
        assignments = ", ".join(f"{key} = ?" for key in validated)
        conn = self._connect()
        cursor = conn.execute(
            f"UPDATE projects SET {assignments}, updated_at = ? WHERE id = ?",
            (*validated.values(), utc_now(), project_id),
        )
        self._commit()
        if cursor.rowcount == 0:
            return None
        return self.get_project(project_id)

    def update_project_progress(
        self, project_id: str, text: str
    ) -> dict[str, Any] | None:
        """Narrow convenience update for ``current_progress``."""
        conn = self._connect()
        cursor = conn.execute(
            "UPDATE projects SET current_progress = ?, updated_at = ? WHERE id = ?",
            (text, utc_now(), project_id),
        )
        self._commit()
        if cursor.rowcount == 0:
            return None
        return self.get_project(project_id)

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

    def find_similar_projects(
        self, project_id: str, *, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Rank other registered projects against *project_id* by shared evidence.

        Each project's document is its distilled phase and summary plus its
        captured observation content; names and paths are display metadata,
        never ranking input. Scoring is cosine similarity over sublinear-TF/IDF
        term weights, computed on demand with no schema or dependency change.
        Only positive-score matches are returned, ordered by rounded score
        descending then by project id. ``shared_terms`` lists up to eight terms
        ordered by their contribution to the cosine score, then alphabetically.
        """
        if limit <= 0:
            return []
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, name, path, phase, summary FROM projects"
        ).fetchall()
        if all(row["id"] != project_id for row in rows):
            return []

        observation_text: dict[str, list[str]] = {}
        for row in conn.execute("SELECT project_id, content FROM observations"):
            observation_text.setdefault(row["project_id"], []).append(row["content"])
        tokens: dict[str, list[str]] = {
            row["id"]: tokenize(
                " ".join(
                    [row["phase"] or "", row["summary"] or ""]
                    + observation_text.get(row["id"], [])
                )
            )
            for row in rows
        }

        doc_count = len(rows)
        doc_freq: dict[str, int] = {}
        for terms in tokens.values():
            for term in set(terms):
                doc_freq[term] = doc_freq.get(term, 0) + 1

        def weights(terms: list[str]) -> dict[str, float]:
            counts: dict[str, int] = {}
            for term in terms:
                counts[term] = counts.get(term, 0) + 1
            return {
                # Smooth IDF so terms shared by every registered project still
                # contribute a small positive signal (not a zero-norm vector
                # when the database contains exactly two matching projects).
                term: (1.0 + math.log(count))
                * (math.log((1.0 + doc_count) / (1.0 + doc_freq[term])) + 1.0)
                for term, count in counts.items()
            }

        vectors = {pid: weights(terms) for pid, terms in tokens.items()}
        selected = vectors[project_id]
        selected_norm = math.sqrt(sum(w * w for w in selected.values()))
        if selected_norm == 0:
            return []

        scored: list[dict[str, Any]] = []
        for row in rows:
            if row["id"] == project_id:
                continue
            other = vectors[row["id"]]
            shared = {term: selected[term] * w for term, w in other.items() if term in selected}
            if not shared:
                continue
            dot = sum(shared.values())
            other_norm = math.sqrt(sum(w * w for w in other.values()))
            if other_norm == 0:
                continue
            score = round(dot / (selected_norm * other_norm), 6)
            if score <= 0:
                continue
            contributions = sorted(shared.items(), key=lambda item: (-item[1], item[0]))
            scored.append(
                {
                    "project_id": row["id"],
                    "project_name": row["name"],
                    "project_path": row["path"],
                    "phase": row["phase"],
                    "summary": row["summary"],
                    "score": score,
                    "shared_terms": [term for term, _ in contributions[:8]],
                }
            )
        scored.sort(key=lambda result: (-result["score"], result["project_id"]))
        return scored[:limit]

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
            # Unscoped modes (include_all or legacy flat callers) apply no branch
            # filter, so hidden = total open minus the rows actually returned.
            hidden_blockers = max(
                0,
                conn.execute(
                    """
                    SELECT COUNT(*) AS n FROM blockers
                    WHERE project_id = :pid AND status = 'open'
                    """,
                    {"pid": project_id},
                ).fetchone()["n"]
                - len(blockers),
            )
            hidden_actions = max(
                0,
                conn.execute(
                    """
                    SELECT COUNT(*) AS n FROM next_actions
                    WHERE project_id = :pid AND status = 'open'
                    """,
                    {"pid": project_id},
                ).fetchone()["n"]
                - len(actions),
            )
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

        rec_text = " ".join(
            [d["title"] for d in decisions]
            + [b["title"] for b in blockers]
            + [a["text"] for a in actions]
        )
        rec_terms = salient_terms(rec_text)
        rec_query = " OR ".join(f'"{term}"' for term in rec_terms)
        recommended_patterns = (
            self.search_patterns_safe(rec_query, limit=3) if rec_terms else []
        )

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
            recommended_patterns=recommended_patterns,
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

    def get_project_path(self, project_id: str) -> str | None:
        """Return the registered absolute path for *project_id*, or None."""
        row = self._connect().execute(
            "SELECT path FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return row["path"] if row else None

    def link_bug_remote(
        self, bug_id: str, *, remote_url: str, remote_issue_id: str
    ) -> dict[str, Any]:
        """Persist the remote issue link on an existing bug and return it refreshed.

        Unknown bugs are reported without inserting anything; only the
        nullable remote columns (plus updated_at) are touched.
        """
        current = self.get_bug(bug_id)
        if current is None:
            return {"ok": False, "bug_id": bug_id, "status": "not_found", "bug": None}
        self._connect().execute(
            """
            UPDATE bugs SET remote_url = ?, remote_issue_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (remote_url, remote_issue_id, utc_now(), bug_id),
        )
        self._commit()
        return {"ok": True, "bug_id": bug_id, "status": "linked", "bug": self.get_bug(bug_id)}

    def upsert_pattern(
        self,
        *,
        title: str,
        statement: str = "",
        category: str | None = None,
        source: str = "authored",
        source_ref: str | None = None,
        projects: list[str] | None = None,
        status: str = "candidate",
    ) -> str:
        """Insert or refresh a pattern keyed by its unique title.

        Field values always refresh. The stored status never regresses away
        from promoted/retired, and otherwise only moves forward along
        candidate -> validated -> promoted.
        """
        if status not in _PATTERN_STATUS_RANK:
            raise ValueError(f"invalid pattern status '{status}'")
        conn = self._connect()
        now = utc_now()
        existing = conn.execute(
            "SELECT id, status FROM patterns WHERE title = ?", (title,)
        ).fetchone()
        if existing is None:
            pattern_id = make_entity_id("pat")
            conn.execute(
                """
                INSERT INTO patterns (
                    id, title, statement, category, status, source,
                    source_ref, projects_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pattern_id,
                    title,
                    statement,
                    category,
                    status,
                    source,
                    source_ref,
                    json.dumps(projects or [], ensure_ascii=False),
                    now,
                    now,
                ),
            )
            self._commit()
            return pattern_id

        kept = existing["status"]
        if kept not in ("promoted", "retired"):
            if _PATTERN_STATUS_RANK[status] > _PATTERN_STATUS_RANK[kept]:
                kept = status
        conn.execute(
            """
            UPDATE patterns SET statement = ?, category = ?, source = ?,
                source_ref = ?, projects_json = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                statement,
                category,
                source,
                source_ref,
                json.dumps(projects or [], ensure_ascii=False),
                kept,
                now,
                existing["id"],
            ),
        )
        self._commit()
        return existing["id"]

    def set_pattern_status(self, pattern_id: str, status: str) -> dict[str, Any]:
        from chrono_core.domain.models import PATTERN_STATUSES

        if status not in PATTERN_STATUSES:
            raise ValueError(f"invalid pattern status '{status}'")
        cursor = self._connect().execute(
            "UPDATE patterns SET status = ?, updated_at = ? WHERE id = ?",
            (status, utc_now(), pattern_id),
        )
        self._commit()
        return {
            "ok": cursor.rowcount > 0,
            "pattern_id": pattern_id,
            "status": status if cursor.rowcount > 0 else "not_found",
        }

    def get_pattern(self, pattern_id: str) -> dict[str, Any] | None:
        """Return one pattern by id, or ``None`` when it is unknown."""
        row = self._connect().execute(
            """
            SELECT id, title, statement, category, status, source,
                   source_ref, projects_json, created_at, updated_at
            FROM patterns WHERE id = ?
            """,
            (pattern_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_patterns(
        self, *, status: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, title, statement, category, status, source,
                   source_ref, projects_json, created_at, updated_at
            FROM patterns
        """
        params: list[Any] = []
        if status is not None:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY title"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._connect().execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def search_patterns_safe(
        self,
        query: str,
        *,
        limit: int = 3,
        statuses: tuple[str, ...] = ("candidate", "validated"),
    ) -> list[dict[str, Any]]:
        """FTS match against patterns; malformed queries return []."""
        try:
            rows = self._connect().execute(
                """
                SELECT p.id, p.title, p.category, p.status
                FROM pattern_fts f JOIN patterns p ON p.rowid = f.rowid
                WHERE pattern_fts MATCH ?
                ORDER BY rank LIMIT ?
                """,
                (query, max(limit * 4, limit)),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        hits = [dict(row) for row in rows if row["status"] in statuses]
        return hits[:limit]

    def search_bugs(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._connect().execute(
            """
            SELECT b.* FROM bug_fts f JOIN bugs b ON b.rowid = f.rowid
            WHERE bug_fts MATCH ? ORDER BY rank LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
