from __future__ import annotations

from pathlib import Path

DEFAULT_WORKSPACE_ROOT = "~/workspace"


def default_db_path() -> str:
    """Canonical continuity database location shared by the CLI and MCP server."""
    return str(Path.home() / ".local" / "share" / "continuity-core" / "continuity.db")
