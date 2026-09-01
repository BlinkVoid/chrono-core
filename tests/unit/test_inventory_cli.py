"""CLI contracts for live inventory: discover counts, dirty flags, refresh."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from chrono_core.cli import main


def _run(capsys, *argv) -> tuple[int, dict | None]:
    rc = main(list(argv))
    out = capsys.readouterr().out
    return rc, json.loads(out) if out.strip() else None


def _git_repo(path: Path, *, subject: str = "seed commit") -> Path:
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(path)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(path), "add", "pyproject.toml"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.email=t@example.com", "-c",
         "user.name=t", "commit", "-q", "--allow-empty", "-m", subject],
        check=True,
        capture_output=True,
    )
    return path


def test_discover_persisted_json_reports_live_inventory_counts(tmp_path: Path, capsys):
    workspace = tmp_path / "workspace"
    _git_repo(workspace / "alpha")
    db = str(tmp_path / "chrono.db")

    rc, result = _run(
        capsys, "discover", "--workspace-root", str(workspace), "--db-path", db
    )

    assert rc == 0
    assert result["ok"] is True
    assert result["persisted_count"] == 1
    assert result["refreshed_count"] == 1
    assert result["missing_count"] == 0
    assert result["failed_count"] == 0
    assert result["failures"] == []

    rc, shown = _run(capsys, "project", "show", "alpha", "--db-path", db)
    assert rc == 0
    inventory = shown["project"]["inventory"]
    assert inventory["is_git"] is True
    assert inventory["branch"] == "main"
    assert inventory["dirty"] is False
    assert inventory["head_subject"] == "seed commit"


def test_discover_no_persist_stays_pure(tmp_path: Path, capsys):
    workspace = tmp_path / "workspace"
    _git_repo(workspace / "alpha")
    db = tmp_path / "absent.sqlite"

    rc, result = _run(
        capsys,
        "discover",
        "--workspace-root",
        str(workspace),
        "--no-persist",
        "--db-path",
        str(db),
    )

    assert rc == 0
    assert result["ok"] is True
    assert result["discovered_count"] == 1
    assert result["refreshed_count"] == 0
    assert not db.exists()


def test_project_list_dirty_flags_use_current_inventory(tmp_path: Path, capsys):
    workspace = tmp_path / "workspace"
    alpha = _git_repo(workspace / "alpha")
    beta = _git_repo(workspace / "beta")
    db = str(tmp_path / "chrono.db")

    _run(capsys, "discover", "--workspace-root", str(workspace), "--db-path", db)

    rc, none = _run(capsys, "project", "list", "--db-path", db)
    assert rc == 0
    assert none["count"] == 2

    # Make alpha dirty, then refresh only alpha.
    (alpha / "wip.txt").write_text("dirty\n", encoding="utf-8")
    rc, refreshed = _run(
        capsys, "project", "refresh", "alpha", "--db-path", db
    )
    assert rc == 0
    assert refreshed["ok"] is True
    assert refreshed["project"]["inventory"]["dirty"] is True

    # beta was not refreshed: its inventory stays clean even though the
    # historical session snapshots (none here) are never consulted.
    rc, dirty = _run(capsys, "project", "list", "--dirty", "--db-path", db)
    assert rc == 0
    assert [p["relative_path"] for p in dirty["projects"]] == ["alpha"]

    rc, clean = _run(capsys, "project", "list", "--no-dirty", "--db-path", db)
    assert rc == 0
    assert [p["relative_path"] for p in clean["projects"]] == ["beta"]

    combined = _run(
        capsys, "project", "list", "--dirty", "--no-dirty", "--db-path", db
    )
    assert combined[0] == 2

    # beta is dirty on disk but its stored inventory only changes on refresh.
    (beta / "wip.txt").write_text("dirty\n", encoding="utf-8")
    rc, still_clean = _run(capsys, "project", "list", "--no-dirty", "--db-path", db)
    assert [p["relative_path"] for p in still_clean["projects"]] == ["beta"]


def test_project_refresh_reports_missing_db_and_unknown_project(
    tmp_path: Path, capsys
):
    absent = str(tmp_path / "absent.sqlite")
    rc, missing = _run(capsys, "project", "refresh", "alpha", "--db-path", absent)
    assert rc == 1
    assert missing["code"] == "database_not_found"
    assert not Path(absent).exists()

    workspace = tmp_path / "workspace"
    _git_repo(workspace / "alpha")
    db = str(tmp_path / "chrono.db")
    _run(capsys, "discover", "--workspace-root", str(workspace), "--db-path", db)

    rc, unknown = _run(capsys, "project", "refresh", "ghost", "--db-path", db)
    assert rc == 1
    assert unknown["code"] == "project_not_found"


def test_project_refresh_marks_vanished_path_structurally(tmp_path: Path, capsys):
    workspace = tmp_path / "workspace"
    gone = _git_repo(workspace / "gone")
    db = str(tmp_path / "chrono.db")
    _run(capsys, "discover", "--workspace-root", str(workspace), "--db-path", db)

    import shutil

    shutil.rmtree(gone)
    rc, vanished = _run(capsys, "project", "refresh", "gone", "--db-path", db)
    assert rc == 1
    assert vanished["ok"] is False
    assert vanished["code"] == "path_not_found"


def test_discover_reconciles_missing_and_restores_status(tmp_path: Path, capsys):
    workspace = tmp_path / "workspace"
    _git_repo(workspace / "alpha")
    beta = _git_repo(workspace / "beta")
    db = str(tmp_path / "chrono.db")
    _run(capsys, "discover", "--workspace-root", str(workspace), "--db-path", db)

    _run(capsys, "project", "update", "beta", "--status", "paused", "--db-path", db)
    import shutil

    shutil.rmtree(beta)
    rc, result = _run(
        capsys, "discover", "--workspace-root", str(workspace), "--db-path", db
    )
    assert rc == 0
    assert result["missing_count"] == 1

    rc, shown = _run(capsys, "project", "show", "beta", "--db-path", db)
    assert shown["project"]["status"] == "missing"
    assert shown["project"]["inventory"]["status_before_missing"] == "paused"

    beta = _git_repo(workspace / "beta")
    rc, result = _run(
        capsys, "discover", "--workspace-root", str(workspace), "--db-path", db
    )
    assert result["missing_count"] == 0
    rc, shown = _run(capsys, "project", "show", "beta", "--db-path", db)
    assert shown["project"]["status"] == "paused"
    assert shown["project"]["inventory"]["missing_since"] is None
