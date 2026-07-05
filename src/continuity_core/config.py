from __future__ import annotations

import os
from pathlib import Path

FALLBACK_WORKSPACE_ROOT = "~/workspace"


def default_workspace_root() -> str:
    """Workspace root, overridable via CONTINUITY_WORKSPACE_ROOT.

    Read per call (not at import) so the CLI and MCP server pick up the
    environment they were launched with.
    """
    return os.environ.get("CONTINUITY_WORKSPACE_ROOT") or FALLBACK_WORKSPACE_ROOT


def default_db_path() -> str:
    """Canonical continuity database location shared by the CLI and MCP server."""
    return str(Path.home() / ".local" / "share" / "continuity-core" / "continuity.db")
