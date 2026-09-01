import sqlite3
from pathlib import Path

from chrono_core.store.migrations import MIGRATIONS, apply_pending
from chrono_core.store.schema import DDL, SCHEMA_VERSION

V4_DDL = """
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    phase TEXT,
    summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


def _v5_columns(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {
        row["name"]: row for row in conn.execute("PRAGMA table_info(projects)")
    }


def test_empty_database_migrates_to_v5(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    apply_pending(conn)

    columns = _v5_columns(conn)
    for name in (
        "priority",
        "lifecycle_phase",
        "tags",
        "owner",
        "description_usage",
        "current_progress",
        "notes",
        "other_factors",
    ):
        assert name in columns
    assert columns["priority"]["notnull"] == 0
    assert columns["tags"]["dflt_value"] == "'[]'"
    assert columns["other_factors"]["dflt_value"] == "'{}'"
    applied = {
        row["version"] for row in conn.execute("SELECT version FROM schema_migrations")
    }
    assert applied == set(range(1, SCHEMA_VERSION + 1))


def test_v4_rows_survive_migration_with_defaults(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    conn.row_factory = sqlite3.Row
    conn.executescript(V4_DDL)
    for version in range(1, 5):
        conn.execute(
            "INSERT INTO schema_migrations VALUES (?, 'seeded')", (version,)
        )
    conn.execute(
        "INSERT INTO projects (id, name, path, relative_path, status, phase, summary,"
        " created_at, updated_at)"
        " VALUES ('proj-x', 'legacy', '/ws/legacy', 'legacy', 'active', 'old-phase',"
        " 'old summary', 't0', 't1')"
    )
    conn.commit()

    ran = apply_pending(conn)
    assert 5 in ran

    row = conn.execute("SELECT * FROM projects WHERE id = 'proj-x'").fetchone()
    assert row["phase"] == "old-phase"
    assert row["lifecycle_phase"] is None
    assert row["summary"] == "old summary"
    assert row["priority"] is None
    assert row["owner"] is None
    assert row["description_usage"] is None
    assert row["current_progress"] is None
    assert row["notes"] is None
    assert row["tags"] == "[]"
    assert row["other_factors"] == "{}"


def test_v4_legacy_catalog_maturity_moves_out_of_operational_phase(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    conn.row_factory = sqlite3.Row
    conn.executescript(V4_DDL)
    for version in range(1, 5):
        conn.execute(
            "INSERT INTO schema_migrations VALUES (?, 'seeded')", (version,)
        )
    conn.executemany(
        "INSERT INTO projects "
        "(id, name, path, relative_path, phase, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("maturity", "maturity", "/ws/maturity", "maturity", "validation", "t0", "t1"),
            ("operational", "operational", "/ws/operational", "operational", "blocked", "t0", "t1"),
        ],
    )
    conn.commit()

    apply_pending(conn)

    rows = {
        row["id"]: row
        for row in conn.execute(
            "SELECT id, phase, lifecycle_phase FROM projects ORDER BY id"
        )
    }
    assert rows["maturity"]["phase"] is None
    assert rows["maturity"]["lifecycle_phase"] == "validation"
    assert rows["operational"]["phase"] == "blocked"
    assert rows["operational"]["lifecycle_phase"] is None


def test_v5_migration_is_idempotent_against_fresh_ddl(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    apply_pending(conn)
    apply_pending(conn)
    assert [version for version, _ in MIGRATIONS][-1] == SCHEMA_VERSION
