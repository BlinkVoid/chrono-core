"""Ordered per-version schema migrations.

Each migration is (version, label) with its statements registered in
_STATEMENTS. Versions below the first tracked migration predate this
framework (the monolithic-DDL era) and are backfilled into
schema_migrations so the ledger stays contiguous.
"""

from __future__ import annotations

import re
import sqlite3

from chrono_core.store.schema import SCHEMA_VERSION

MIGRATIONS: list[tuple[int, str]] = [
    (
        3,
        "lifecycle columns (next_actions/blockers), bugs table + FTS, first indexes",
    ),
    (4, "patterns table + FTS"),
    (5, "project catalog metadata (priority, tags, owner, description_usage, "
        "current_progress, notes, lifecycle_phase, other_factors)"),
    (6, "current project Git inventory and missing reconciliation"),
]

_V3_LIFECYCLE_BUGS = [
    "ALTER TABLE next_actions ADD COLUMN cancelled_at TEXT",
    "ALTER TABLE next_actions ADD COLUMN supersedes_id TEXT REFERENCES next_actions(id)",
    "ALTER TABLE next_actions ADD COLUMN raw_history_json TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE blockers ADD COLUMN cancelled_at TEXT",
    """
    CREATE TABLE IF NOT EXISTS bugs (
        id TEXT PRIMARY KEY,
        project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        severity TEXT NOT NULL DEFAULT 'medium',
        status TEXT NOT NULL DEFAULT 'open',
        found_in_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
        fixed_in_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
        remote_url TEXT,
        remote_issue_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        resolved_at TEXT
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS bug_fts USING fts5(
        title, detail, content='bugs', content_rowid='rowid'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS bugs_fts_insert
    AFTER INSERT ON bugs BEGIN
        INSERT INTO bug_fts (rowid, title, detail) VALUES (new.rowid, new.title, new.detail);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS bugs_fts_delete
    AFTER DELETE ON bugs BEGIN
        INSERT INTO bug_fts (bug_fts, rowid, title, detail)
        VALUES ('delete', old.rowid, old.title, old.detail);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS bugs_fts_update
    AFTER UPDATE ON bugs BEGIN
        INSERT INTO bug_fts (bug_fts, rowid, title, detail)
        VALUES ('delete', old.rowid, old.title, old.detail);
        INSERT INTO bug_fts (rowid, title, detail) VALUES (new.rowid, new.title, new.detail);
    END
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_proj_ended ON sessions(project_id, ended_at)",
    "CREATE INDEX IF NOT EXISTS idx_actions_proj_status_created"
    " ON next_actions(project_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_blockers_proj_status_created"
    " ON blockers(project_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_bugs_proj_status_created"
    " ON bugs(project_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_decisions_proj_created ON decisions(project_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_observations_proj ON observations(project_id)",
]

_V4_PATTERNS = [
    """
    CREATE TABLE IF NOT EXISTS patterns (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL UNIQUE,
        statement TEXT NOT NULL DEFAULT '',
        category TEXT,
        status TEXT NOT NULL DEFAULT 'candidate',
        source TEXT NOT NULL DEFAULT 'authored',
        source_ref TEXT,
        projects_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS pattern_fts USING fts5(
        title, statement, content='patterns', content_rowid='rowid'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS patterns_fts_insert
    AFTER INSERT ON patterns BEGIN
        INSERT INTO pattern_fts (rowid, title, statement)
        VALUES (new.rowid, new.title, new.statement);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS patterns_fts_delete
    AFTER DELETE ON patterns BEGIN
        INSERT INTO pattern_fts (pattern_fts, rowid, title, statement)
        VALUES ('delete', old.rowid, old.title, old.statement);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS patterns_fts_update
    AFTER UPDATE ON patterns BEGIN
        INSERT INTO pattern_fts (pattern_fts, rowid, title, statement)
        VALUES ('delete', old.rowid, old.title, old.statement);
        INSERT INTO pattern_fts (rowid, title, statement)
        VALUES (new.rowid, new.title, new.statement);
    END
    """,
]

# Mirrors the source tool's column set so an imported registry keeps its
# metadata fields natively instead of only as archived observations.
_V5_PROJECT_CATALOG = [
    "ALTER TABLE projects ADD COLUMN priority TEXT",
    "ALTER TABLE projects ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE projects ADD COLUMN owner TEXT",
    "ALTER TABLE projects ADD COLUMN description_usage TEXT",
    "ALTER TABLE projects ADD COLUMN current_progress TEXT",
    "ALTER TABLE projects ADD COLUMN notes TEXT",
    "ALTER TABLE projects ADD COLUMN lifecycle_phase TEXT",
    "ALTER TABLE projects ADD COLUMN other_factors TEXT NOT NULL DEFAULT '{}'",
    # Tier-2 catalog builds wrote maturity into the operational phase column.
    # Move only recognized maturity values; Chrono's active/blocked/unknown
    # operational values remain untouched.
    "UPDATE projects SET lifecycle_phase = phase "
    "WHERE phase IN ('prototype', 'validation', 'commercialisation', "
    "'maintenance', 'archived') AND lifecycle_phase IS NULL",
    "UPDATE projects SET phase = NULL "
    "WHERE phase IN ('prototype', 'validation', 'commercialisation', "
    "'maintenance', 'archived') AND lifecycle_phase = phase",
]

_V6_PROJECT_INVENTORY = [
    """
    CREATE TABLE IF NOT EXISTS project_inventory (
        project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        workspace_root TEXT NOT NULL,
        marker TEXT NOT NULL,
        depth INTEGER NOT NULL,
        last_seen_at TEXT,
        missing_since TEXT,
        status_before_missing TEXT,
        last_error_json TEXT,
        is_git INTEGER NOT NULL DEFAULT 0,
        branch TEXT,
        detached INTEGER NOT NULL DEFAULT 0,
        head_sha TEXT,
        head_subject TEXT,
        remote_name TEXT,
        remote_url TEXT,
        default_branch TEXT,
        dirty INTEGER NOT NULL DEFAULT 0,
        changed_count INTEGER NOT NULL DEFAULT 0,
        untracked_count INTEGER NOT NULL DEFAULT 0,
        collected_at TEXT
    )
    """,
]

_STATEMENTS: dict[int, list[str]] = {
    3: _V3_LIFECYCLE_BUGS,
    4: _V4_PATTERNS,
    5: _V5_PROJECT_CATALOG,
    6: _V6_PROJECT_INVENTORY,
}


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row["version"] for row in rows}


# SQLite has no ADD COLUMN IF NOT EXISTS; guard ALTERs against databases
# whose columns already exist (partially applied migration or ledger rows
# removed without a matching rollback of the DDL).
_ALTER_ADD_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)", re.IGNORECASE
)


def _execute_statement(conn: sqlite3.Connection, statement: str) -> None:
    match = _ALTER_ADD_COLUMN.match(statement.strip())
    if match:
        table, column = match.groups()
        existing = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
        }
        if column in existing:
            return
    conn.execute(statement)


def apply_pending(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations in order; refuse newer-than-code databases."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    recorded = applied_versions(conn)
    newest = max(recorded, default=0)
    if newest > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema version {newest} is newer than supported {SCHEMA_VERSION}"
        )
    ran: list[int] = []
    for version, _label in MIGRATIONS:
        if version in recorded:
            continue
        for statement in _STATEMENTS[version]:
            _execute_statement(conn, statement)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at)"
            " VALUES (?, datetime('now'))",
            (version,),
        )
        recorded.add(version)
        ran.append(version)
    # Backfill versions from before per-version bookkeeping existed so the
    # ledger covers 1..SCHEMA_VERSION contiguously.
    for version in range(1, SCHEMA_VERSION + 1):
        if version not in recorded:
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at)"
                " VALUES (?, datetime('now'))",
                (version,),
            )
    return ran
