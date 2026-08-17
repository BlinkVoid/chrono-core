from __future__ import annotations

import json
from pathlib import Path

from chrono_core import mcp_server
from chrono_core.cli import build_parser, main
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


def _seed_observations(store: Store, workspace: Path, name: str = "example") -> str:
    store.init_schema()
    project_path = workspace / name
    project_path.mkdir(parents=True, exist_ok=True)
    project = resolve_project(project_path, workspace_root=workspace)
    project_id = store.get_or_create_project(project)
    store.record_observations(
        project_id,
        None,
        "risk",
        ["Credential rotation is unverified", "Deploy pipeline lacks smoke test"],
    )
    return project_id


def test_search_observations_finds_matching_content(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    project_id = _seed_observations(store, tmp_path / "workspace")

    results = store.search_observations("credential")

    assert len(results) == 1
    assert results[0]["project_id"] == project_id
    assert "Credential rotation" in results[0]["content"]


def test_search_observations_scopes_by_project(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    project_a = _seed_observations(store, tmp_path / "workspace", "alpha")
    project_b = _seed_observations(store, tmp_path / "workspace", "beta")

    results = store.search_observations("credential", project_id=project_b)

    assert len(results) == 1
    assert results[0]["project_id"] == project_b
    assert project_a != project_b


def test_search_observations_returns_empty_for_no_match(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    _seed_observations(store, tmp_path / "workspace")

    assert store.search_observations("nonexistentterm") == []


def test_init_schema_rebuilds_fts_for_rows_indexed_before_migration(tmp_path: Path):
    """Rows written before the FTS migration become searchable after re-init."""
    store = Store(tmp_path / "test.db")
    _seed_observations(store, tmp_path / "workspace")

    conn = store._connect()
    conn.execute("INSERT INTO observation_fts(observation_fts) VALUES('delete-all')")
    conn.execute("DELETE FROM schema_migrations WHERE version >= 2")
    conn.commit()
    store.close()

    fresh = Store(tmp_path / "test.db")
    fresh.init_schema()

    assert len(fresh.search_observations("credential")) == 1


def test_search_parser_defaults():
    args = build_parser().parse_args(["search", "credential"])

    assert args.command == "search"
    assert args.query == "credential"
    assert args.project_id is None
    assert args.limit == 20


def test_search_main_emits_json(tmp_path: Path, capsys):
    db_path = tmp_path / "chrono.db"
    _seed_observations(Store(db_path), tmp_path / "workspace")

    code = main(["search", "credential", "--db-path", str(db_path)])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["ok"] is True
    assert data["count"] == 1
    assert "Credential rotation" in data["results"][0]["content"]


def test_mcp_handle_search_observations(tmp_path: Path):
    db_path = tmp_path / "chrono.db"
    project_id = _seed_observations(Store(db_path), tmp_path / "workspace")

    result = mcp_server.handle_search_observations("credential", db_path=str(db_path))

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["results"][0]["project_id"] == project_id
