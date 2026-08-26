"""One-off ops script: copy a legacy continuity DB and remap moved projects.

Not part of the installed package; run ad hoc with the project venv, e.g.::

    uv run python scripts/migrate_legacy_db.py  # or import from a REPL

The remap is workspace-specific, so it is supplied by the operator rather than
baked in. Two environment variables configure it:

``CHRONO_MIGRATION_WORKSPACE_ROOT``
    Absolute path to the workspace root. Defaults to ``~/workspace``.

``CHRONO_MIGRATION_MOVES``
    JSON array of ``[old_relative_path, new_relative_path]`` pairs, relative to
    the workspace root, e.g.::

        CHRONO_MIGRATION_MOVES='[["MyTool", "tools/MyTool"], ["old-name", "tools/new-name"]]'

    A project's new name is taken from the last segment of its new path, so a
    move that also renames the directory renames the project too. Unset or empty
    means no moves, which makes the migration a plain copy.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from chrono_core.workspace.resolver import make_project_id

WORKSPACE_ROOT = Path(
    os.environ.get("CHRONO_MIGRATION_WORKSPACE_ROOT", str(Path.home() / "workspace"))
)


def _load_project_root_moves() -> tuple[tuple[Path, Path], ...]:
    """Read the operator-supplied move map from the environment."""
    raw = os.environ.get("CHRONO_MIGRATION_MOVES", "").strip()
    if not raw:
        return ()
    return tuple(
        (WORKSPACE_ROOT / old, WORKSPACE_ROOT / new) for old, new in json.loads(raw)
    )


PROJECT_ROOT_MOVES = _load_project_root_moves()

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
        new_name = new_path.name
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
