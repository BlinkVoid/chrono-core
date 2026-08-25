from __future__ import annotations

import os
from pathlib import Path


def default_workspace_root() -> str:
    """Workspace root: env override, else cwd (no machine-specific fallback).

    Read per call (not at import) so the CLI and MCP server pick up the
    environment they were launched with. CONTINUITY_WORKSPACE_ROOT is
    accepted as a legacy fallback; other tools in this workspace rely on
    CHRONO_WORKSPACE_ROOT being set, so the cwd fallback is a last resort.
    """
    return (
        os.environ.get("CHRONO_WORKSPACE_ROOT")
        or os.environ.get("CONTINUITY_WORKSPACE_ROOT")
        or os.getcwd()
    )


def default_db_path() -> str:
    """Continuity DB: CHRONO_DB_PATH override at call time, else canonical home location."""
    override = os.environ.get("CHRONO_DB_PATH")
    if override:
        return override
    return str(Path.home() / ".local" / "share" / "chrono-core" / "chrono.db")
