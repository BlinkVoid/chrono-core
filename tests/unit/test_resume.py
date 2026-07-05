from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from continuity_core.domain.models import GitState, HandoffPayload
from continuity_core.resume import format_resume, get_resume_context
from continuity_core.store.store import Store
from continuity_core.workspace.resolver import resolve_project


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
    from continuity_core.domain.models import ResumeContext

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
    from continuity_core.domain.models import ResumeContext

    context = ResumeContext(project_id="x", project_name="Example", project_path="/x")
    text = format_resume(context, as_json=True)
    assert '"project_name": "Example"' in text
