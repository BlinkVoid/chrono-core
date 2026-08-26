from __future__ import annotations

from pathlib import Path

from chrono_core.store.store import Store


def make_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    return store


def test_migration_v4_creates_patterns_and_fts(tmp_path: Path):
    store = make_store(tmp_path)
    conn = store._connect()

    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        ).fetchall()
    }
    assert "patterns" in tables

    # FTS sync triggers fire: a written pattern is searchable.
    conn.execute(
        """
        INSERT INTO patterns (
            id, title, statement, category, status, source,
            source_ref, projects_json, created_at, updated_at
        )
        VALUES ('pat_x', 'Fail-Closed Gating', 'default is rejection',
                'security', 'validated', 'metafactory', NULL, '[]',
                datetime('now'), datetime('now'))
        """
    )
    store._commit()
    row = conn.execute(
        "SELECT p.title FROM pattern_fts f JOIN patterns p ON p.rowid = f.rowid "
        "WHERE pattern_fts MATCH 'rejection'"
    ).fetchone()
    assert row is not None and row["title"] == "Fail-Closed Gating"


def test_migration_ledger_records_v4(tmp_path: Path):
    store = make_store(tmp_path)
    applied = {
        row["version"]
        for row in store._connect().execute("SELECT version FROM schema_migrations")
    }
    assert 4 in applied
