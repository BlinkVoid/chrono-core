from __future__ import annotations

from pathlib import Path

from continuity_core.store.store import Store
from continuity_core.workspace.resolver import make_project_id, resolve_project


def test_make_project_id_is_deterministic():
    assert make_project_id("projects/incubator/example") == make_project_id("projects/incubator/example")


def test_make_project_id_normalizes_separators():
    assert make_project_id("Hub\\incubator\\example") == make_project_id("projects/incubator/example")


def test_store_get_or_create_project(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.init_schema()

    project = resolve_project(
        tmp_path / "workspace" / "example", workspace_root=tmp_path / "workspace"
    )
    project_id = store.get_or_create_project(project)

    assert project_id == project.project_id
    row = (
        store._connect()
        .execute("SELECT name, path FROM projects WHERE id = ?", (project_id,))
        .fetchone()
    )
    assert row["name"] == "example"


def test_store_creates_session_and_records(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.init_schema()

    project = resolve_project(
        tmp_path / "workspace" / "example", workspace_root=tmp_path / "workspace"
    )
    project_id = store.get_or_create_project(project)

    from continuity_core.domain.models import GitState, HandoffPayload

    payload = HandoffPayload(
        summary="Implemented handoff.",
        files_changed=["src/cli.py"],
        tests=["pytest: passed"],
        decisions=[{"title": "Use SQLite", "rationale": "Simplicity"}],
        blockers=[{"title": "Need credentials", "status": "open"}],
        next_actions=["Add resume command"],
    )
    git = GitState(branch="main", head="abc123", dirty=False)
    session_id = store.create_session(project_id, payload, git)

    store.record_decisions(project_id, session_id, payload.decisions)
    store.record_blockers(project_id, session_id, payload.blockers)
    store.record_next_actions(project_id, session_id, payload.next_actions)
    store.record_observations(project_id, session_id, "file", payload.files_changed)

    conn = store._connect()
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM blockers").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM next_actions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1


def test_store_get_resume_context(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.init_schema()

    project = resolve_project(
        tmp_path / "workspace" / "example", workspace_root=tmp_path / "workspace"
    )
    project_id = store.get_or_create_project(project)

    from continuity_core.domain.models import GitState, HandoffPayload

    payload = HandoffPayload(
        summary="First session.",
        blockers=[{"title": "Blocked", "status": "open"}],
        next_actions=["Do thing"],
        decisions=[{"title": "Decide", "rationale": "Why not"}],
    )
    session_id = store.create_session(project_id, payload, GitState())
    store.record_blockers(project_id, session_id, payload.blockers)
    store.record_next_actions(project_id, session_id, payload.next_actions)
    store.record_decisions(project_id, session_id, payload.decisions)

    context = store.get_resume_context(project_id)

    assert context.project_name == "example"
    assert context.summary == "First session."
    assert len(context.active_blockers) == 1
    assert len(context.next_actions) == 1
    assert len(context.recent_decisions) == 1


def test_upsert_same_path_different_id_reuses_existing_project(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.init_schema()

    first_id = store.upsert_project(
        project_id="alpha-1111111111",
        name="alpha",
        path="/ws/alpha",
        relative_path="alpha",
    )
    returned_id = store.upsert_project(
        project_id="alpha-2222222222",
        name="alpha-renamed",
        path="/ws/alpha",
        relative_path="deeper/alpha",
    )

    assert returned_id == first_id
    conn = store._connect()
    assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
    row = conn.execute("SELECT id, name FROM projects WHERE path = '/ws/alpha'").fetchone()
    assert row["id"] == first_id
    assert row["name"] == "alpha-renamed"
