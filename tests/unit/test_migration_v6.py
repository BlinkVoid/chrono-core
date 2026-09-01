"""Schema v6: project_inventory table, migration, and FK/cascade contract."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from chrono_core.store.migrations import MIGRATIONS, apply_pending
from chrono_core.store.schema import DDL, SCHEMA_VERSION

V5_DDL = """
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    phase TEXT,
    lifecycle_phase TEXT,
    summary TEXT,
    priority TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    owner TEXT,
    description_usage TEXT,
    current_progress TEXT,
    notes TEXT,
    other_factors TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""

EXPECTED_INVENTORY_COLUMNS = (
    "project_id",
    "workspace_root",
    "marker",
    "depth",
    "last_seen_at",
    "missing_since",
    "status_before_missing",
    "last_error_json",
    "is_git",
    "branch",
    "detached",
    "head_sha",
    "head_subject",
    "remote_name",
    "remote_url",
    "default_branch",
    "dirty",
    "changed_count",
    "untracked_count",
    "collected_at",
)


def _inventory_columns(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {
        row["name"]: row
        for row in conn.execute("PRAGMA table_info(project_inventory)")
    }


def test_latest_migration_is_v6():
    assert SCHEMA_VERSION == 6
    assert MIGRATIONS[-1][0] == 6


def test_fresh_database_creates_project_inventory_with_design_columns(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    apply_pending(conn)

    columns = _inventory_columns(conn)
    assert tuple(columns) == EXPECTED_INVENTORY_COLUMNS
    assert columns["project_id"]["pk"] == 1
    assert columns["is_git"]["notnull"] == 1
    assert columns["dirty"]["notnull"] == 1
    assert columns["dirty"]["dflt_value"] == "0"

    applied = {
        row["version"] for row in conn.execute("SELECT version FROM schema_migrations")
    }
    assert applied == set(range(1, SCHEMA_VERSION + 1))


def test_v5_database_gains_inventory_and_keeps_project_rows(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    conn.row_factory = sqlite3.Row
    conn.executescript(V5_DDL)
    for version in range(1, 6):
        conn.execute("INSERT INTO schema_migrations VALUES (?, 'seeded')", (version,))
    conn.execute(
        "INSERT INTO projects (id, name, path, relative_path, status, created_at,"
        " updated_at, priority, tags)"
        " VALUES ('p1', 'alpha', '/ws/alpha', 'alpha', 'paused', 't0', 't1',"
        " 'high', '[\"infra\"]')"
    )
    conn.commit()

    ran = apply_pending(conn)
    assert 6 in ran
    assert "project_id" in _inventory_columns(conn)

    row = conn.execute("SELECT * FROM projects WHERE id = 'p1'").fetchone()
    assert row["status"] == "paused"
    assert row["priority"] == "high"
    assert row["tags"] == '["infra"]'


def test_v6_migration_is_idempotent(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    apply_pending(conn)
    apply_pending(conn)
    conn.execute(
        "INSERT INTO projects (id, name, path, relative_path, created_at, updated_at)"
        " VALUES ('p1', 'alpha', '/ws/alpha', 'alpha', 't0', 't1')"
    )
    conn.execute(
        "INSERT INTO project_inventory (project_id, workspace_root, marker, depth,"
        " is_git, dirty) VALUES ('p1', '/ws', 'pyproject.toml', 1, 1, 0)"
    )
    conn.commit()
    apply_pending(conn)

    row = conn.execute(
        "SELECT dirty FROM project_inventory WHERE project_id = 'p1'"
    ).fetchone()
    assert row["dirty"] == 0


def test_inventory_rows_cascade_with_their_project(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending(conn)
    conn.execute(
        "INSERT INTO projects (id, name, path, relative_path, created_at, updated_at)"
        " VALUES ('p1', 'alpha', '/ws/alpha', 'alpha', 't0', 't1')"
    )
    conn.execute(
        "INSERT INTO project_inventory (project_id, workspace_root, marker, depth)"
        " VALUES ('p1', '/ws', 'pyproject.toml', 1)"
    )
    conn.commit()

    conn.execute("DELETE FROM projects WHERE id = 'p1'")
    conn.commit()

    remaining = conn.execute("SELECT COUNT(*) AS n FROM project_inventory").fetchone()
    assert remaining["n"] == 0
