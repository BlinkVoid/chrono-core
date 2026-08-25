from __future__ import annotations

import subprocess
from argparse import Namespace
from pathlib import Path

from chrono_core import mcp_server, services
from chrono_core.capture.git import read_git_state
from chrono_core.capture.handoff import build_handoff_payload
from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.export.markdown import _render_escape
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


def _seed_busy_project(db_path: Path, workspace: Path) -> Path:
    store = Store(db_path)
    store.init_schema()
    project_path = workspace / "example"
    project_path.mkdir(parents=True)
    (project_path / ".git").mkdir()
    project = resolve_project(project_path, workspace_root=workspace)
    project_id = store.get_or_create_project(project)
    payload = HandoffPayload(
        summary="A fairly long session summary describing everything that happened. " * 5,
        decisions=[{"title": f"Decision number {i} with rationale", "rationale": "x" * 80}
                   for i in range(10)],
        blockers=[{"title": f"Blocker number {i}", "status": "open"} for i in range(10)],
        next_actions=[f"Next action number {i} with some detail" for i in range(10)],
    )
    session_id = store.create_session(project_id, payload, GitState(branch="main"))
    store.record_decisions(project_id, session_id, payload.decisions)
    store.record_blockers(project_id, session_id, payload.blockers)
    store.record_next_actions(project_id, session_id, payload.next_actions)
    return project_path


def test_bad_fts_query_is_structured_error(tmp_path):
    result = services.search_observations_safe(str(tmp_path / "d.db"), '"unbalanced')
    assert result["ok"] is False
    assert result["query"] == '"unbalanced'
    assert result["results"] == []
    assert "error" in result


def test_good_fts_query_reports_ok_with_results(tmp_path):
    db = str(tmp_path / "d.db")
    store = services.open_store(db)
    pid = store.upsert_project(project_id="p", name="p", path="/tmp/p", relative_path="p")
    store.record_observations(pid, None, "file", ["src/main.py"])

    result = services.search_observations_safe(db, "main")
    assert result["ok"] is True
    assert result["count"] == 1
    assert result["results"][0]["content"] == "src/main.py"


def test_negative_limit_is_clamped_to_zero(tmp_path):
    db = str(tmp_path / "d.db")
    store = services.open_store(db)
    pid = store.upsert_project(project_id="p", name="p", path="/tmp/p", relative_path="p")
    store.record_observations(pid, None, "file", ["a.py", "b.py"])

    result = services.search_observations_safe(db, "py", limit=-3)
    assert result["ok"] is True
    assert result["count"] == 0


def test_mcp_search_routes_through_safe_wrapper(monkeypatch):
    calls: dict[str, object] = {}

    def fake_safe(db_path, query, *, project_id=None, limit=20):
        calls.update(db_path=db_path, query=query, project_id=project_id, limit=limit)
        return {"ok": True, "query": query, "count": 0, "results": []}

    monkeypatch.setattr(services, "search_observations_safe", fake_safe)
    result = mcp_server.handle_search_observations("needle", db_path="x.db", limit=5)

    assert result["ok"] is True
    assert calls == {"db_path": "x.db", "query": "needle", "project_id": None, "limit": 5}


def test_handoff_unreadable_json_raises_value_error(tmp_path):
    args = Namespace(json=str(tmp_path / "nope.json"))
    try:
        build_handoff_payload(args)
    except ValueError as exc:
        assert "unreadable --json payload" in str(exc)
    else:
        raise AssertionError("expected ValueError for unreadable --json payload")


def test_handoff_invalid_json_raises_value_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")

    args = Namespace(json=str(bad))
    try:
        build_handoff_payload(args)
    except ValueError as exc:
        assert "unreadable --json payload" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid JSON payload")


def test_cli_handoff_bad_json_prints_clean_error_and_returns_two(
    tmp_path, capsys, monkeypatch
):
    from chrono_core.cli import main

    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")

    code = main(["handoff", "--summary", "s", "--json", str(bad)])
    captured = capsys.readouterr()

    assert code == 2
    assert "unreadable --json payload" in (captured.out + captured.err)


def test_markdown_escapes_structure_chars():
    assert _render_escape("# not a heading](link").startswith("\\#")
    assert _render_escape("back\\slash") == "back\\\\slash"
    assert _render_escape("[bracket]") == "\\[bracket\\]"
    assert _render_escape("plain text") == "plain text"


def test_markdown_export_escapes_user_text(tmp_path):
    from chrono_core.export.markdown import export_markdown

    db = str(tmp_path / "d.db")
    project_dir = tmp_path / "weird"
    project_dir.mkdir()
    store = services.open_store(db)
    pid = store.upsert_project(
        project_id="weird", name="# Weird [Name]", path=str(project_dir),
        relative_path="weird",
    )
    store.record_next_actions(pid, None, ["# Not a heading [link]"])

    result = export_markdown(store, tmp_path / "out")
    index = (tmp_path / "out" / "Projects.md").read_text(encoding="utf-8")
    page = Path(result["projects"][0]["path"]).read_text(encoding="utf-8")

    assert "# Weird [Name]" not in index.split("\n", 1)[1]
    assert "- \\[\\# Weird \\[Name\\]\\]" in index or "\\#" in index
    assert page.count("\\#") >= 2


def test_zero_max_tokens_is_honored(tmp_path):
    db_path = tmp_path / "chrono.db"
    project_path = _seed_busy_project(db_path, tmp_path / "workspace")

    result = mcp_server.handle_get_resume_context(
        str(project_path),
        workspace_root=str(tmp_path / "workspace"),
        db_path=str(db_path),
        max_tokens=0,
    )

    assert result["truncated"] is True
    assert result["recent_decisions"] == []
    assert result["next_actions"] == []


def test_git_subprocess_calls_carry_timeout(monkeypatch, tmp_path):
    captured: list[dict] = []

    class FakeCompleted:
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured.append(kwargs)
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    (tmp_path / ".git").mkdir()
    read_git_state(tmp_path)

    assert len(captured) == 3
    assert all(kwargs.get("timeout") == 10 for kwargs in captured)


def test_read_git_state_survives_timeout(monkeypatch, tmp_path):
    def hung_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", hung_run)
    (tmp_path / ".git").mkdir()

    state = read_git_state(tmp_path)
    assert state.branch is None and state.head is None and state.dirty is False
