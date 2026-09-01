from __future__ import annotations

import json
from pathlib import Path

import anyio

from chrono_core import mcp_server, services
from chrono_core.cli import build_parser, main
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


def _seed_project(
    store: Store,
    workspace: Path,
    name: str,
    *,
    observations: list[str] | None = None,
    phase: str | None = None,
    summary: str | None = None,
) -> tuple[str, Path]:
    """Register *name* under *workspace* and return (project_id, project_path)."""
    project_path = workspace / name
    project_path.mkdir(parents=True, exist_ok=True)
    project = resolve_project(project_path, workspace_root=workspace)
    project_id = store.get_or_create_project(project)
    if observations:
        store.record_observations(project_id, None, "lesson", observations)
    if phase is not None or summary is not None:
        store.update_project_state(project_id, phase=phase, summary=summary)
    return project_id, project_path


def test_stronger_overlap_ranks_ahead_of_weaker(tmp_path: Path):
    workspace = tmp_path / "workspace"
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    core_id, _ = _seed_project(
        store,
        workspace,
        "core",
        observations=[
            "SQLite continuity storage with WAL journal",
            "SQLite schema migration rebuilds the FTS index",
        ],
    )
    kin_id, _ = _seed_project(
        store, workspace, "kin",
        observations=["SQLite continuity storage with WAL journal"],
    )
    distant_id, _ = _seed_project(
        store, workspace, "distant",
        observations=["SQLite deployment pipeline smoke tests"],
    )
    _seed_project(
        store, workspace, "unrelated",
        observations=["zebra quantum pancake rotation"],
    )

    results = store.find_similar_projects(core_id)

    assert [r["project_id"] for r in results] == [kin_id, distant_id]
    assert results[0]["score"] > results[1]["score"] > 0


def test_selected_project_and_zero_overlap_projects_are_excluded(tmp_path: Path):
    workspace = tmp_path / "workspace"
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    core_id, _ = _seed_project(
        store, workspace, "core", observations=["SQLite continuity storage"]
    )
    _seed_project(store, workspace, "unrelated", observations=["zebra quantum pancake"])

    results = store.find_similar_projects(core_id)

    ids = [r["project_id"] for r in results]
    assert core_id not in ids
    assert ids == []


def test_distilled_phase_and_summary_rank_without_observations(tmp_path: Path):
    workspace = tmp_path / "workspace"
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    core_id, _ = _seed_project(
        store,
        workspace,
        "core",
        phase="refining",
        summary="Extending the SQLite export pipeline",
    )
    peer_id, _ = _seed_project(
        store,
        workspace,
        "peer",
        phase="blocked",
        summary="Extending the SQLite export pipeline further",
    )
    _seed_project(store, workspace, "hollow")

    results = store.find_similar_projects(core_id)

    assert [r["project_id"] for r in results] == [peer_id]
    assert set(results[0]["shared_terms"]) >= {"sqlite", "export", "pipeline"}


def test_shared_terms_are_deterministic_and_contribution_ranked(tmp_path: Path):
    workspace = tmp_path / "workspace"
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    core_id, _ = _seed_project(
        store, workspace, "core", observations=["export export pipeline"]
    )
    kin_id, _ = _seed_project(
        store, workspace, "kin", observations=["export export pipeline"]
    )
    _seed_project(store, workspace, "isolated", observations=["unrelated zebra content"])

    first = store.find_similar_projects(core_id)
    second = store.find_similar_projects(core_id)

    assert first == second
    kin = next(r for r in first if r["project_id"] == kin_id)
    # "export" repeats in both documents, so its sublinear-TF weight — and
    # therefore its cosine contribution — exceeds the single-use "pipeline".
    assert kin["shared_terms"] == ["export", "pipeline"]


def test_empty_project_evidence_returns_no_matches(tmp_path: Path):
    workspace = tmp_path / "workspace"
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    blank_id, _ = _seed_project(store, workspace, "blank")
    _seed_project(store, workspace, "evidence", observations=["SQLite continuity storage"])

    assert store.find_similar_projects(blank_id) == []


def test_non_positive_limits_return_empty_results(tmp_path: Path):
    workspace = tmp_path / "workspace"
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    core_id, _ = _seed_project(store, workspace, "core", observations=["SQLite storage"])
    _seed_project(store, workspace, "kin", observations=["SQLite storage"])

    assert store.find_similar_projects(core_id, limit=0) == []
    assert store.find_similar_projects(core_id, limit=-3) == []


def test_two_projects_with_only_shared_evidence_still_match(tmp_path: Path):
    workspace = tmp_path / "workspace"
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    core_id, _ = _seed_project(store, workspace, "core", observations=["SQLite storage"])
    peer_id, _ = _seed_project(store, workspace, "peer", observations=["SQLite storage"])

    results = store.find_similar_projects(core_id)

    assert [result["project_id"] for result in results] == [peer_id]
    assert results[0]["score"] > 0
    assert results[0]["shared_terms"] == ["sqlite", "storage"]


def test_service_reports_unknown_project_without_mutation(tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    store = Store(db_path)
    store.init_schema()
    _seed_project(store, workspace, "registered", observations=["SQLite storage"])
    store.close()
    mystery = workspace / "mystery"
    mystery.mkdir()

    before = Store(db_path, read_only=True).list_projects()
    result = services.find_similar_projects(
        str(db_path), str(mystery), workspace_root=str(workspace)
    )
    after = Store(db_path, read_only=True).list_projects()

    assert result["ok"] is False
    assert "unknown project" in result["error"]
    assert result["results"] == []
    assert before == after


def test_service_reports_missing_database_without_creating_it(tmp_path: Path):
    db_path = tmp_path / "missing" / "chrono.db"
    cwd = tmp_path / "workspace" / "core"
    cwd.mkdir(parents=True)

    result = services.find_similar_projects(str(db_path), str(cwd))

    assert result["ok"] is False
    assert result["error"] == "database not found"
    assert not db_path.exists()


def test_service_envelope_matches_contract(tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    store = Store(db_path)
    store.init_schema()
    core_id, core_dir = _seed_project(
        store, workspace, "core", observations=["SQLite continuity storage"]
    )
    kin_id, _ = _seed_project(
        store, workspace, "kin", observations=["SQLite continuity storage"]
    )
    _seed_project(store, workspace, "isolated", observations=["zebra quantum pancake"])
    store.close()

    result = services.find_similar_projects(
        str(db_path), str(core_dir), workspace_root=str(workspace)
    )

    assert result == {
        "ok": True,
        "project_id": core_id,
        "count": 1,
        "results": [
            {
                "project_id": kin_id,
                "project_name": "kin",
                "project_path": str(workspace / "kin"),
                "phase": None,
                "summary": None,
                "score": result["results"][0]["score"],
                "shared_terms": result["results"][0]["shared_terms"],
            }
        ],
    }
    assert isinstance(result["results"][0]["score"], float)
    assert result["results"][0]["shared_terms"]


def test_similar_parser_defaults():
    args = build_parser().parse_args(["similar"])

    assert args.command == "similar"
    assert args.cwd == "."
    assert args.limit == 5
    assert args.db_path is None


def test_similar_main_emits_service_envelope(tmp_path: Path, capsys):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    store = Store(db_path)
    store.init_schema()
    core_id, core_dir = _seed_project(
        store, workspace, "core", observations=["SQLite continuity storage"]
    )
    kin_id, _ = _seed_project(
        store, workspace, "kin", observations=["SQLite continuity storage"]
    )
    _seed_project(store, workspace, "isolated", observations=["zebra quantum pancake"])
    store.close()

    code = main(
        [
            "similar",
            "--cwd", str(core_dir),
            "--workspace-root", str(workspace),
            "--limit", "1",
            "--db-path", str(db_path),
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["ok"] is True
    assert data["project_id"] == core_id
    assert data["count"] == 1
    assert data["results"][0]["project_id"] == kin_id


def test_similar_main_fails_for_unknown_project(tmp_path: Path, capsys):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    store = Store(db_path)
    store.init_schema()
    _seed_project(store, workspace, "registered", observations=["SQLite storage"])
    store.close()
    mystery = workspace / "mystery"
    mystery.mkdir()

    code = main(
        [
            "similar",
            "--cwd", str(mystery),
            "--workspace-root", str(workspace),
            "--db-path", str(db_path),
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert code == 1
    assert data["ok"] is False


def test_similar_main_non_positive_limit_is_empty(tmp_path: Path, capsys):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    store = Store(db_path)
    store.init_schema()
    core_id, core_dir = _seed_project(
        store, workspace, "core", observations=["SQLite storage"]
    )
    _seed_project(store, workspace, "kin", observations=["SQLite storage"])
    store.close()

    code = main(
        [
            "similar",
            "--cwd", str(core_dir),
            "--workspace-root", str(workspace),
            "--limit", "0",
            "--db-path", str(db_path),
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["ok"] is True
    assert data["count"] == 0
    assert data["results"] == []


def test_mcp_handle_find_similar_projects(tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    store = Store(db_path)
    store.init_schema()
    core_id, core_dir = _seed_project(
        store, workspace, "core", observations=["SQLite continuity storage"]
    )
    kin_id, _ = _seed_project(
        store, workspace, "kin", observations=["SQLite continuity storage"]
    )
    _seed_project(store, workspace, "isolated", observations=["zebra quantum pancake"])
    store.close()

    result = mcp_server.handle_find_similar_projects(
        str(core_dir), workspace_root=str(workspace), db_path=str(db_path)
    )

    expected = services.find_similar_projects(
        str(db_path), str(core_dir), workspace_root=str(workspace)
    )
    assert result == expected
    assert result["ok"] is True
    assert result["project_id"] == core_id
    assert result["count"] == 1
    assert result["results"][0]["project_id"] == kin_id


def test_find_similar_projects_tool_is_registered():
    tools = anyio.run(mcp_server.mcp.list_tools)
    tool = next(t for t in tools if t.name == "chrono_core_find_similar_projects")
    assert {"cwd", "workspace_root", "db_path", "limit"} <= set(
        tool.inputSchema.get("properties", {})
    )
