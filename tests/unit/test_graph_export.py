from __future__ import annotations

import json
from pathlib import Path

import pytest

from chrono_core.cli import main
from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.export.graph import build_record_graph
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


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


def seed_session_records(store: Store, project_id: str) -> str:
    """Create one session with a decision, blocker, and two actions."""
    session = store.create_session(
        project_id,
        HandoffPayload(summary="Design export", next_actions=["Ship graph", "Write docs"]),
        GitState(branch="main"),
    )
    store.record_decisions(project_id, session, [{"title": "Use SQLite"}])
    store.record_blockers(project_id, session, [{"title": "Flaky test"}])
    store.record_next_actions(project_id, session, ["Ship graph", "Write docs"])
    return session


# Nodes cover all three record types plus their session hub, with stable shape.
def test_nodes_include_records_and_session_hubs(tmp_path: Path):
    store = make_store(tmp_path)
    pid = seed_project(store, tmp_path)
    session = seed_session_records(store, pid)

    graph = build_record_graph(store, pid)

    by_type: dict[str, list[dict]] = {}
    for node in graph["nodes"]:
        assert set(node.keys()) == {"id", "type", "label", "status", "created_at"}
        by_type.setdefault(node["type"], []).append(node)

    assert len(by_type["decision"]) == 1
    assert by_type["decision"][0]["label"] == "Use SQLite"
    assert len(by_type["blocker"]) == 1
    assert by_type["blocker"][0]["label"] == "Flaky test"
    assert {n["label"] for n in by_type["next_action"]} == {"Ship graph", "Write docs"}

    session_nodes = by_type["session"]
    assert [n["id"] for n in session_nodes] == [session]
    assert session_nodes[0]["label"] == "Design export"


# Session co-occurrence is represented only through the session hub node.
def test_edges_link_records_to_session_hub_only(tmp_path: Path):
    store = make_store(tmp_path)
    pid = seed_project(store, tmp_path)
    session = seed_session_records(store, pid)

    graph = build_record_graph(store, pid)
    edges = graph["edges"]

    hub_edges = [e for e in edges if e["relation"] == "captured_in"]
    assert len(hub_edges) == 4
    assert all(e["target"] == session for e in hub_edges)

    # No direct problem->solution edges: everything routes via the hub.
    direct = [
        e
        for e in edges
        if e["relation"] != "captured_in"
        and e["source"].startswith(("blk_", "dec_"))
        and e["target"].startswith(("blk_", "dec_", "act_"))
    ]
    assert direct == []
    for edge in edges:
        assert set(edge.keys()) == {"source", "target", "relation"}


# Supersession produces an explicit old->new edge between action nodes.
def test_superseded_actions_produce_superseded_by_edge(tmp_path: Path):
    store = make_store(tmp_path)
    pid = seed_project(store, tmp_path)
    seed_session_records(store, pid)
    old_id = store._connect().execute(
        "SELECT id FROM next_actions WHERE text = 'Ship graph'"
    ).fetchone()["id"]

    result = store.supersede_next_action(old_id, "Ship graph v2")
    assert result["ok"]

    graph = build_record_graph(store, pid)

    supersede_edges = [e for e in graph["edges"] if e["relation"] == "superseded_by"]
    assert supersede_edges == [
        {"source": old_id, "target": result["new_action_id"], "relation": "superseded_by"}
    ]
    labels = {n["label"] for n in graph["nodes"] if n["type"] == "next_action"}
    assert "Ship graph v2" in labels


# Records captured outside any session still appear, without hub edges.
def test_orphan_records_have_no_hub_edges(tmp_path: Path):
    store = make_store(tmp_path)
    pid = seed_project(store, tmp_path)
    store.record_decisions(pid, None, [{"title": "Pre-history decision"}])

    graph = build_record_graph(store, pid)

    orphan = [n for n in graph["nodes"] if n["label"] == "Pre-history decision"]
    assert len(orphan) == 1
    assert all(e["source"] != orphan[0]["id"] for e in graph["edges"])


def test_graph_output_is_deterministic(tmp_path: Path):
    store = make_store(tmp_path)
    pid = seed_project(store, tmp_path)
    seed_session_records(store, pid)

    first = json.dumps(build_record_graph(store, pid), sort_keys=True)
    second = json.dumps(build_record_graph(store, pid), sort_keys=True)

    assert first == second
    parsed = json.loads(first)
    node_keys = [(n["type"], n["created_at"], n["id"]) for n in parsed["nodes"]]
    assert node_keys == sorted(node_keys)
    edge_keys = [(e["source"], e["relation"], e["target"]) for e in parsed["edges"]]
    assert edge_keys == sorted(edge_keys)


def test_unknown_project_id_raises(tmp_path: Path):
    store = Store(tmp_path / "graph-export-unknown.db")
    store.init_schema()
    with pytest.raises(ValueError):
        build_record_graph(store, "nope-0000000000")


def test_cli_export_graph_via_cwd(tmp_path: Path, capsys):
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
    seed_session_records(store, pid)

    rc = main([
        "export", "graph",
        "--cwd", str(proj),
        "--workspace-root", str(tmp_path),
        "--db-path", str(db),
    ])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["project_id"] == pid
    assert out["project_name"] == "proj"
    assert out["filters"] == {}
    assert len(out["nodes"]) == 5
    assert len(out["edges"]) == 4


def test_cli_unregistered_cwd_project_exports_empty_graph(tmp_path: Path, capsys):
    proj = tmp_path / "fresh"
    proj.mkdir()
    (proj / ".git").mkdir()

    rc = main([
        "export", "graph",
        "--cwd", str(proj),
        "--workspace-root", str(tmp_path),
        "--db-path", str(tmp_path / "chrono.db"),
    ])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["nodes"] == []
    assert out["edges"] == []


def test_cli_unknown_project_id_fails_cleanly(tmp_path: Path, capsys):
    rc = main([
        "export", "graph",
        "--project-id", "nope-0000000000",
        "--db-path", str(tmp_path / "graph-export-unknown-cli.db"),
    ])
    captured = capsys.readouterr()
    assert rc != 0
    assert captured.out == ""


def test_cli_requires_exactly_one_project_selector():
    with pytest.raises(SystemExit) as neither:
        main(["export", "graph"])
    assert neither.value.code != 0

    with pytest.raises(SystemExit) as both:
        main(["export", "graph", "--project-id", "p_x", "--cwd", "."])
    assert both.value.code != 0
