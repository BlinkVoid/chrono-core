from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from chrono_core.cli import main
from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


def _doctor(argv: list[str], capsys) -> tuple[int, dict]:
    try:
        rc = main(["doctor", *argv, "--json"])
    except SystemExit as exc:
        pytest.fail(f"doctor command is not registered: {exc}")
    return rc, json.loads(capsys.readouterr().out)


def _seed_project(store: Store, workspace: Path, name: str) -> str:
    path = workspace / name
    path.mkdir(parents=True)
    (path / ".git").mkdir()
    return store.get_or_create_project(resolve_project(path, workspace_root=workspace))


def test_doctor_reports_healthy_database(tmp_path: Path, capsys):
    db_path = tmp_path / "chrono.db"
    store = Store(db_path)
    store.init_schema()
    project_id = _seed_project(store, tmp_path / "workspace", "alpha")
    store.create_session(
        project_id, HandoffPayload(summary="healthy"), GitState(branch="main")
    )
    store.close()

    rc, result = _doctor(["--db-path", str(db_path)], capsys)

    assert rc == 0
    assert result["ok"] is True
    assert result["summary"] == {"pass": 6, "warn": 0, "fail": 0}
    assert set(result["checks"]) == {
        "integrity",
        "foreign_keys",
        "project_identity",
        "session_ownership",
        "legacy_bucket",
        "unsafe_mined_patterns",
    }
    assert all(check["status"] == "pass" for check in result["checks"].values())


def test_doctor_default_output_is_human_readable(tmp_path: Path, capsys):
    db_path = tmp_path / "chrono.db"
    store = Store(db_path)
    store.init_schema()
    store.close()

    rc = main(["doctor", "--db-path", str(db_path)])

    assert rc == 0
    output = capsys.readouterr().out
    assert "PASS integrity: SQLite integrity is clean." in output
    assert "Doctor: 6 passed, 0 warning(s), 0 failed." in output


def test_doctor_accepts_historical_project_ids_when_paths_are_unique(
    tmp_path: Path, capsys
):
    db_path = tmp_path / "chrono.db"
    store = Store(db_path)
    store.init_schema()
    store.upsert_project(
        project_id="historical-id",
        name="historical",
        path="/historical/project",
        relative_path=".",
    )
    store.close()

    rc, result = _doctor(["--db-path", str(db_path)], capsys)

    assert rc == 0
    assert result["checks"]["project_identity"]["status"] == "pass"


def test_doctor_detects_logical_contamination(tmp_path: Path, capsys):
    db_path = tmp_path / "chrono.db"
    workspace = tmp_path / "workspace"
    store = Store(db_path)
    store.init_schema()
    alpha_id = _seed_project(store, workspace, "alpha")
    beta_id = _seed_project(store, workspace, "beta")
    session_id = store.create_session(
        alpha_id, HandoffPayload(summary="mixed"), GitState(branch="main")
    )
    store.record_next_actions(beta_id, session_id, ["belongs to beta, session belongs to alpha"])
    store.upsert_project(
        project_id="-cdb4ee2aea",
        name="legacy-unresolved-bucket",
        path="/legacy/unresolved",
        relative_path=".",
    )
    store.upsert_project(
        project_id="wrong-project-id",
        name="wrong",
        path="/wrong/project",
        relative_path="alpha",
    )
    store.create_session(
        "-cdb4ee2aea", HandoffPayload(summary="residue"), GitState(branch="main")
    )
    store.upsert_pattern(
        title="Recurring theme: retry",
        source="mined",
        status="candidate",
    )
    store.close()

    rc, result = _doctor(["--db-path", str(db_path)], capsys)

    assert rc == 1
    assert result["ok"] is False
    assert result["checks"]["project_identity"]["status"] == "warn"
    assert result["checks"]["session_ownership"]["count"] == 1
    assert result["checks"]["legacy_bucket"]["status"] == "fail"
    assert result["checks"]["unsafe_mined_patterns"]["count"] == 1


def test_doctor_warns_for_empty_legacy_bucket(tmp_path: Path, capsys):
    db_path = tmp_path / "chrono.db"
    store = Store(db_path)
    store.init_schema()
    store.upsert_project(
        project_id="-cdb4ee2aea",
        name="legacy-unresolved-bucket",
        path="/legacy/unresolved",
        relative_path=".",
    )
    store.close()

    rc, result = _doctor(["--db-path", str(db_path)], capsys)

    assert rc == 0
    assert result["ok"] is True
    assert result["checks"]["legacy_bucket"]["status"] == "warn"
    assert result["checks"]["legacy_bucket"]["count"] == 0


def test_doctor_missing_database_does_not_create_it(tmp_path: Path, capsys):
    db_path = tmp_path / "missing.db"

    rc, result = _doctor(["--db-path", str(db_path)], capsys)

    assert rc == 1
    assert result["ok"] is False
    assert result["error"] == "database not found"
    assert not db_path.exists()


def test_doctor_reports_foreign_key_violations(tmp_path: Path, capsys):
    db_path = tmp_path / "chrono.db"
    store = Store(db_path)
    store.init_schema()
    store.close()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        """
        INSERT INTO sessions (
            id, project_id, ended_at, summary, git_dirty, raw_payload_json
        ) VALUES ('sess_orphan', 'missing-project', 'now', 'orphan', 0, '{}')
        """
    )
    conn.commit()
    conn.close()

    rc, result = _doctor(["--db-path", str(db_path)], capsys)

    assert rc == 1
    assert result["checks"]["foreign_keys"]["status"] == "fail"
    assert result["checks"]["foreign_keys"]["count"] == 1


def test_doctor_reports_unreadable_database(tmp_path: Path, capsys):
    db_path = tmp_path / "not-sqlite.db"
    db_path.write_text("not a sqlite database")

    rc, result = _doctor(["--db-path", str(db_path)], capsys)

    assert rc == 1
    assert result["ok"] is False
    assert result["error"] == "database unreadable"
