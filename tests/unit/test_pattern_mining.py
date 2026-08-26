from __future__ import annotations

from pathlib import Path

from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.management.patterns import mine_pattern_candidates
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


def seed_two_project_stores(tmp_path: Path) -> Store:
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    for name in ("alpha", "beta"):
        proj = tmp_path / name
        proj.mkdir()
        project = resolve_project(proj, workspace_root=tmp_path)
        pid = store.get_or_create_project(project)
        session = store.create_session(
            pid, HandoffPayload(summary="s"), GitState(branch="main")
        )
        store.record_decisions(pid, session, [{"title": f"circuit breaker in {name}"}])
        store.record_observations(pid, session, "lesson", [f"circuit breaker saved {name}"])
    return store


def test_mining_requires_min_distinct_projects(tmp_path: Path):
    store = seed_two_project_stores(tmp_path)

    result = mine_pattern_candidates(store, min_projects=2)

    titles = [p["title"] for p in result["mined"]]
    assert "Recurring theme: circuit" in titles
    assert "Recurring theme: breaker" in titles
    assert result["skipped_existing"] == 0


def test_mining_respects_limit_and_skips_existing_titles(tmp_path: Path):
    store = seed_two_project_stores(tmp_path)
    first = mine_pattern_candidates(store, min_projects=2, limit=1)
    assert len(first["mined"]) == 1

    second = mine_pattern_candidates(store, min_projects=2)

    assert second["mined"] == []
    assert second["skipped_existing"] == 2
    assert len(store.list_patterns(status="candidate")) == 1


def test_single_project_terms_are_not_mined(tmp_path: Path):
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    proj = tmp_path / "solo"
    proj.mkdir()
    project = resolve_project(proj, workspace_root=tmp_path)
    pid = store.get_or_create_project(project)
    session = store.create_session(
        pid, HandoffPayload(summary="s"), GitState(branch="main")
    )
    store.record_decisions(pid, session, [{"title": "esoteric widget only here"}])

    result = mine_pattern_candidates(store, min_projects=2)

    assert result["mined"] == []
