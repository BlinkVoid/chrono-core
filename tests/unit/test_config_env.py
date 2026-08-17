from __future__ import annotations

from pathlib import Path

from chrono_core import mcp_server
from chrono_core.cli import build_parser
from chrono_core.config import default_workspace_root


def test_default_workspace_root_reads_env_override(monkeypatch):
    monkeypatch.setenv("CHRONO_WORKSPACE_ROOT", "/custom/workspace")
    assert default_workspace_root() == "/custom/workspace"


def test_default_workspace_root_falls_back_without_env(monkeypatch):
    monkeypatch.delenv("CHRONO_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("CONTINUITY_WORKSPACE_ROOT", raising=False)
    assert default_workspace_root() == "~/workspace"


def test_default_workspace_root_accepts_legacy_env_as_fallback(monkeypatch):
    monkeypatch.delenv("CHRONO_WORKSPACE_ROOT", raising=False)
    monkeypatch.setenv("CONTINUITY_WORKSPACE_ROOT", "/legacy/workspace")
    assert default_workspace_root() == "/legacy/workspace"


def test_cli_workspace_root_default_respects_env(monkeypatch):
    monkeypatch.setenv("CHRONO_WORKSPACE_ROOT", "/custom/workspace")
    args = build_parser().parse_args(["resolve"])
    assert args.workspace_root == "/custom/workspace"


def test_mcp_resolve_project_respects_env(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "ws"
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    monkeypatch.setenv("CHRONO_WORKSPACE_ROOT", str(workspace))

    result = mcp_server.handle_resolve_project(str(project))

    assert result["name"] == "example"
    assert result["relative_path"] == "example"
