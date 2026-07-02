from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from continuity_core.capture.handoff import build_handoff_payload, persist_handoff
from continuity_core.domain.models import GitState, HandoffPayload
from continuity_core.store.store import Store
from continuity_core.workspace.resolver import resolve_project


def test_build_handoff_payload_from_summary_only():
    args = Namespace(summary="Updated docs.")
    payload = build_handoff_payload(args)
    assert payload.summary == "Updated docs."


def test_build_handoff_payload_from_cli_args():
    args = Namespace(
        summary="Implemented CLI.",
        json=None,
        files_changed=["src/cli.py", "src/store.py"],
        tests=["pytest: passed"],
        decisions=['{"title": "Use SQLite", "rationale": "simple"}'],
        blockers=["Missing tests"],
        next_actions=["Add resume"],
        risks=["Schema churn"],
    )
    payload = build_handoff_payload(args)
    assert payload.summary == "Implemented CLI."
    assert payload.files_changed == ["src/cli.py", "src/store.py"]
    assert payload.decisions == [{"title": "Use SQLite", "rationale": "simple"}]
    assert payload.blockers == [{"title": "Missing tests"}]


def test_build_handoff_payload_from_json(tmp_path: Path):
    data = {
        "summary": "From JSON",
        "files_changed": ["a.py"],
        "decisions": [{"title": "D", "rationale": "R"}],
        "blockers": [{"title": "B", "status": "open"}],
        "next_actions": ["N"],
    }
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(data))

    args = Namespace(json=str(path))
    payload = build_handoff_payload(args)
    assert payload.summary == "From JSON"
    assert payload.next_actions == ["N"]


def test_persist_handoff_creates_records(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    project = resolve_project(tmp_path / "workspace" / "example", workspace_root=tmp_path / "workspace")
    payload = HandoffPayload(
        summary="Test handoff.",
        files_changed=["src/x.py"],
        blockers=[{"title": "Block", "status": "open"}],
    )
    result = persist_handoff(store, project, payload, GitState(branch="main"))

    assert result["ok"] is True
    assert result["project_id"] == project.project_id
    assert "session_id" in result
    assert "Block" in result["resume_hint"]
