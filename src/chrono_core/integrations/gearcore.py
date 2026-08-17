from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SKILL_PATH = REPO_ROOT / "skills" / "chrono-core"
DEFAULT_MCP_SERVER_ID = "chrono-core"
DEFAULT_MCP_COMMAND = "chrono-mcp"


@dataclass(frozen=True)
class GearCoreCommand:
    """A GearCore command that can be executed by an operator."""

    description: str
    argv: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "argv": self.argv,
            "shell": shlex.join(self.argv),
        }


@dataclass(frozen=True)
class GearCoreInstallPlan:
    """Registration plan for exposing Chrono Core through GearCore."""

    scope: str
    skill_path: Path
    symlink: bool
    project_root: Path | None
    mcp_server_id: str
    mcp_command: str
    commands: list[GearCoreCommand]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "scope": self.scope,
            "project_root": str(self.project_root) if self.project_root else None,
            "skill_path": str(self.skill_path),
            "symlink": self.symlink,
            "mcp_server": {
                "id": self.mcp_server_id,
                "type": "stdio",
                "command": self.mcp_command,
            },
            "commands": [command.to_dict() for command in self.commands],
        }


def build_gearcore_install_plan(
    *,
    scope: str = "global",
    project_root: str | Path | None = None,
    skill_path: str | Path | None = None,
    symlink: bool = True,
    mcp_server_id: str = DEFAULT_MCP_SERVER_ID,
    mcp_command: str = DEFAULT_MCP_COMMAND,
) -> GearCoreInstallPlan:
    """Build explicit GearCore registration commands without mutating config."""
    if scope not in {"global", "project"}:
        raise ValueError("scope must be 'global' or 'project'")
    if scope == "project" and project_root is None:
        raise ValueError("project_root is required when scope is 'project'")

    resolved_skill_path = Path(skill_path) if skill_path else DEFAULT_SKILL_PATH
    resolved_project_root = Path(project_root) if project_root else None

    prefix = ["gearcore"]
    if resolved_project_root is not None:
        prefix.extend(["--project", str(resolved_project_root)])

    skill_argv = [*prefix, "add-skill", "--scope", scope]
    if symlink:
        skill_argv.append("--symlink")
    skill_argv.append(str(resolved_skill_path))

    mcp_argv = [
        *prefix,
        "add-mcp",
        "--id",
        mcp_server_id,
        "--type",
        "stdio",
        "--command",
        mcp_command,
        "--scope",
        scope,
    ]

    return GearCoreInstallPlan(
        scope=scope,
        skill_path=resolved_skill_path,
        symlink=symlink,
        project_root=resolved_project_root,
        mcp_server_id=mcp_server_id,
        mcp_command=mcp_command,
        commands=[
            GearCoreCommand("Register Chrono Core skill", skill_argv),
            GearCoreCommand("Register Chrono Core MCP server", mcp_argv),
        ],
    )
