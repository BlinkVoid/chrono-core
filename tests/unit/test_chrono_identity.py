from __future__ import annotations

import tomllib
from pathlib import Path

from chrono_core.integrations.gearcore import build_gearcore_install_plan

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_product_and_gearcore_registration_use_chrono_core_identity():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert project["name"] == "chrono-core"
    assert "mcp>=1.0,<2" in project["dependencies"]
    assert project["scripts"]["chrono"] == "chrono_core.cli:main"
    assert project["scripts"]["chrono-mcp"] == "chrono_core.mcp_server:main"

    plan = build_gearcore_install_plan(skill_path=REPO_ROOT / "skills" / "chrono-core")
    plan_data = plan.to_dict()
    assert plan_data["skill_path"].endswith("skills/chrono-core")
    assert plan_data["mcp_server"] == {
        "id": "chrono-core",
        "type": "stdio",
        "command": "chrono-mcp",
    }
