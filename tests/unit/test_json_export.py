from __future__ import annotations

import json
from pathlib import Path

import pytest

from chrono_core.cli import main
from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.export.json import export_records_json
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project

T1 = "2026-08-25T10:00:00+00:00"
T2 = "2026-08-26T09:00:00+00:00"
T3 = "2026-08-27T09:00:00+00:00"


def make_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    return store


def seed_project(store: Store, tmp_path: Path) -> str:
    project = resolve_project(tmp_path / "proj", workspace_root=tmp_path)
    return store.upsert_project(
        project_id=project.project_id,
        name="example",
        path=str(tmp_path / "proj"),
        relative_path="proj",
    )


def seed_records(store: Store, project_id: str) -> dict[str, list[str]]:
    session = store.create_session(project_id, HandoffPayload(summary="s"), GitState())
    decisions = [
        {"title": "Use SQLite", "rationale": "local-first"},
        {"title": "Use FTS", "rationale": "search"},
    ]
    blockers = [{"title": "Flaky test", "status": "open"}]
    actions = ["Ship export", "Write docs"]
    store.record_decisions(project_id, session, decisions)
    store.record_blockers(project_id, session, blockers)
    store.record_next_actions(project_id, session, actions)

    decision_ids = [
        row["id"]
        for row in store._connect().execute(
            "SELECT id FROM decisions WHERE project_id = ? ORDER BY title", (project_id,)
        ).fetchall()
    ]
    blocker_ids = [
        row["id"]
        for row in store._connect().execute(
            "SELECT id FROM blockers WHERE project_id = ? ORDER BY title", (project_id,)
        ).fetchall()
    ]
    action_ids = [
        row["id"]
        for row in store._connect().execute(
            "SELECT id FROM next_actions WHERE project_id = ? ORDER BY text", (project_id,)
        ).fetchall()
    ]
    return {"decisions": decision_ids, "blockers": blocker_ids,
            "next_actions": action_ids}


def set_created_at(store: Store, table: str, entity_id: str, created_at: str) -> None:
    conn = store._connect()
    conn.execute(
        f"UPDATE {table} SET created_at = ? WHERE id = ?", (created_at, entity_id)
    )
    store._commit()


# 1. Full export returns all record types; closed items excluded by default.
def test_full_export_returns_all_records_and_excludes_closed_by_default(tmp_path: Path):
    store = make_store(tmp_path)
    pid = seed_project(store, tmp_path)
    ids = seed_records(store, pid)
    store.resolve_blocker(ids["blockers"][0])
    store.complete_next_action(ids["next_actions"][1])

    payload = export_records_json(store, pid)

    assert payload["project_id"] == pid
    assert payload["project_name"] == "example"
    assert payload["filters"] == {"since": None, "include_closed": False}
    decision = payload["decisions"][0]
    assert set(decision.keys()) == {
        "id", "title", "rationale", "status", "created_at", "session_id"
    }
    assert decision["session_id"] is not None
    assert len(payload["decisions"]) == 2
    assert payload["blockers"] == []
    assert len(payload["next_actions"]) == 1
    assert {a["text"] for a in payload["next_actions"]} == {"Ship export"}
    action = payload["next_actions"][0]
    assert set(action.keys()) == {"id", "text", "status", "priority", "created_at"}


# 2. --since boundary: records exactly at the watermark are included.
def test_since_boundary_is_inclusive(tmp_path: Path):
    store = make_store(tmp_path)
    pid = seed_project(store, tmp_path)
    ids = seed_records(store, pid)
    set_created_at(store, "next_actions", ids["next_actions"][0], T1)
    set_created_at(store, "next_actions", ids["next_actions"][1], T2)

    payload = export_records_json(store, pid, since=T2)

    assert {a["text"] for a in payload["next_actions"]} == {"Write docs"}
    assert payload["filters"]["since"] == T2


# 3. --include-closed surfaces terminal statuses.
def test_include_closed_surfaces_terminal_statuses(tmp_path: Path):
    store = make_store(tmp_path)
    pid = seed_project(store, tmp_path)
    ids = seed_records(store, pid)
    store.cancel_blocker(ids["blockers"][0], reason="obsolete")
    store.complete_next_action(ids["next_actions"][1])

    payload = export_records_json(store, pid, include_closed=True)

    blocker = payload["blockers"][0]
    assert set(blocker.keys()) == {"id", "title", "status", "detail", "created_at"}
    assert blocker["status"] == "cancelled"
    statuses = {a["text"]: a["status"] for a in payload["next_actions"]}
    assert statuses == {"Ship export": "open", "Write docs": "done"}


# 4. --type filtering drops other arrays from the payload entirely.
def test_type_filter_drops_other_arrays_from_payload(tmp_path: Path):
    store = make_store(tmp_path)
    pid = seed_project(store, tmp_path)
    seed_records(store, pid)

    payload = export_records_json(store, pid, record_types=["blockers"])

    assert set(payload.keys()) == {
        "project_id",
        "project_name",
        "project_path",
        "exported_at",
        "filters",
        "blockers",
    }


# 5. Deterministic ordering across two consecutive exports.
def test_export_ordering_is_deterministic_by_created_at_then_id(tmp_path: Path):
    store = make_store(tmp_path)
    pid = seed_project(store, tmp_path)
    ids = seed_records(store, pid)
    set_created_at(store, "decisions", ids["decisions"][0], T3)
    set_created_at(store, "decisions", ids["decisions"][1], T3)

    first = export_records_json(store, pid)
    second = export_records_json(store, pid)

    # exported_at is the per-call timestamp; arrays must diff cleanly.
    first.pop("exported_at")
    second.pop("exported_at")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    ordered = [d["id"] for d in first["decisions"]]
    assert ordered == sorted(ordered)


# 6. Project resolution via --cwd matches resume's resolution.
def test_cli_cwd_resolution_matches_resume_resolution(tmp_path: Path, capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".git").mkdir()
    db = tmp_path / "chrono.db"
    store = Store(db)
    store.init_schema()
    project = resolve_project(proj, workspace_root=tmp_path)
    pid = store.upsert_project(
        project_id=project.project_id,
        name="proj",
        path=str(proj),
        relative_path="proj",
    )
    store.record_next_actions(pid, None, ["an action"])

    rc = main([
        "export", "json",
        "--cwd", str(proj),
        "--workspace-root", str(tmp_path),
        "--db-path", str(db),
    ])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["project_id"] == pid
    assert out["project_name"] == "proj"
    assert len(out["next_actions"]) == 1


# 7a. Bad inputs exit non-zero: malformed --since.
def test_cli_rejects_malformed_since(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    db = tmp_path / "chrono.db"
    rc = main([
        "export", "json",
        "--cwd", str(proj),
        "--workspace-root", str(tmp_path),
        "--db-path", str(db),
        "--since", "not-a-date",
    ])
    assert rc != 0


# 7b/c. Exactly one of --project-id / --cwd is required.
def test_cli_requires_exactly_one_project_selector():
    with pytest.raises(SystemExit) as neither:
        main(["export", "json"])
    assert neither.value.code != 0

    with pytest.raises(SystemExit) as both:
        main(["export", "json", "--project-id", "p_x", "--cwd", "."])
    assert both.value.code != 0


# 7d. Unknown --project-id exits non-zero without partial output.
def test_cli_unknown_project_id_fails_cleanly(capsys):
    rc = main([
        "export", "json",
        "--project-id", "nope-0000000000",
        "--db-path", "/tmp/opencode/export-json-unknown-project.db",
    ])
    captured = capsys.readouterr()
    assert rc != 0
    assert json.loads(captured.out) == {} if False else captured.out == ""


def test_cli_unregistered_cwd_project_exports_empty_payload(tmp_path: Path, capsys):
    proj = tmp_path / "fresh"
    proj.mkdir()
    (proj / ".git").mkdir()
    db = tmp_path / "chrono.db"

    rc = main([
        "export", "json",
        "--cwd", str(proj),
        "--workspace-root", str(tmp_path),
        "--db-path", str(db),
    ])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decisions"] == []
    assert out["blockers"] == []
    assert out["next_actions"] == []
    assert out["project_name"] == "fresh"
