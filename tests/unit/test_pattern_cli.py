from __future__ import annotations

import json
from pathlib import Path

from chrono_core.cli import main

SNAPSHOT = """## Pattern: Fail-Closed Gating

**Category**: security
**Projects**: alpha, beta

**Pattern Statement**:
Default is rejection at trust boundaries.
"""


def seed_snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / "consolidated" / "2026-08-01_090633"
    snap.mkdir(parents=True)
    path = snap / "patterns_library.md"
    path.write_text(SNAPSHOT, encoding="utf-8")
    return path


def test_ingest_patterns_cli_happy_path(tmp_path: Path, capsys):
    db = tmp_path / "chrono.db"
    seed_snapshot(tmp_path / "mf")

    rc = main([
        "ingest-patterns",
        "--metafactory-root", str(tmp_path / "mf"),
        "--db-path", str(db),
    ])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["ingested"] == 1


def test_ingest_patterns_cli_missing_snapshot_fails(tmp_path: Path, capsys):
    rc = main([
        "ingest-patterns",
        "--metafactory-root", str(tmp_path / "empty"),
        "--db-path", str(tmp_path / "chrono.db"),
    ])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""


def test_mine_patterns_cli(tmp_path: Path, capsys):
    db = tmp_path / "chrono.db"
    from chrono_core.domain.models import GitState, HandoffPayload
    from chrono_core.store.store import Store
    from chrono_core.workspace.resolver import resolve_project

    store = Store(db)
    store.init_schema()
    for name in ("alpha", "beta"):
        proj = tmp_path / name
        proj.mkdir()
        project = resolve_project(proj, workspace_root=tmp_path)
        pid = store.get_or_create_project(project)
        session = store.create_session(
            pid, HandoffPayload(summary="s"), GitState(branch="main")
        )
        store.record_decisions(pid, session, [{"title": f"idempotency key reuse in {name}"}])

    rc = main([
        "mine-patterns",
        "--db-path", str(db),
    ])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert any(p["title"].startswith("Recurring theme:") for p in out["mined"])


def test_patterns_list_and_set_status_cli(tmp_path: Path, capsys):
    db = tmp_path / "chrono.db"
    seed_snapshot(tmp_path / "mf")
    main([
        "ingest-patterns",
        "--metafactory-root", str(tmp_path / "mf"),
        "--db-path", str(db),
    ])
    capsys.readouterr()

    rc = main(["patterns", "list", "--db-path", str(db)])
    listed = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert listed["ok"] is True
    assert listed["patterns"][0]["title"] == "Fail-Closed Gating"
    pattern_id = listed["patterns"][0]["id"]

    filtered = main(["patterns", "list", "--status", "promoted", "--db-path", str(db)])
    out_filtered = json.loads(capsys.readouterr().out)
    assert filtered == 0 and out_filtered["patterns"] == []

    rc = main(["patterns", "set-status", pattern_id, "promoted", "--db-path", str(db)])
    set_out = json.loads(capsys.readouterr().out)
    assert rc == 0 and set_out["ok"] is True and set_out["status"] == "promoted"

    rc_bad = main([
        "patterns", "set-status", pattern_id, "bogus", "--db-path", str(db),
    ])
    assert rc_bad == 2
    assert capsys.readouterr().out == ""


def test_resume_output_includes_recommended_patterns(tmp_path: Path, capsys):
    db = tmp_path / "chrono.db"
    seed_snapshot(tmp_path / "mf")
    main(["ingest-patterns", "--metafactory-root", str(tmp_path / "mf"), "--db-path", str(db)])
    capsys.readouterr()

    from chrono_core.domain.models import GitState, HandoffPayload
    from chrono_core.store.store import Store
    from chrono_core.workspace.resolver import resolve_project

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".git").mkdir()
    store = Store(db)
    project = resolve_project(proj, workspace_root=tmp_path)
    pid = store.get_or_create_project(project)
    session = store.create_session(
        pid, HandoffPayload(summary="s"), GitState(branch="main")
    )
    store.record_decisions(pid, session, [{"title": "fail closed gating at boundaries"}])
    store.close()

    class Args:
        cwd = str(proj)
        workspace_root = str(tmp_path)
        db_path = str(db)
        json = True
        all = False
        branch = None
        limit = 20

    from chrono_core.resume import resume_command

    assert resume_command(Args()) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["recommended_patterns"][0]["title"] == "Fail-Closed Gating"
