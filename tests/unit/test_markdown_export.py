from __future__ import annotations

from pathlib import Path

from continuity_core.domain.models import GitState, HandoffPayload
from continuity_core.export.markdown import export_markdown
from continuity_core.store.store import Store
from continuity_core.workspace.resolver import resolve_project


def test_export_markdown_writes_project_index_and_project_page(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project_path = workspace / "example"
    project_path.mkdir(parents=True)
    store = Store(tmp_path / "continuity.db")
    store.init_schema()
    project = resolve_project(project_path, workspace_root=workspace)
    store.get_or_create_project(project)
    payload = HandoffPayload(
        summary="Latest session.",
        next_actions=["Ship export"],
        decisions=[{"title": "Use Markdown", "rationale": "Readable"}],
        blockers=[{"title": "Need review", "status": "open"}],
    )
    session_id = store.create_session(project.project_id, payload, GitState(branch="main"))
    store.record_next_actions(project.project_id, session_id, payload.next_actions)
    store.record_decisions(project.project_id, session_id, payload.decisions)
    store.record_blockers(project.project_id, session_id, payload.blockers)

    result = export_markdown(store, tmp_path / "export")

    assert result["ok"] is True
    assert result["exported_count"] == 1
    index = (tmp_path / "export" / "Projects.md").read_text(encoding="utf-8")
    assert "# Projects" in index
    assert "- [example](projects/example-" in index

    project_page = Path(result["projects"][0]["path"])
    text = project_page.read_text(encoding="utf-8")
    assert "# example" in text
    assert "Latest session." in text
    assert "Ship export" in text
    assert "Use Markdown" in text
    assert "Need review" in text
