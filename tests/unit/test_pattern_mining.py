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
    assert "Recurring pattern: circuit breaker" in titles
    old_single_token_titles = {"Recurring theme: circuit", "Recurring theme: breaker"}
    assert all(title not in old_single_token_titles for title in titles)
    assert result["skipped_existing"] == 0


def test_mining_respects_limit_and_skips_existing_titles(tmp_path: Path):
    store = seed_two_project_stores(tmp_path)
    first = mine_pattern_candidates(store, min_projects=2, limit=1)
    assert len(first["mined"]) == 1

    second = mine_pattern_candidates(store, min_projects=2)

    # Title-only dedup: the already-stored top-ranked phrase is skipped;
    # remaining qualifying phrases are still minted as new candidates.
    assert {p["title"] for p in second["mined"]} == {
        "Recurring pattern: circuit breaker",
        "Recurring pattern: circuit breaker saved",
    }
    assert second["skipped_existing"] == 1
    assert len(store.list_patterns()) == 3


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


def test_mining_ignores_operational_observation_kinds(tmp_path: Path):
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
        store.record_observations(
            pid,
            session,
            "workspace_intelligence_metadata",
            ["shared operational marker"],
        )
        store.record_observations(
            pid,
            session,
            "lesson",
            ["bounded retry budget"],
        )

    result = mine_pattern_candidates(store, min_projects=2)

    titles = {pattern["title"] for pattern in result["mined"]}
    assert "Recurring pattern: bounded retry budget" in titles
    assert all("operational" not in title and "marker" not in title for title in titles)


def test_mining_does_not_treat_decision_prose_as_pattern_evidence(tmp_path: Path):
    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    for name, decision in (
        ("alpha", "circuit breaker around remote calls"),
        ("beta", "circuit breaker around provider calls"),
    ):
        proj = tmp_path / name
        proj.mkdir()
        project = resolve_project(proj, workspace_root=tmp_path)
        pid = store.get_or_create_project(project)
        session = store.create_session(
            pid, HandoffPayload(summary="s"), GitState(branch="main")
        )
        store.record_decisions(pid, session, [{"title": decision}])

    result = mine_pattern_candidates(store, min_projects=2)

    assert result["mined"] == []
