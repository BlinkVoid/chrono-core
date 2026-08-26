from __future__ import annotations

import os
from pathlib import Path

from chrono_core import mcp_server
from chrono_core.cli import build_parser
from chrono_core.config import default_db_path, default_workspace_root


def test_env_overrides_win(monkeypatch):
    monkeypatch.setenv("CHRONO_WORKSPACE_ROOT", "/custom/workspace")
    assert default_workspace_root() == "/custom/workspace"


def test_legacy_var_still_accepted(monkeypatch):
    monkeypatch.delenv("CHRONO_WORKSPACE_ROOT", raising=False)
    monkeypatch.setenv("CONTINUITY_WORKSPACE_ROOT", "/legacy/workspace")
    assert default_workspace_root() == "/legacy/workspace"


def test_no_personal_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("CHRONO_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("CONTINUITY_WORKSPACE_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert str(Path.home()) not in default_workspace_root()
    assert Path(default_workspace_root()) == Path(os.getcwd())


def test_cli_workspace_root_default_respects_env(monkeypatch):
    monkeypatch.setenv("CHRONO_WORKSPACE_ROOT", "/custom/workspace")
    args = build_parser().parse_args(["resolve"])
    assert args.workspace_root == "/custom/workspace"


def test_db_path_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONO_DB_PATH", str(tmp_path / "x.db"))
    assert default_db_path() == str(tmp_path / "x.db")


def test_db_path_default_under_home(monkeypatch):
    monkeypatch.delenv("CHRONO_DB_PATH", raising=False)
    assert default_db_path().endswith(".local/share/chrono-core/chrono.db")


def test_mcp_resolve_project_respects_env(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "ws"
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    monkeypatch.setenv("CHRONO_WORKSPACE_ROOT", str(workspace))

    result = mcp_server.handle_resolve_project(str(project))

    assert result["name"] == "example"
    assert result["relative_path"] == "example"
