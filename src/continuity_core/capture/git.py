from __future__ import annotations

import subprocess
from pathlib import Path

from continuity_core.domain.models import GitState


def read_git_state(project_path: Path) -> GitState:
    """Return git branch, head, and dirty state for *project_path*."""
    if not (project_path / ".git").exists():
        return GitState()

    try:
        branch = (
            subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=False,
            )
            .stdout.strip()
            or None
        )
        head = (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=False,
            )
            .stdout.strip()
            or None
        )
        dirty = (
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=False,
            )
            .stdout.strip()
            != ""
        )
        return GitState(branch=branch, head=head, dirty=dirty)
    except (OSError, subprocess.SubprocessError):
        return GitState()
