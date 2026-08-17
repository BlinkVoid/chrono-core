from __future__ import annotations

import sqlite3

from chrono_core.store.schema import DDL


def test_schema_bootstraps_in_memory_database():
    conn = sqlite3.connect(":memory:")
    conn.executescript(DDL)

    rows = conn.execute(
        "select name from sqlite_master where type in ('table', 'view') order by name"
    ).fetchall()
    names = {row[0] for row in rows}

    assert "projects" in names
    assert "sessions" in names
    assert "decisions" in names
    assert "blockers" in names
    assert "edges" in names
