import sqlite3
from pathlib import Path

import pytest

from chrono_core.store.migrations import SCHEMA_VERSION, apply_pending
from chrono_core.store.schema import DDL


def _fresh(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.executescript(DDL)
    return conn


def test_v3_adds_lifecycle_columns_bugs_and_indexes(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    conn.row_factory = sqlite3.Row
    _fresh(conn)
    apply_pending(conn)

    cols = {
        r["name"]
        for r in conn.execute("PRAGMA table_info(next_actions)").fetchall()
    }
    assert {"cancelled_at", "supersedes_id", "raw_history_json"} <= cols
    assert "cancelled_at" in {
        r["name"] for r in conn.execute("PRAGMA table_info(blockers)").fetchall()
    }

    bug_cols = {
        r["name"]: r for r in conn.execute("PRAGMA table_info(bugs)").fetchall()
    }
    assert bug_cols["project_id"]["notnull"] == 0
    indexes = {
        r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    assert "idx_sessions_proj_ended" in indexes
    assert "idx_actions_proj_status_created" in indexes
    assert "idx_bugs_proj_status_created" in indexes
    applied = {
        r["version"] for r in conn.execute("SELECT version FROM schema_migrations")
    }
    assert applied == set(range(1, SCHEMA_VERSION + 1))


def test_refuses_newer_database(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    conn.row_factory = sqlite3.Row
    _fresh(conn)
    conn.execute("INSERT INTO schema_migrations VALUES (99, 'future')")
    with pytest.raises(RuntimeError, match="newer"):
        apply_pending(conn)
