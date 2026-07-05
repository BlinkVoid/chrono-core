from __future__ import annotations

from pathlib import Path

from continuity_core import mcp_server
from continuity_core.cli import build_parser
from continuity_core.config import default_workspace_root


def test_default_workspace_root_reads_env_override(monkeypatch):
    monkeypatch.setenv("CONTINUITY_WORKSPACE_ROOT", "/custom/workspace")
    assert default_workspace_root() == "/custom/workspace"


def test_default_workspace_root_falls_back_without_env(monkeypatch):
    monkeypatch.delenv("CONTINUITY_WORKSPACE_ROOT", raising=False)
    assert default_workspace_root() == "~/workspace"


def test_cli_workspace_root_default_respects_env(monkeypatch):
    monkeypatch.setenv("CONTINUITY_WORKSPACE_ROOT", "/custom/workspace")
    args = build_parser().parse_args(["resolve"])
    assert args.workspace_root == "/custom/workspace"


def test_mcp_resolve_project_respects_env(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "ws"
    project = workspace / "example"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    monkeypatch.setenv("CONTINUITY_WORKSPACE_ROOT", str(workspace))

    result = mcp_server.handle_resolve_project(str(project))

    assert result["name"] == "example"
    assert result["relative_path"] == "example"
