from __future__ import annotations

import json
from pathlib import Path

from chrono_core.cli import build_parser, main
from chrono_core.integrations.gearcore import build_gearcore_install_plan


def test_gearcore_install_plan_defaults_to_global_symlink_registration():
    plan = build_gearcore_install_plan()
    data = plan.to_dict()

    assert data["ok"] is True
    assert data["scope"] == "global"
    assert data["skill_path"].endswith("skills/chrono-core")
    assert data["mcp_server"] == {
        "id": "chrono-core",
        "type": "stdio",
        "command": "chrono-mcp",
    }
    assert data["commands"][0]["argv"] == [
        "gearcore",
        "add-skill",
        "--scope",
        "global",
        "--symlink",
        data["skill_path"],
    ]
    assert data["commands"][1]["argv"] == [
        "gearcore",
        "add-mcp",
        "--id",
        "chrono-core",
        "--type",
        "stdio",
        "--command",
        "chrono-mcp",
        "--scope",
        "global",
    ]


def test_gearcore_install_plan_supports_project_scope(tmp_path: Path):
    plan = build_gearcore_install_plan(scope="project", project_root=tmp_path, symlink=False)
    data = plan.to_dict()

    assert data["scope"] == "project"
    assert data["project_root"] == str(tmp_path)
    assert data["commands"][0]["argv"] == [
        "gearcore",
        "--project",
        str(tmp_path),
        "add-skill",
        "--scope",
        "project",
        data["skill_path"],
    ]
    assert data["commands"][1]["argv"][:3] == ["gearcore", "--project", str(tmp_path)]


def test_gearcore_project_scope_requires_project_root():
    try:
        build_gearcore_install_plan(scope="project")
    except ValueError as exc:
        assert "project_root" in str(exc)
    else:
        raise AssertionError("project scope should require project_root")


def test_gearcore_install_plan_parser_defaults():
    args = build_parser().parse_args(["gearcore", "install-plan"])

    assert args.command == "gearcore"
    assert args.gearcore_command == "install-plan"
    assert args.scope == "global"
    assert args.symlink is True
    assert args.mcp_command == "chrono-mcp"


def test_gearcore_install_plan_main_emits_json(capsys):
    code = main(["gearcore", "install-plan", "--mcp-command", "custom-chrono-mcp"])

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert code == 0
    assert data["mcp_server"]["command"] == "custom-chrono-mcp"
    assert data["commands"][1]["argv"][7] == "custom-chrono-mcp"
