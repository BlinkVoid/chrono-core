from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from chrono_core.migrations import migrate_legacy_database
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import make_project_id


def test_identity_migration_preserves_observations_fts_and_foreign_keys(tmp_path: Path):
    source = tmp_path / "continuity.db"
    target = tmp_path / "chrono.db"
    Store(source).init_schema()

    old_relative = "continuity-core"
    old_id = make_project_id(old_relative)
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(source) as conn:
        conn.execute(
            """INSERT INTO projects
               (id, name, path, relative_path, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'active', ?, ?)""",
            (
                old_id,
                "continuity-core",
                "~/workspace/continuity-core",
                old_relative,
                now,
                now,
            ),
        )
        conn.execute(
            """INSERT INTO observations
               (id, project_id, kind, content, source, observed_at)
               VALUES ('obs-1', ?, 'note', 'rename survives', 'test', ?)""",
            (old_id, now),
        )

    result = migrate_legacy_database(source, target)

    assert result["projects_moved"] == 1
    new_id = make_project_id("cores/chrono-core")
    with sqlite3.connect(target) as conn:
        project = conn.execute(
            "SELECT id, name, path, relative_path FROM projects"
        ).fetchone()
        observation_project = conn.execute(
            "SELECT project_id FROM observations WHERE id = 'obs-1'"
        ).fetchone()[0]
        fts_content = conn.execute(
            "SELECT content FROM observation_fts WHERE observation_fts MATCH 'rename'"
        ).fetchone()[0]
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()

    assert project == (
        new_id,
        "chrono-core",
        "~/workspace/cores/chrono-core",
        "cores/chrono-core",
    )
    assert observation_project == new_id
    assert fts_content == "rename survives"
    assert violations == []
