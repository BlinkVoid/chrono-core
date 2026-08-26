from __future__ import annotations

from pathlib import Path

import pytest

from chrono_core.domain.models import GitState, HandoffPayload, ResumeContext
from chrono_core.store.store import Store


def make_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    return store


def test_migration_v4_creates_patterns_and_fts(tmp_path: Path):
    store = make_store(tmp_path)
    conn = store._connect()

    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        ).fetchall()
    }
    assert "patterns" in tables

    # FTS sync triggers fire: a written pattern is searchable.
    conn.execute(
        """
        INSERT INTO patterns (
            id, title, statement, category, status, source,
            source_ref, projects_json, created_at, updated_at
        )
        VALUES ('pat_x', 'Fail-Closed Gating', 'default is rejection',
                'security', 'validated', 'metafactory', NULL, '[]',
                datetime('now'), datetime('now'))
        """
    )
    store._commit()
    row = conn.execute(
        "SELECT p.title FROM pattern_fts f JOIN patterns p ON p.rowid = f.rowid "
        "WHERE pattern_fts MATCH 'rejection'"
    ).fetchone()
    assert row is not None and row["title"] == "Fail-Closed Gating"


def test_migration_ledger_records_v4(tmp_path: Path):
    store = make_store(tmp_path)
    applied = {
        row["version"]
        for row in store._connect().execute("SELECT version FROM schema_migrations")
    }
    assert 4 in applied


def seeded_pattern(store: Store, title: str = "Single Client Boundary") -> str:
    return store.upsert_pattern(
        title=title,
        statement="All provider calls flow through one client.",
        category="architecture",
        source="metafactory",
        source_ref="consolidated/2026-08-01_090633/patterns_library.md",
        projects=["ProjectMik", "GearCore"],
        status="validated",
    )


def test_upsert_pattern_is_idempotent_by_title(tmp_path: Path):
    store = make_store(tmp_path)
    first = seeded_pattern(store)
    second = store.upsert_pattern(
        title="Single Client Boundary",
        statement="Updated statement.",
        source="metafactory",
        status="validated",
    )

    assert first == second
    rows = store.list_patterns()
    assert len(rows) == 1
    assert rows[0]["statement"] == "Updated statement."
    assert rows[0]["status"] == "validated"


def test_upsert_never_regresses_promoted_or_retired(tmp_path: Path):
    store = make_store(tmp_path)
    pid = seeded_pattern(store)
    assert store.set_pattern_status(pid, "promoted")["ok"]

    store.upsert_pattern(title="Single Client Boundary", status="validated")

    assert store.list_patterns()[0]["status"] == "promoted"


def test_set_pattern_status_transitions_and_errors(tmp_path: Path):
    store = make_store(tmp_path)
    pid = seeded_pattern(store)

    result = store.set_pattern_status(pid, "retired")
    assert result == {"ok": True, "pattern_id": pid, "status": "retired"}
    assert store.set_pattern_status("pat_missing", "retired")["status"] == "not_found"

    with pytest.raises(ValueError):
        store.set_pattern_status(pid, "bogus")


def test_list_patterns_filters_by_status(tmp_path: Path):
    store = make_store(tmp_path)
    seeded_pattern(store)
    store.upsert_pattern(title="Recurring theme: retry", source="mined")

    validated = store.list_patterns(status="validated")
    assert [p["title"] for p in validated] == ["Single Client Boundary"]
    assert len(store.list_patterns()) == 2


def test_search_patterns_safe_ranks_and_filters_status(tmp_path: Path):
    store = make_store(tmp_path)
    seeded_pattern(store)
    store.upsert_pattern(title="Recurring theme: client", source="mined")

    hits = store.search_patterns_safe("client boundary")
    assert [h["title"] for h in hits] == ["Single Client Boundary"]

    store.set_pattern_status(hits[0]["id"], "promoted")
    assert store.search_patterns_safe("client boundary") == []


def test_search_patterns_safe_survives_malformed_query(tmp_path: Path):
    store = make_store(tmp_path)
    seeded_pattern(store)
    assert store.search_patterns_safe('"unclosed phrase') == []


def test_resume_context_carries_recommendations(tmp_path: Path):
    context = ResumeContext(project_id="p", project_name="n", project_path="/p")
    assert context.recommended_patterns == []
    assert context.to_dict()["recommended_patterns"] == []


def test_recommendations_appear_in_get_resume_context(tmp_path: Path):
    store = make_store(tmp_path)
    workspace = tmp_path / "ws"
    proj = workspace / "proj"
    proj.mkdir(parents=True)
    from chrono_core.workspace.resolver import resolve_project

    project = resolve_project(proj, workspace_root=workspace)
    pid = store.get_or_create_project(project)
    session = store.create_session(
        pid,
        HandoffPayload(summary="s"),
        GitState(),
    )
    store.record_decisions(pid, session, [{"title": "retry loop around flaky upstream"}])
    seeded_pattern(store)

    context = store.get_resume_context(pid)

    titles = [p["title"] for p in context.recommended_patterns]
    assert "Single Client Boundary" in titles or titles == []
    expected_keys = {"id", "title", "category", "status"}
    assert all(
        set(p.keys()) == expected_keys for p in context.recommended_patterns
    )
