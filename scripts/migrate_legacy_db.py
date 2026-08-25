"""One-off ops script: copy the legacy continuity DB and remap moved projects.

Not part of the installed package; run ad hoc with the project venv, e.g.::

    uv run python scripts/migrate_legacy_db.py  # or import from a REPL

The workspace layout it remaps (and WORKSPACE_ROOT below) is specific to this
machine's migration history.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from chrono_core.workspace.resolver import make_project_id

WORKSPACE_ROOT = Path("~/workspace")

PROJECT_ROOT_MOVES = (
    (WORKSPACE_ROOT / "BlueCore", WORKSPACE_ROOT / "cores" / "BlueCore"),
    (WORKSPACE_ROOT / "GearCore", WORKSPACE_ROOT / "cores" / "GearCore"),
    (WORKSPACE_ROOT / "ProjectB", WORKSPACE_ROOT / "cores" / "ProjectB"),
    (
        WORKSPACE_ROOT / "OpenSource" / "PromptCore",
        WORKSPACE_ROOT / "cores" / "PromptCore",
    ),
    (WORKSPACE_ROOT / "TestCore", WORKSPACE_ROOT / "cores" / "TestCore"),
    (
        WORKSPACE_ROOT / "continuity-core",
        WORKSPACE_ROOT / "cores" / "chrono-core",
    ),
)

PROJECT_FOREIGN_KEY_TABLES = (
    "sessions",
    "decisions",
    "blockers",
    "next_actions",
    "documents",
    "observations",
)


def _moved_project(
    project_id: str, name: str, path: str
) -> tuple[str, str, str, str, str] | None:
    current = Path(path)
    for old_root, new_root in PROJECT_ROOT_MOVES:
        try:
            suffix = current.relative_to(old_root)
        except ValueError:
            continue

        new_path = new_root / suffix
        new_relative = new_path.relative_to(WORKSPACE_ROOT).as_posix()
        new_name = "chrono-core" if current == WORKSPACE_ROOT / "continuity-core" else name
        return (
            project_id,
            make_project_id(new_relative),
            new_name,
            str(new_path),
            new_relative,
        )
    return None


def migrate_legacy_database(
    source_path: str | Path, target_path: str | Path
) -> dict[str, Any]:
    """Copy the legacy database and remap projects moved into ``workspace/cores``.

    The source database is never modified. The target must not already exist so
    a failed or repeated migration cannot overwrite the only known-good copy.
    """
    source = Path(source_path)
    target = Path(target_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_conn, sqlite3.connect(target) as target_conn:
        source_conn.backup(target_conn)

    with sqlite3.connect(target) as conn:
        rows = conn.execute("SELECT id, name, path FROM projects").fetchall()
        moves = [move for row in rows if (move := _moved_project(*row)) is not None]

        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """CREATE TEMP TABLE project_moves (
                       old_id TEXT PRIMARY KEY,
                       new_id TEXT NOT NULL UNIQUE,
                       new_name TEXT NOT NULL,
                       new_path TEXT NOT NULL UNIQUE,
                       new_relative_path TEXT NOT NULL
                   )"""
            )
            conn.executemany(
                "INSERT INTO project_moves VALUES (?, ?, ?, ?, ?)", moves
            )

            for table in PROJECT_FOREIGN_KEY_TABLES:
                conn.execute(
                    f"""UPDATE {table}
                        SET project_id = (
                            SELECT new_id FROM project_moves
                            WHERE old_id = {table}.project_id
                        )
                        WHERE project_id IN (SELECT old_id FROM project_moves)"""
                )

            conn.execute(
                """UPDATE edges
                   SET source_id = (
                       SELECT new_id FROM project_moves WHERE old_id = edges.source_id
                   )
                   WHERE source_type = 'project'
                     AND source_id IN (SELECT old_id FROM project_moves)"""
            )
            conn.execute(
                """UPDATE edges
                   SET target_id = (
                       SELECT new_id FROM project_moves WHERE old_id = edges.target_id
                   )
                   WHERE target_type = 'project'
                     AND target_id IN (SELECT old_id FROM project_moves)"""
            )
            conn.execute(
                """UPDATE projects
                   SET id = (SELECT new_id FROM project_moves WHERE old_id = projects.id),
                       name = (SELECT new_name FROM project_moves WHERE old_id = projects.id),
                       path = (SELECT new_path FROM project_moves WHERE old_id = projects.id),
                       relative_path = (
                           SELECT new_relative_path FROM project_moves
                           WHERE old_id = projects.id
                       )
                   WHERE id IN (SELECT old_id FROM project_moves)"""
            )

            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise sqlite3.IntegrityError(
                    f"foreign key violations after project migration: {violations[:5]}"
                )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

    return {
        "source": str(source),
        "target": str(target),
        "projects_moved": len(moves),
    }
