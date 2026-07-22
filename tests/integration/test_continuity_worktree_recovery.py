from __future__ import annotations

import shutil
from argparse import Namespace

import pytest

from continuity_core.domain.models import GitState, HandoffPayload
from continuity_core.mcp_server import handle_get_resume_context
from continuity_core.resume import get_resume_context
from continuity_core.store.store import Store
from continuity_core.workspace.resolver import resolve_project


def test_resume_rejects_or_recovers_missing_active_tmp_worktree(tmp_path):
    """BUG-Hub-071: never advertise a vanished worktree as resumable."""
    workspace = tmp_path / "workspace"
    volatile_worktree = workspace / "tmp" / "hive-v2-assess"
    volatile_worktree.mkdir(parents=True)
    (volatile_worktree / ".git").write_text("gitdir: /tmp/missing-admin-dir\n")
    db_path = tmp_path / "continuity.db"

    project = resolve_project(volatile_worktree, workspace_root=workspace)
    store = Store(db_path)
    store.init_schema()
    store.get_or_create_project(project)
    store.create_session(
        project.project_id,
        HandoffPayload(summary="Resume the release from this worktree."),
        GitState(branch="hive/v2-transition", head="abc123"),
    )
    shutil.rmtree(volatile_worktree)

    args = Namespace(
        cwd=str(volatile_worktree),
        workspace_root=str(workspace),
        db_path=str(db_path),
    )
    with pytest.raises(FileNotFoundError, match="stored resume path no longer exists"):
        get_resume_context(args)
    with pytest.raises(FileNotFoundError, match="stored resume path no longer exists"):
        handle_get_resume_context(
            str(volatile_worktree),
            workspace_root=str(workspace),
            db_path=str(db_path),
        )
