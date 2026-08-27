from __future__ import annotations

import json
from pathlib import Path

import pytest

from chrono_core import mcp_server, services
from chrono_core.cli import main
from chrono_core.management.patterns import mine_pattern_candidates


def _project(workspace: Path, name: str) -> Path:
    project = workspace / name
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    return project


def test_service_records_semantic_observation_for_safe_mining(tmp_path: Path):
    recorder = getattr(services, "record_semantic_observation", None)
    assert callable(recorder), "semantic observation service is not implemented"
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    project = _project(workspace, "alpha")

    result = recorder(
        str(db_path),
        str(project),
        content="Bounded retry budget",
        kind="lesson",
        workspace_root=str(workspace),
    )

    assert result["ok"] is True
    assert result["recorded_count"] == 1
    assert result["observation"]["id"].startswith("obs_")
    assert result["observation"]["kind"] == "lesson"
    assert result["observation"]["content"] == "Bounded retry budget"
    assert result["observation"]["source"] == "direct"
    assert result["observation"]["session_id"] is None


@pytest.mark.parametrize("kind", ["file", "test", "risk", "workspace_metadata"])
def test_service_rejects_nonsemantic_observation_kinds(tmp_path: Path, kind: str):
    recorder = getattr(services, "record_semantic_observation", None)
    assert callable(recorder), "semantic observation service is not implemented"
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    project = _project(workspace, "alpha")

    result = recorder(
        str(db_path),
        str(project),
        content="Operational noise",
        kind=kind,
        workspace_root=str(workspace),
    )

    assert result["ok"] is False
    assert "semantic observation kind" in result["error"]
    assert not db_path.exists()


def test_service_rejects_blank_semantic_observation(tmp_path: Path):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    project = _project(workspace, "alpha")

    result = services.record_semantic_observation(
        str(db_path),
        str(project),
        content="  ",
        workspace_root=str(workspace),
    )

    assert result == {
        "ok": False,
        "kind": "lesson",
        "error": "content must not be blank",
    }
    assert not db_path.exists()


def test_direct_observations_feed_cross_project_mining(tmp_path: Path):
    recorder = getattr(services, "record_semantic_observation", None)
    assert callable(recorder), "semantic observation service is not implemented"
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    for name in ("alpha", "beta"):
        recorder(
            str(db_path),
            str(_project(workspace, name)),
            content="Bounded retry budget",
            kind="lesson",
            workspace_root=str(workspace),
        )

    result = mine_pattern_candidates(services.open_store(str(db_path)), min_projects=2)

    assert "Recurring pattern: bounded retry budget" in {
        pattern["title"] for pattern in result["mined"]
    }


def test_observe_cli_records_a_pattern_candidate(tmp_path: Path, capsys):
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    project = _project(workspace, "alpha")

    try:
        rc = main(
            [
                "observe",
                "Single provider client boundary",
                "--kind",
                "pattern_candidate",
                "--cwd",
                str(project),
                "--workspace-root",
                str(workspace),
                "--db-path",
                str(db_path),
            ]
        )
    except SystemExit as exc:
        pytest.fail(f"observe command is not registered: {exc}")

    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["observation"]["kind"] == "pattern_candidate"


def test_mcp_record_observation_wraps_the_shared_service(tmp_path: Path):
    handler = getattr(mcp_server, "handle_record_observation", None)
    tool = getattr(mcp_server, "record_observation_tool", None)
    assert callable(handler), "MCP observation handler is not implemented"
    assert callable(tool), "MCP observation tool is not implemented"
    workspace = tmp_path / "workspace"
    db_path = tmp_path / "chrono.db"
    project = _project(workspace, "alpha")

    result = tool(
        str(project),
        "Fail closed at trust boundaries",
        kind="pattern",
        workspace_root=str(workspace),
        db_path=str(db_path),
    )

    assert result["ok"] is True
    assert result["observation"]["kind"] == "pattern"
