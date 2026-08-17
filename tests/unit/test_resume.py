from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.resume import format_resume, get_resume_context
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


def test_get_resume_context_for_unknown_project(tmp_path: Path):
    args = Namespace(
        cwd=str(tmp_path / "workspace" / "example"),
        workspace_root=str(tmp_path / "workspace"),
        db_path=str(tmp_path / "test.db"),
    )
    (tmp_path / "workspace" / "example").mkdir(parents=True)
    context = get_resume_context(args)
    assert context.project_name == "unknown"


def test_get_resume_context_after_handoff(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.init_schema()
    (tmp_path / "workspace" / "example").mkdir(parents=True)
    project = resolve_project(
        tmp_path / "workspace" / "example", workspace_root=tmp_path / "workspace"
    )
    store.get_or_create_project(project)

    payload = HandoffPayload(summary="Latest.", next_actions=["Act"])
    session_id = store.create_session(project.project_id, payload, GitState())
    store.record_next_actions(project.project_id, session_id, payload.next_actions)

    args = Namespace(
        cwd=str(tmp_path / "workspace" / "example"),
        workspace_root=str(tmp_path / "workspace"),
        db_path=str(tmp_path / "test.db"),
    )
    context = get_resume_context(args)

    assert context.project_name == "example"
    assert context.summary == "Latest."
    assert len(context.next_actions) == 1


def test_format_resume_text_output():
    from chrono_core.domain.models import ResumeContext

    context = ResumeContext(
        project_id="x",
        project_name="Example",
        project_path="/x",
        current_status="Active.",
        summary="Latest session.",
        active_blockers=[{"title": "B"}],
        next_actions=[{"text": "A"}],
        recent_decisions=[{"title": "D"}],
    )
    text = format_resume(context)
    assert "Example" in text
    assert "Latest session." in text
    assert "B" in text
    assert "A" in text
    assert "D" in text


def test_format_resume_json_output():
    from chrono_core.domain.models import ResumeContext

    context = ResumeContext(project_id="x", project_name="Example", project_path="/x")
    text = format_resume(context, as_json=True)
    assert '"project_name": "Example"' in text


def test_resume_finds_project_recorded_under_a_different_workspace_root(tmp_path: Path):
    """A project keeps its continuity when the workspace root changes.

    project_id is a hash of the workspace-*relative* path, so the same
    directory resolves to different ids under different roots. The write
    path already reconciles on absolute path; reads must agree, or a
    handoff captured under one root is invisible from the other.
    """
    project_dir = tmp_path / "workspace" / "cores" / "example"
    (project_dir / ".git").mkdir(parents=True)
    db_path = tmp_path / "test.db"

    store = Store(db_path)
    store.init_schema()
    inner = resolve_project(project_dir, workspace_root=tmp_path / "workspace" / "cores")
    stored_id = store.get_or_create_project(inner)
    payload = HandoffPayload(summary="Captured under the inner root.")
    store.create_session(stored_id, payload, GitState())

    outer = resolve_project(project_dir, workspace_root=tmp_path / "workspace")
    assert outer.project_id != stored_id, "precondition: the roots must disagree on id"

    context = get_resume_context(
        Namespace(
            cwd=str(project_dir),
            workspace_root=str(tmp_path / "workspace"),
            db_path=str(db_path),
        )
    )

    assert context.project_name == "example"
    assert context.summary == "Captured under the inner root."
