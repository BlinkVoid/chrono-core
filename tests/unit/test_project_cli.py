from __future__ import annotations

import json
from pathlib import Path

from chrono_core.cli import main


def _run(capsys, *argv) -> tuple[int, dict | None]:
    rc = main(list(argv))
    out = capsys.readouterr().out
    return rc, json.loads(out) if out.strip() else None


def seeded_db(tmp_path: Path, capsys) -> str:
    db = str(tmp_path / "chrono.db")
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "pyproject.toml").write_text("[project]\n")
    _run(capsys, "discover", "--workspace-root", str(tmp_path), "--db-path", db)
    return db


def test_project_list_reports_discovered_projects(tmp_path: Path, capsys):
    db = str(tmp_path / "chrono.db")
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "pyproject.toml").write_text("[project]\n")
    (tmp_path / "beta").mkdir()
    (tmp_path / "beta" / "pyproject.toml").write_text("[project]\n")
    _run(capsys, "discover", "--workspace-root", str(tmp_path), "--db-path", db)

    rc, listed = _run(capsys, "project", "list", "--db-path", db)
    assert rc == 0
    assert listed["ok"] is True
    assert listed["count"] == 2
    assert [p["relative_path"] for p in listed["projects"]] == ["alpha", "beta"]

    rc, limited = _run(capsys, "project", "list", "--db-path", db, "--limit", "1")
    assert rc == 0
    assert limited["count"] == 1

    rc, none = _run(capsys, "project", "list", "--db-path", db, "--status", "missing")
    assert rc == 0
    assert none["count"] == 0


def test_project_show_resolves_selectors(tmp_path: Path, capsys):
    db = seeded_db(tmp_path, capsys)

    rc, shown = _run(capsys, "project", "show", "alpha", "--db-path", db)
    assert rc == 0
    assert shown["ok"] is True
    assert shown["project"]["relative_path"] == "alpha"

    project_id = shown["project"]["id"]
    rc, by_id = _run(capsys, "project", "show", project_id, "--db-path", db)
    assert rc == 0
    assert by_id["project"]["id"] == project_id

    rc, by_path = _run(
        capsys, "project", "show", str(tmp_path / "alpha"), "--db-path", db
    )
    assert rc == 0
    assert by_path["project"]["relative_path"] == "alpha"

    rc, missing = _run(capsys, "project", "show", "ghost", "--db-path", db)
    assert rc == 1
    assert missing["ok"] is False
    assert missing["code"] == "project_not_found"


def test_project_update_and_progress_roundtrip(tmp_path: Path, capsys):
    db = seeded_db(tmp_path, capsys)

    rc, updated = _run(
        capsys,
        "project", "update", "alpha",
        "--status", "paused",
        "--lifecycle-phase", "maintenance",
        "--priority", "high",
        "--tag", "infra",
        "--tag", "cli",
        "--owner", "r345",
        "--description-usage", "internal tooling",
        "--summary", "one-line state",
        "--notes", "mind the schema",
        "--other-factors", '{"team": "core"}',
        "--db-path", db,
    )
    assert rc == 0
    project = updated["project"]
    assert project["status"] == "paused"
    assert project["phase"] is None
    assert project["lifecycle_phase"] == "maintenance"
    assert project["priority"] == "high"
    assert project["tags"] == ["infra", "cli"]
    assert project["owner"] == "r345"
    assert project["description_usage"] == "internal tooling"
    assert project["summary"] == "one-line state"
    assert project["notes"] == "mind the schema"
    assert project["other_factors"] == {"team": "core"}

    rc, progressed = _run(
        capsys, "project", "progress", "alpha", "wiring the catalog", "--db-path", db
    )
    assert rc == 0
    assert progressed["project"]["current_progress"] == "wiring the catalog"

    rc, retagged = _run(
        capsys, "project", "update", "alpha", "--tag", "solo", "--db-path", db
    )
    assert rc == 0
    assert retagged["project"]["tags"] == ["solo"]


def test_project_update_structured_errors(tmp_path: Path, capsys):
    db = seeded_db(tmp_path, capsys)

    rc, unknown = _run(
        capsys, "project", "update", "ghost", "--status", "paused", "--db-path", db
    )
    assert rc == 1
    assert unknown["code"] == "project_not_found"

    rc, invalid = _run(
        capsys, "project", "update", "alpha", "--status", "vibes", "--db-path", db
    )
    assert rc == 1
    assert invalid["ok"] is False
    assert invalid["code"] == "invalid_input"

    rc, empty = _run(capsys, "project", "update", "alpha", "--db-path", db)
    assert rc == 1
    assert empty["code"] == "empty_update"


def test_project_update_rejects_malformed_other_factors_json(tmp_path: Path, capsys):
    db = seeded_db(tmp_path, capsys)

    rc, envelope = _run(
        capsys,
        "project", "update", "alpha", "--other-factors", "{not json", "--db-path", db,
    )
    assert rc == 2
    assert envelope["ok"] is False
    assert envelope["code"] == "invalid_input"


def test_project_read_commands_report_missing_database(tmp_path: Path, capsys):
    db = str(tmp_path / "absent.sqlite")

    rc, listed = _run(capsys, "project", "list", "--db-path", db)
    assert rc == 1
    assert listed["code"] == "database_not_found"

    rc, shown = _run(capsys, "project", "show", "alpha", "--db-path", db)
    assert rc == 1
    assert shown["code"] == "database_not_found"

    assert not (tmp_path / "absent.sqlite").exists()
