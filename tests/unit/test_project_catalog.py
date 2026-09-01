from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from chrono_core import services
from chrono_core.store.store import AmbiguousProjectSelector, Store

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


def _seed(store: Store, path: str, relative: str) -> str:
    return store.upsert_project(
        project_id=relative.replace("/", "-") + "-0001",
        name=relative.split("/")[-1],
        path=path,
        relative_path=relative,
    )


# --- Store: list filters ----------------------------------------------------


def test_list_projects_decodes_json_fields(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    pid = _seed(store, "/ws/alpha", "alpha")
    store.update_project_metadata(
        pid,
        {
            "tags": ["infra", "cli"],
            "other_factors": {"team": "core", "risk": "low"},
            "priority": "high",
            "owner": "r345",
        },
    )

    projects = store.list_projects()
    assert len(projects) == 1
    record = projects[0]
    assert record["tags"] == ["infra", "cli"]
    assert record["other_factors"] == {"team": "core", "risk": "low"}
    assert record["priority"] == "high"
    assert record["owner"] == "r345"
    assert record["description_usage"] is None


def test_list_projects_filters_status_tag_and_limit(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    alpha = _seed(store, "/ws/alpha", "alpha")
    beta = _seed(store, "/ws/beta", "beta")
    gamma = _seed(store, "/ws/gamma", "gamma")
    store.update_project_metadata(alpha, {"tags": ["infra"], "status": "paused"})
    store.update_project_metadata(beta, {"tags": ["infra", "cli"]})
    store.update_project_metadata(gamma, {"status": "archived"})

    by_status = store.list_projects(status="paused")
    assert [p["id"] for p in by_status] == [alpha]

    by_tag = store.list_projects(tag="infra")
    assert [p["id"] for p in by_tag] == [alpha, beta]

    limited = store.list_projects(tag="infra", limit=1)
    assert [p["id"] for p in limited] == [alpha]

    unknown_tag = store.list_projects(tag="nope")
    assert unknown_tag == []


# --- Store: selector resolution ---------------------------------------------


def test_get_project_resolves_id_then_path_then_relative_path(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    pid = _seed(store, "/ws/alpha", "alpha")

    by_id = store.get_project(pid)
    assert by_id is not None and by_id["id"] == pid

    by_path = store.get_project("/ws/alpha")
    assert by_path is not None and by_path["id"] == pid

    by_relative = store.get_project("alpha")
    assert by_relative is not None and by_relative["id"] == pid

    assert store.get_project("missing") is None


def test_get_project_reports_ambiguous_relative_path(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    _seed(store, "/root-a/app", "app")
    _seed(store, "/root-b/app", "app")

    with pytest.raises(AmbiguousProjectSelector):
        store.get_project("app")


# --- Store: metadata updates -------------------------------------------------


def test_update_project_metadata_updates_fields_and_refreshes_record(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    pid = _seed(store, "/ws/alpha", "alpha")
    store.update_project_state(pid, phase="active")
    before = store.get_project(pid)

    updated = store.update_project_metadata(
        pid,
        {
            "status": "paused",
            "lifecycle_phase": "maintenance",
            "priority": "critical",
            "tags": ["x"],
            "owner": "r345",
            "description_usage": "used by tests",
            "summary": "new summary",
            "notes": "remember this",
            "other_factors": {"k": "v"},
        },
    )

    assert updated["id"] == pid
    assert updated["status"] == "paused"
    assert updated["phase"] == "active"
    assert updated["lifecycle_phase"] == "maintenance"
    assert updated["priority"] == "critical"
    assert updated["tags"] == ["x"]
    assert updated["owner"] == "r345"
    assert updated["description_usage"] == "used by tests"
    assert updated["summary"] == "new summary"
    assert updated["notes"] == "remember this"
    assert updated["other_factors"] == {"k": "v"}
    assert updated["updated_at"] > before["updated_at"]


def test_update_project_metadata_replaces_tags_in_order(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    pid = _seed(store, "/ws/alpha", "alpha")

    # Duplicate tags are rejected before mutation, so the previous set survives.
    with pytest.raises(ValueError):
        store.update_project_metadata(pid, {"tags": ["b", "a", "b"]})
    assert store.get_project(pid)["tags"] == []

    store.update_project_metadata(pid, {"tags": ["z", "a"]})
    assert store.get_project(pid)["tags"] == ["z", "a"]


def test_update_project_metadata_rejects_invalid_input(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    pid = _seed(store, "/ws/alpha", "alpha")

    with pytest.raises(ValueError):
        store.update_project_metadata(pid, {"status": "vibes"})
    with pytest.raises(ValueError):
        store.update_project_metadata(pid, {"lifecycle_phase": "warp"})
    with pytest.raises(ValueError):
        store.update_project_metadata(pid, {"priority": "urgent"})
    with pytest.raises(ValueError):
        store.update_project_metadata(pid, {"tags": "not-a-list"})
    with pytest.raises(ValueError):
        store.update_project_metadata(pid, {"tags": [1, 2]})
    with pytest.raises(ValueError):
        store.update_project_metadata(pid, {"other_factors": ["not", "an", "object"]})
    with pytest.raises(ValueError):
        store.update_project_metadata(pid, {"nonsense": "x"})

    row = store.get_project(pid)
    assert row["status"] == "active"
    assert row["tags"] == []


def test_update_project_metadata_unknown_project_returns_none(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    assert store.update_project_metadata("ghost", {"status": "paused"}) is None


def test_update_project_progress_sets_field_and_timestamp(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    pid = _seed(store, "/ws/alpha", "alpha")
    before = store.get_project(pid)

    updated = store.update_project_progress(pid, "wiring the catalog API")
    assert updated["current_progress"] == "wiring the catalog API"
    assert updated["updated_at"] > before["updated_at"]
    assert store.get_project(pid)["current_progress"] == "wiring the catalog API"


# --- Services ----------------------------------------------------------------


def test_service_reads_report_missing_database_without_creating_it(tmp_path: Path):
    missing = str(tmp_path / "absent.sqlite")

    listed = services.list_projects(missing)
    assert listed["ok"] is False
    assert listed["code"] == "database_not_found"
    assert listed["projects"] == []

    shown = services.get_project(missing, "alpha")
    assert shown["ok"] is False
    assert shown["code"] == "database_not_found"

    assert not (tmp_path / "absent.sqlite").exists()


def test_service_catalog_reads_report_schema_upgrade_without_mutating_v4_db(
    tmp_path: Path,
):
    db_path = tmp_path / "v4.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(V4_DDL)
    conn.executemany(
        "INSERT INTO schema_migrations VALUES (?, 'seeded')",
        [(version,) for version in range(1, 5)],
    )
    conn.execute(
        "INSERT INTO projects "
        "(id, name, path, relative_path, status, phase, summary, created_at, updated_at) "
        "VALUES ('p1', 'alpha', '/ws/alpha', 'alpha', 'active', 'active', 'summary', 't0', 't1')"
    )
    conn.commit()
    conn.close()
    before = db_path.read_bytes()

    listed = services.list_projects(str(db_path))
    shown = services.get_project(str(db_path), "p1")

    assert listed["ok"] is False
    assert listed["code"] == "schema_upgrade_required"
    assert shown["ok"] is False
    assert shown["code"] == "schema_upgrade_required"
    assert db_path.read_bytes() == before


def test_service_get_project_structured_errors(tmp_path: Path):
    db = str(tmp_path / "db.sqlite")
    store = services.open_store(db)
    _seed(store, "/ws/alpha", "alpha")
    _seed(store, "/root-a/app", "app")
    _seed(store, "/root-b/app", "app")
    store.close()

    missing = services.get_project(db, "ghost")
    assert missing == {
        "ok": False,
        "code": "project_not_found",
        "selector": "ghost",
        "project": None,
    }

    ambiguous = services.get_project(db, "app")
    assert ambiguous["ok"] is False
    assert ambiguous["code"] == "ambiguous_project"

    found = services.get_project(db, "alpha")
    assert found["ok"] is True
    assert found["project"]["relative_path"] == "alpha"


def test_service_update_envelopes(tmp_path: Path):
    db = str(tmp_path / "db.sqlite")
    store = services.open_store(db)
    _seed(store, "/ws/alpha", "alpha")
    store.close()

    empty = services.update_project_metadata(db, "alpha", {})
    assert empty["ok"] is False
    assert empty["code"] == "empty_update"

    invalid = services.update_project_metadata(db, "alpha", {"priority": "nope"})
    assert invalid["ok"] is False
    assert invalid["code"] == "invalid_input"

    unknown = services.update_project_metadata(db, "ghost", {"status": "paused"})
    assert unknown["ok"] is False
    assert unknown["code"] == "project_not_found"

    ok = services.update_project_metadata(
        db, "alpha", {"status": "paused", "tags": ["core"]}
    )
    assert ok["ok"] is True
    assert ok["project"]["status"] == "paused"
    assert ok["project"]["tags"] == ["core"]

    persisted = services.get_project(db, "alpha")
    assert persisted["project"]["status"] == "paused"


def test_service_update_progress_envelope(tmp_path: Path):
    db = str(tmp_path / "db.sqlite")
    store = services.open_store(db)
    _seed(store, "/ws/alpha", "alpha")
    store.close()

    missing = services.update_project_progress(db, "ghost", "text")
    assert missing["ok"] is False
    assert missing["code"] == "project_not_found"

    ok = services.update_project_progress(db, "/ws/alpha", "half done")
    assert ok["ok"] is True
    assert ok["project"]["current_progress"] == "half done"


def test_service_list_projects_envelope(tmp_path: Path):
    db = str(tmp_path / "db.sqlite")
    store = services.open_store(db)
    alpha = _seed(store, "/ws/alpha", "alpha")
    _seed(store, "/ws/beta", "beta")
    store.update_project_metadata(alpha, {"tags": ["infra"]})
    store.close()

    result = services.list_projects(db)
    assert result["ok"] is True
    assert result["count"] == 2

    filtered = services.list_projects(db, tag="infra")
    assert filtered["count"] == 1
    assert filtered["projects"][0]["tags"] == ["infra"]

    dumped = json.dumps(filtered)
    assert "other_factors" in dumped
