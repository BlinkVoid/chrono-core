"""Live project inventory: store contracts, discovery refresh, and services."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from chrono_core import services
from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.store.store import Store
from chrono_core.workspace.discovery import DiscoveryOptions, discover_workspace
from chrono_core.workspace.inventory import GitCommandResult

# --- helpers -----------------------------------------------------------------


class FakeGitRunner:
    """Injectable runner returning scripted git results per repository path."""

    def __init__(self) -> None:
        self.states: dict[str, dict] = {}
        self.calls: list[list[str]] = []

    def set(
        self,
        path: str | Path,
        *,
        branch: str = "main",
        changed: tuple[str, ...] = (),
        untracked: tuple[str, ...] = (),
        head: tuple[str, str] = ("ac6368f", "seed commit"),
        remote: tuple[str, str] | None = None,
        default_branch: str | None = "main",
        fail_status: bool = False,
    ) -> None:
        self.states[str(path)] = {
            "branch": branch,
            "changed": changed,
            "untracked": untracked,
            "head": head,
            "remote": remote,
            "default_branch": default_branch,
            "fail_status": fail_status,
        }

    def __call__(self, argv: list[str], *, timeout: float = 10.0) -> GitCommandResult:
        self.calls.append(list(argv))
        state = self.states.get(argv[2])
        if state is None:
            return GitCommandResult(returncode=128)
        tail = tuple(argv[3:])
        if tail == ("status", "--porcelain=v1", "-b"):
            if state["fail_status"]:
                return GitCommandResult(returncode=128)
            lines = [f"## {state['branch']}"]
            lines.extend(f" M {name}" for name in state["changed"])
            lines.extend(f"?? {name}" for name in state["untracked"])
            return GitCommandResult(stdout="\n".join(lines) + "\n")
        if tail == ("log", "-1", "--pretty=%h%x1f%s"):
            sha, subject = state["head"]
            return GitCommandResult(stdout=f"{sha}\x1f{subject}\n")
        if tail == ("remote",):
            return GitCommandResult(
                stdout="origin\n" if state["remote"] else ""
            )
        if tail == ("remote", "get-url", "origin"):
            return GitCommandResult(
                stdout=f"{state['remote'][1]}\n" if state["remote"] else "",
                returncode=0 if state["remote"] else 128,
            )
        if tail == ("symbolic-ref", "--short", "refs/remotes/origin/HEAD"):
            if state["remote"] and state["default_branch"]:
                return GitCommandResult(stdout=f"origin/{state['default_branch']}\n")
            return GitCommandResult(returncode=128)
        if tail == ("rev-parse", "--verify", "refs/heads/main"):
            return GitCommandResult(returncode=0 if state["default_branch"] == "main" else 128)
        if tail == ("rev-parse", "--verify", "refs/heads/master"):
            return GitCommandResult(returncode=0 if state["default_branch"] == "master" else 128)
        return GitCommandResult(returncode=128)


def _marker_project(root: Path, name: str, *, git: bool = True) -> Path:
    path = root / name
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    if git:
        (path / ".git").mkdir()
    return path


def _collected(
    *,
    branch: str = "main",
    changed: int = 0,
    untracked: int = 0,
    error: dict | None = None,
) -> dict:
    return {
        "is_git": True,
        "branch": branch,
        "detached": False,
        "head_sha": "ac6368f",
        "head_subject": "seed commit",
        "remote_name": None,
        "remote_url": None,
        "default_branch": "main",
        "dirty": bool(changed or untracked),
        "changed_count": changed,
        "untracked_count": untracked,
        "error": error,
    }


def _seed_catalog(store: Store, path: str, relative: str) -> str:
    return store.upsert_project(
        project_id=relative.replace("/", "-") + "-0001",
        name=relative.split("/")[-1],
        path=path,
        relative_path=relative,
    )


# --- store: nested reads ------------------------------------------------------


def test_get_project_embeds_inventory_and_catalog_only_rows_read_null(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    alpha = _seed_catalog(store, "/ws/alpha", "alpha")
    beta = _seed_catalog(store, "/ws/beta", "beta")
    store.upsert_project_inventory(
        project_id=alpha,
        workspace_root="/ws",
        marker="pyproject.toml",
        depth=1,
        collected=_collected(changed=2, untracked=1),
    )

    shown = store.get_project(alpha)
    inventory = shown["inventory"]
    assert inventory["workspace_root"] == "/ws"
    assert inventory["marker"] == "pyproject.toml"
    assert inventory["depth"] == 1
    assert inventory["is_git"] is True
    assert inventory["branch"] == "main"
    assert inventory["detached"] is False
    assert inventory["head_sha"] == "ac6368f"
    assert inventory["head_subject"] == "seed commit"
    assert inventory["dirty"] is True
    assert inventory["changed_count"] == 2
    assert inventory["untracked_count"] == 1
    assert inventory["last_seen_at"]
    assert inventory["missing_since"] is None
    assert inventory["last_error"] is None

    assert store.get_project(beta)["inventory"] is None


def test_list_projects_embeds_inventory(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    alpha = _seed_catalog(store, "/ws/alpha", "alpha")
    _seed_catalog(store, "/ws/beta", "beta")
    store.upsert_project_inventory(
        project_id=alpha,
        workspace_root="/ws",
        marker="pyproject.toml",
        depth=1,
        collected=_collected(),
    )

    records = {record["id"]: record for record in store.list_projects()}
    assert records[alpha]["inventory"]["branch"] == "main"
    assert records[[r["id"] for r in store.list_projects() if r["id"] != alpha][0]][
        "inventory"
    ] is None


# --- store: dirty filter is inventory-scoped ----------------------------------


def test_dirty_filters_use_inventory_not_session_snapshots(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    dirty_project = _seed_catalog(store, "/ws/dirty", "dirty")
    clean_project = _seed_catalog(store, "/ws/clean", "clean")
    plain_project = _seed_catalog(store, "/ws/plain", "plain")
    ghost_project = _seed_catalog(store, "/ws/ghost", "ghost")

    store.upsert_project_inventory(
        project_id=dirty_project,
        workspace_root="/ws",
        marker="pyproject.toml",
        depth=1,
        collected=_collected(changed=1),
    )
    store.upsert_project_inventory(
        project_id=clean_project,
        workspace_root="/ws",
        marker="pyproject.toml",
        depth=1,
        collected=_collected(),
    )
    store.upsert_project_inventory(
        project_id=plain_project,
        workspace_root="/ws",
        marker="pyproject.toml",
        depth=1,
        collected={
            "is_git": False,
            "branch": None,
            "detached": False,
            "head_sha": None,
            "head_subject": None,
            "remote_name": None,
            "remote_url": None,
            "default_branch": None,
            "dirty": False,
            "changed_count": 0,
            "untracked_count": 0,
            "error": None,
        },
    )
    # A historical session snapshot claims dirty; current inventory is clean.
    store.create_session(
        clean_project,
        HandoffPayload(summary="old handoff"),
        GitState(branch="old-branch", head="old-head", dirty=True),
    )

    dirty_ids = [record["id"] for record in store.list_projects(dirty=True)]
    assert dirty_ids == [dirty_project]

    clean_ids = set(
        record["id"] for record in store.list_projects(dirty=False)
    )
    assert clean_ids == {clean_project, plain_project}

    unfiltered = store.list_projects()
    assert (
        next(record for record in unfiltered if record["id"] == ghost_project)["inventory"]
        is None
    )

    # The clean project's session snapshot stays untouched by inventory reads.
    assert store.list_projects(dirty=True) != store.list_projects()
    session_row = store._connect().execute(
        "SELECT git_dirty FROM sessions WHERE project_id = ?", (clean_project,)
    ).fetchone()
    assert session_row["git_dirty"] == 1


# --- store: upsert semantics --------------------------------------------------


def test_upsert_keeps_last_successful_git_fields_and_records_bounded_error(
    tmp_path: Path,
):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    pid = _seed_catalog(store, "/ws/alpha", "alpha")
    store.upsert_project_inventory(
        project_id=pid,
        workspace_root="/ws",
        marker="pyproject.toml",
        depth=1,
        collected=_collected(changed=3),
    )
    first = store.get_project_inventory(pid)

    store.upsert_project_inventory(
        project_id=pid,
        workspace_root="/ws",
        marker="pyproject.toml",
        depth=1,
        collected=_collected(error={"code": "timeout", "op": "status"}),
    )
    second = store.get_project_inventory(pid)

    # Provenance refreshes, Git fields stay at the last successful values.
    assert second["last_error"] == {"code": "timeout", "op": "status"}
    assert second["branch"] == "main"
    assert second["head_sha"] == "ac6368f"
    assert second["dirty"] is True
    assert second["changed_count"] == 3
    assert second["collected_at"] == first["collected_at"]
    assert second["last_seen_at"] >= first["last_seen_at"]
    assert set(second["last_error"]) == {"code", "op"}

    store.upsert_project_inventory(
        project_id=pid,
        workspace_root="/ws",
        marker="pyproject.toml",
        depth=1,
        collected=_collected(branch="feature"),
    )
    third = store.get_project_inventory(pid)
    assert third["last_error"] is None
    assert third["branch"] == "feature"


def test_non_git_marker_project_is_a_clean_inventory_entry(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    pid = _seed_catalog(store, "/ws/plain", "plain")
    store.upsert_project_inventory(
        project_id=pid,
        workspace_root="/ws",
        marker="pyproject.toml",
        depth=1,
        collected={
            "is_git": False,
            "branch": None,
            "detached": False,
            "head_sha": None,
            "head_subject": None,
            "remote_name": None,
            "remote_url": None,
            "default_branch": None,
            "dirty": False,
            "changed_count": 0,
            "untracked_count": 0,
            "error": None,
        },
    )
    inventory = store.get_project_inventory(pid)
    assert inventory["is_git"] is False
    assert inventory["branch"] is None
    assert inventory["head_sha"] is None
    assert inventory["dirty"] is False


# --- store: missing reconciliation --------------------------------------------


def test_reconcile_is_exact_root_and_depth_scoped(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    alpha = _seed_catalog(store, "/ws/alpha", "alpha")
    beta = _seed_catalog(store, "/other/beta", "beta")
    deep = _seed_catalog(store, "/ws/a/b/deep", "a/b/deep")
    for pid, root, depth in ((alpha, "/ws", 1), (beta, "/other", 1), (deep, "/ws", 3)):
        store.upsert_project_inventory(
            project_id=pid,
            workspace_root=root,
            marker="pyproject.toml",
            depth=depth,
            collected=_collected(),
        )

    marked = store.reconcile_missing_inventory(
        workspace_root="/ws",
        max_depth=1,
        include_provisional=False,
        seen_project_ids=set(),
        now="2026-09-01T00:00:00+00:00",
    )

    assert marked == [alpha]
    assert store.get_project(alpha)["status"] == "missing"
    inventory = store.get_project_inventory(alpha)
    assert inventory["missing_since"] == "2026-09-01T00:00:00+00:00"
    assert inventory["status_before_missing"] == "active"
    assert store.get_project(beta)["status"] == "active"
    assert store.get_project(deep)["status"] == "active"
    assert store.get_project_inventory(deep)["missing_since"] is None


def test_reconcile_provisional_rows_require_provisional_scans(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    provisional = _seed_catalog(store, "/ws/generated", "generated")
    store.upsert_project_inventory(
        project_id=provisional,
        workspace_root="/ws",
        marker="provisional",
        depth=1,
        collected=_collected(),
    )

    marked = store.reconcile_missing_inventory(
        workspace_root="/ws",
        max_depth=3,
        include_provisional=False,
        seen_project_ids=set(),
        now="2026-09-01T00:00:00+00:00",
    )
    assert marked == []
    assert store.get_project(provisional)["status"] == "active"

    marked = store.reconcile_missing_inventory(
        workspace_root="/ws",
        max_depth=3,
        include_provisional=True,
        seen_project_ids=set(),
        now="2026-09-01T00:00:01+00:00",
    )
    assert marked == [provisional]
    assert store.get_project(provisional)["status"] == "missing"


@pytest.mark.parametrize("prior_status", ("paused", "archived"))
def test_reconcile_preserves_prior_status_and_restores_it_on_return(
    tmp_path: Path, prior_status: str
):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    paused = _seed_catalog(store, "/ws/paused", "paused")
    store.update_project_metadata(paused, {"status": prior_status})
    store.upsert_project_inventory(
        project_id=paused,
        workspace_root="/ws",
        marker="pyproject.toml",
        depth=1,
        collected=_collected(),
    )

    store.reconcile_missing_inventory(
        workspace_root="/ws",
        max_depth=1,
        include_provisional=False,
        seen_project_ids=set(),
        now="2026-09-01T00:00:00+00:00",
    )
    assert store.get_project(paused)["status"] == "missing"
    assert store.get_project_inventory(paused)["status_before_missing"] == prior_status

    # A second sweep must not double-mark or clobber the saved status.
    store.reconcile_missing_inventory(
        workspace_root="/ws",
        max_depth=1,
        include_provisional=False,
        seen_project_ids=set(),
        now="2026-09-01T00:01:00+00:00",
    )
    assert store.get_project_inventory(paused)["missing_since"] == (
        "2026-09-01T00:00:00+00:00"
    )

    store.upsert_project_inventory(
        project_id=paused,
        workspace_root="/ws",
        marker="pyproject.toml",
        depth=1,
        collected=_collected(),
    )
    restored = store.get_project(paused)
    assert restored["status"] == prior_status
    inventory = store.get_project_inventory(paused)
    assert inventory["missing_since"] is None
    assert inventory["status_before_missing"] is None


def test_return_without_saved_status_restores_active(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    pid = _seed_catalog(store, "/ws/alpha", "alpha")
    store.upsert_project_inventory(
        project_id=pid,
        workspace_root="/ws",
        marker="pyproject.toml",
        depth=1,
        collected=_collected(),
    )
    store.reconcile_missing_inventory(
        workspace_root="/ws",
        max_depth=1,
        include_provisional=False,
        seen_project_ids=set(),
        now="2026-09-01T00:00:00+00:00",
    )
    # An operator already marked it missing manually: no saved status exists.
    store._connect().execute(
        "UPDATE project_inventory SET status_before_missing = NULL WHERE project_id = ?",
        (pid,),
    )
    store._commit()

    store.upsert_project_inventory(
        project_id=pid,
        workspace_root="/ws",
        marker="pyproject.toml",
        depth=1,
        collected=_collected(),
    )
    assert store.get_project(pid)["status"] == "active"


# --- persisted discovery workflow ----------------------------------------------


def test_persisted_discover_refreshes_inventory_and_reconciles_missing(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    alpha = _marker_project(workspace, "alpha")
    beta = _marker_project(workspace, "beta")
    runner = FakeGitRunner()
    runner.set(alpha, branch="main")
    runner.set(beta, branch="feature", changed=("a.py",), untracked=("b.txt",))
    db = tmp_path / "chrono.db"

    result = discover_workspace(
        workspace_root=workspace,
        store=Store(db),
        git_runner=runner,
    )

    assert result.ok is True
    assert result.persisted_count == 2
    assert result.refreshed_count == 2
    assert result.failed_count == 0
    assert result.missing_count == 0
    assert result.failures == []

    store = Store(db)
    store.init_schema()
    alpha_id = store.find_project_id_by_path(str(alpha))
    beta_id = store.find_project_id_by_path(str(beta))
    assert store.get_project_inventory(alpha_id)["dirty"] is False
    assert store.get_project_inventory(beta_id)["dirty"] is True
    assert store.get_project_inventory(beta_id)["changed_count"] == 1
    assert store.get_project_inventory(beta_id)["default_branch"] == "main"

    # beta disappears; the next scan marks exactly it missing.
    import shutil

    shutil.rmtree(beta)
    runner2 = FakeGitRunner()
    runner2.set(alpha)
    result = discover_workspace(
        workspace_root=workspace,
        store=store,
        options=DiscoveryOptions(max_depth=3),
        git_runner=runner2,
    )
    assert result.missing_count == 1
    assert store.get_project(beta_id)["status"] == "missing"

    # beta returns: its status restores.
    beta = _marker_project(workspace, "beta")
    runner3 = FakeGitRunner()
    runner3.set(alpha)
    runner3.set(beta, branch="feature")
    result = discover_workspace(
        workspace_root=workspace, store=store, git_runner=runner3
    )
    assert result.missing_count == 0
    assert store.get_project(beta_id)["status"] == "active"
    assert store.get_project_inventory(beta_id)["missing_since"] is None


def test_persisted_discover_ignores_other_roots_and_narrower_depths(tmp_path: Path):
    workspace = tmp_path / "workspace"
    deep = _marker_project(workspace / "a" / "b", "deep")
    runner = FakeGitRunner()
    runner.set(deep)
    store = Store(tmp_path / "chrono.db")

    discover_workspace(workspace_root=workspace, store=store, git_runner=runner)
    project_id = store.find_project_id_by_path(str(deep))
    assert store.get_project(project_id)["status"] == "active"

    # A narrower scan of the same root must not mark the deep project missing.
    runner2 = FakeGitRunner()
    result = discover_workspace(
        workspace_root=workspace,
        store=store,
        options=DiscoveryOptions(max_depth=1),
        git_runner=runner2,
    )
    assert result.missing_count == 0
    assert store.get_project(project_id)["status"] == "active"

    # A scan rooted below the project is a different exact root.
    runner3 = FakeGitRunner()
    result = discover_workspace(
        workspace_root=workspace / "a",
        store=store,
        git_runner=runner3,
    )
    assert result.missing_count == 0
    assert store.get_project(project_id)["status"] == "active"


def test_persisted_discover_isolates_per_project_git_failures(tmp_path: Path):
    workspace = tmp_path / "workspace"
    alpha = _marker_project(workspace, "alpha")
    beta = _marker_project(workspace, "beta")
    runner = FakeGitRunner()
    runner.set(alpha)
    runner.set(beta, branch="feature", changed=("x.py",))
    store = Store(tmp_path / "chrono.db")
    discover_workspace(workspace_root=workspace, store=store, git_runner=runner)
    beta_id = store.find_project_id_by_path(str(beta))

    breaker = FakeGitRunner()
    breaker.set(alpha)
    breaker.set(beta, fail_status=True)
    result = discover_workspace(
        workspace_root=workspace, store=store, git_runner=breaker
    )

    assert result.ok is True
    assert result.refreshed_count == 1
    assert result.failed_count == 1
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure["project_id"] == beta_id
    assert failure["code"] == "git_failed"
    assert "x.py" not in json.dumps(result.failures)

    inventory = store.get_project_inventory(beta_id)
    assert inventory["last_error"] == {"code": "git_failed", "op": "status"}
    # Last successful Git fields are kept, not overwritten.
    assert inventory["branch"] == "feature"
    assert inventory["changed_count"] == 1
    assert inventory["dirty"] is True

    # The healthy project still refreshed.
    alpha_id = store.find_project_id_by_path(str(alpha))
    assert store.get_project_inventory(alpha_id)["last_error"] is None


def test_pure_traversal_without_store_never_runs_git_or_creates_database(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    _marker_project(workspace, "alpha")
    db = tmp_path / "absent.sqlite"
    runner = FakeGitRunner()

    result = discover_workspace(workspace_root=workspace, store=None, git_runner=runner)

    assert result.ok is True
    assert result.refreshed_count == 0
    assert result.missing_count == 0
    assert result.failed_count == 0
    assert result.failures == []
    assert runner.calls == []
    assert not db.exists()


def test_discover_result_dict_exposes_refresh_counts(tmp_path: Path):
    workspace = tmp_path / "workspace"
    _marker_project(workspace, "alpha")
    runner = FakeGitRunner()
    runner.set(workspace / "alpha")
    result = discover_workspace(
        workspace_root=workspace,
        store=Store(tmp_path / "chrono.db"),
        git_runner=runner,
    )
    payload = result.to_dict()
    assert payload["refreshed_count"] == 1
    assert payload["missing_count"] == 0
    assert payload["failed_count"] == 0
    assert payload["failures"] == []


# --- services ------------------------------------------------------------------


def test_refresh_workspace_inventory_service_envelope(tmp_path: Path):
    workspace = tmp_path / "workspace"
    alpha = _marker_project(workspace, "alpha")
    runner = FakeGitRunner()
    runner.set(alpha, changed=("a.py",))
    db = str(tmp_path / "chrono.db")

    result = services.refresh_workspace_inventory(
        db, workspace_root=str(workspace), git_runner=runner
    )

    assert result["ok"] is True
    assert result["workspace_root"] == str(workspace.resolve())
    assert result["discovered_count"] == 1
    assert result["persisted_count"] == 1
    assert result["refreshed_count"] == 1
    assert result["missing_count"] == 0
    assert result["failed_count"] == 0

    listed = services.list_projects(db, dirty=True)
    assert listed["count"] == 1
    assert listed["projects"][0]["inventory"]["changed_count"] == 1


def test_refresh_workspace_inventory_missing_root_reports_structured_failure(
    tmp_path: Path,
):
    db = str(tmp_path / "chrono.db")
    result = services.refresh_workspace_inventory(
        db, workspace_root=str(tmp_path / "missing")
    )
    assert result["ok"] is False
    assert result["skipped"][0]["reason"] == "workspace_root_not_found"
    assert result["missing_count"] == 0


def test_refresh_project_inventory_returns_project_show_shape(tmp_path: Path):
    workspace = tmp_path / "workspace"
    alpha = _marker_project(workspace, "alpha")
    db = str(tmp_path / "chrono.db")
    services.refresh_workspace_inventory(
        db, workspace_root=str(workspace), git_runner=FakeGitRunner()
    )

    runner = FakeGitRunner()
    runner.set(alpha, branch="feature", untracked=("n.txt",))
    result = services.refresh_project_inventory(db, "alpha", git_runner=runner)

    assert result["ok"] is True
    assert result["error"] is None
    project = result["project"]
    assert project["relative_path"] == "alpha"
    assert project["inventory"]["branch"] == "feature"
    assert project["inventory"]["untracked_count"] == 1
    assert any(argv[0] == "git" and argv[2] == str(alpha) for argv in runner.calls)


def test_refresh_project_inventory_migrates_v5_database_before_refresh(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    alpha = _marker_project(workspace, "alpha")
    db = tmp_path / "chrono-v5.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            relative_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            phase TEXT,
            lifecycle_phase TEXT,
            summary TEXT,
            priority TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            owner TEXT,
            description_usage TEXT,
            current_progress TEXT,
            notes TEXT,
            other_factors TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        """
    )
    for version in range(1, 6):
        conn.execute("INSERT INTO schema_migrations VALUES (?, 'seeded')", (version,))
    conn.execute(
        "INSERT INTO projects (id, name, path, relative_path, created_at, updated_at)"
        " VALUES ('alpha-0001', 'alpha', ?, 'alpha', 't0', 't1')",
        (str(alpha),),
    )
    conn.commit()
    conn.close()

    runner = FakeGitRunner()
    runner.set(alpha, branch="feature")
    result = services.refresh_project_inventory(str(db), "alpha", git_runner=runner)

    assert result["ok"] is True
    assert result["project"]["inventory"]["branch"] == "feature"
    conn = sqlite3.connect(db)
    try:
        assert conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 6"
        ).fetchone()
    finally:
        conn.close()


def test_inventory_refresh_services_can_be_called_consecutively(tmp_path: Path):
    workspace = tmp_path / "workspace"
    alpha = _marker_project(workspace, "alpha")
    db = str(tmp_path / "chrono.db")
    first_runner = FakeGitRunner()
    first_runner.set(alpha, branch="main")

    first = services.refresh_workspace_inventory(
        db, workspace_root=str(workspace), git_runner=first_runner
    )

    second_runner = FakeGitRunner()
    second_runner.set(alpha, branch="feature")
    second = services.refresh_project_inventory(db, "alpha", git_runner=second_runner)

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["project"]["inventory"]["branch"] == "feature"


def test_refresh_project_inventory_stable_errors(tmp_path: Path):
    db = str(tmp_path / "absent.sqlite")
    missing_db = services.refresh_project_inventory(db, "alpha")
    assert missing_db == {
        "ok": False,
        "code": "database_not_found",
        "db_path": db,
        "project": None,
    }
    assert not Path(db).exists()

    db = str(tmp_path / "chrono.db")
    store = services.open_store(db)
    _seed_catalog(store, "/ws/alpha", "alpha")
    store.close()

    unknown = services.refresh_project_inventory(db, "ghost")
    assert unknown["code"] == "project_not_found"

    gone = _marker_project(tmp_path, "gone")
    _seed_catalog(store, str(gone), "gone")
    store.close()
    import shutil

    shutil.rmtree(gone)
    vanished = services.refresh_project_inventory(db, "gone")
    assert vanished["ok"] is False
    assert vanished["code"] == "path_not_found"


def test_refresh_project_inventory_records_git_failure_and_keeps_fields(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    alpha = _marker_project(workspace, "alpha")
    db = str(tmp_path / "chrono.db")
    runner = FakeGitRunner()
    runner.set(alpha, branch="main", changed=("a.py",))
    services.refresh_workspace_inventory(
        db, workspace_root=str(workspace), git_runner=runner
    )

    breaker = FakeGitRunner()
    breaker.set(alpha, fail_status=True)
    result = services.refresh_project_inventory(db, "alpha", git_runner=breaker)

    assert result["ok"] is True
    assert result["error"] == {"code": "git_failed", "op": "status"}
    assert result["project"]["inventory"]["branch"] == "main"
    assert result["project"]["inventory"]["changed_count"] == 1


def test_service_reads_are_inventory_stale_not_refreshed(tmp_path: Path):
    workspace = tmp_path / "workspace"
    alpha = _marker_project(workspace, "alpha")
    db = str(tmp_path / "chrono.db")
    runner = FakeGitRunner()
    runner.set(alpha, branch="main")
    services.refresh_workspace_inventory(
        db, workspace_root=str(workspace), git_runner=runner
    )

    # The working tree becomes dirty after the refresh; reads must not re-run git.
    (alpha / "dirty.txt").write_text("changed\n", encoding="utf-8")

    shown = services.get_project(db, "alpha")
    assert shown["project"]["inventory"]["dirty"] is False
    listed = services.list_projects(db, dirty=True)
    assert listed["count"] == 0


def test_imported_projects_read_with_null_inventory(tmp_path: Path):
    registry = tmp_path / "registry.db"
    workspace = tmp_path / "workspace"
    conn = sqlite3.connect(registry)
    conn.executescript(
        """
        CREATE TABLE projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            relative_path TEXT NOT NULL,
            discovered_at TEXT NOT NULL,
            last_refreshed_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            missing_since TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            priority TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            owner TEXT,
            description_usage TEXT,
            summary TEXT,
            current_progress TEXT,
            notes TEXT,
            lifecycle_phase TEXT NOT NULL DEFAULT 'prototype',
            other_factors TEXT NOT NULL DEFAULT '{}',
            last_error TEXT
        );
        CREATE TABLE git_state (
            project_id TEXT PRIMARY KEY,
            branch TEXT,
            detached INTEGER NOT NULL DEFAULT 0,
            head_sha TEXT,
            head_subject TEXT,
            remote_name TEXT,
            remote_url TEXT,
            default_branch TEXT,
            dirty INTEGER NOT NULL DEFAULT 0,
            changed_count INTEGER NOT NULL DEFAULT 0,
            untracked_count INTEGER NOT NULL DEFAULT 0,
            collected_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO projects (project_id, name, path, relative_path, discovered_at,"
        " last_refreshed_at, last_seen_at) VALUES ('src-1', 'legacy',"
        " ?, 'legacy', 't0', 't1', 't2')",
        (str(workspace / "legacy"),),
    )
    conn.commit()
    conn.close()

    from chrono_core.integrations.workspace_intelligence import (
        import_workspace_intelligence,
    )

    store = Store(tmp_path / "chrono.db")
    result = import_workspace_intelligence(
        store, registry_path=registry, workspace_root=workspace
    )
    assert result.ok is True
    assert result.imported_count == 1

    shown = store.get_project(make_legacy_id())
    assert shown is not None
    assert shown["inventory"] is None


def make_legacy_id() -> str:
    from chrono_core.workspace.resolver import make_project_id

    return make_project_id("legacy")
