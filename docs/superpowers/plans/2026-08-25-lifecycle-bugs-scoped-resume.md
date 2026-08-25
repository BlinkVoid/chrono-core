# Lifecycle, Bugs & Scoped Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Truthful entity lifecycle (cancel/edit/reopen/supersede), cross-project bug tracking dogfooded on Chrono itself, and workstream-scoped resume that stops surfacing unrelated branches' actions.

**Architecture:** Thin `services.py` extraction shared by CLI and MCP frontends, then features built once in services. Schema v3 in one atomic ordered migration (lifecycle columns + bugs table + bug FTS + first indexes). Spec: `docs/superpowers/specs/2026-08-25-lifecycle-bugs-resume-design.md`.

**Tech Stack:** Python ≥3.12, stdlib sqlite3 (WAL), FastMCP, argparse, pytest.

## Global Constraints

- Run tests with `uv run pytest -q` from `~/workspace/cores/chrono-core`.
- Lint after every slice: `uv run ruff check src tests`.
- SQLite ≥3.35 required by double ON CONFLICT upserts (already assumed).
- MCP tool names use underscores, never dots (see `tests/unit/test_mcp_tool_names.py`).
- Timestamps are ISO-8601 UTC strings via `store.utc_now()`.
- License decision: MIT.
- Do not publish anything; GitHub phase is README + local HTML only.
- Follow existing code style: docstrings on public functions, minimal inline comments.

---

### Task 1: Branch-scoped resume queries in Store

**Files:**
- Modify: `src/chrono_core/store/store.py` (`get_resume_context`, lines 367-443)
- Modify: `src/chrono_core/domain/models.py` (`ResumeContext`)
- Test: `tests/unit/test_resume_scoping.py` (create)

**Interfaces:**
- Produces: `Store.get_resume_context(self, project_id: str, *, branch: str | None = None, include_all: bool = False, limit: int | None = 20) -> ResumeContext`. `ResumeContext` gains fields `branch: str = ""`, `hidden_actions: int = 0`, `hidden_blockers: int = 0` (included in `to_dict()`).

- [ ] **Step 1: Write failing regression test**

This reproduces the original defect: two work streams on two branches; default resume must surface only the current branch's items.

```python
import json
from pathlib import Path

from chrono_core.domain.models import GitState, HandoffPayload
from chrono_core.store.store import Store


def _seed(store: Store) -> str:
    store.init_schema()
    project_id = store.upsert_project(
        project_id="p_test", name="t", path="/tmp/t", relative_path="t"
    )
    for branch, text in (
        ("feat/novel", "novel action"),
        ("feat/platform", "platform action"),
    ):
        sid = store.create_session(
            project_id,
            HandoffPayload(summary=f"{branch} session"),
            GitState(branch=branch),
        )
        store.record_next_actions(project_id, sid, [text])
    return project_id


def test_default_resume_shows_only_current_branch_actions(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    pid = _seed(store)
    ctx = store.get_resume_context(pid, branch="feat/novel")
    texts = [a["text"] for a in ctx.next_actions]
    assert texts == ["novel action"]
    assert ctx.hidden_actions == 1
    assert ctx.branch == "feat/novel"


def test_include_all_returns_every_action(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    pid = _seed(store)
    ctx = store.get_resume_context(pid, include_all=True)
    assert len(ctx.next_actions) == 2
    assert ctx.hidden_actions == 0


def test_branchless_items_stay_visible(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.init_schema()
    pid = store.upsert_project(
        project_id="p_x", name="x", path="/tmp/x", relative_path="x"
    )
    store.record_next_actions(pid, None, ["legacy action"])
    ctx = store.get_resume_context(pid, branch="feat/main")
    assert [a["text"] for a in ctx.next_actions] == ["legacy action"]


def test_limit_bounds_lists_and_reports_hidden(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    pid = _seed(store)
    sid = store.create_session(
        pid, HandoffPayload(summary="s"), GitState(branch="feat/novel")
    )
    store.record_next_actions(pid, sid, ["a1", "a2"])
    ctx = store.get_resume_context(pid, branch="feat/novel", limit=2)
    assert len(ctx.next_actions) == 2
    assert ctx.hidden_actions == 1
    d = json.loads(json.dumps(ctx.to_dict()))
    assert d["hidden_actions"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_resume_scoping.py -q`
Expected: FAIL — `TypeError: get_resume_context() got an unexpected keyword argument 'branch'`

- [ ] **Step 3: Extend `ResumeContext`**

In `src/chrono_core/domain/models.py`, add fields and dict keys:

```python
@dataclass(frozen=True)
class ResumeContext:
    project_id: str
    project_name: str
    project_path: str
    current_status: str = ""
    summary: str = ""
    active_blockers: list[dict[str, Any]] = field(default_factory=list)
    next_actions: list[dict[str, Any]] = field(default_factory=list)
    recent_decisions: list[dict[str, Any]] = field(default_factory=list)
    branch: str = ""
    hidden_actions: int = 0
    hidden_blockers: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "project_path": self.project_path,
            "current_status": self.current_status,
            "summary": self.summary,
            "active_blockers": self.active_blockers,
            "next_actions": self.next_actions,
            "recent_decisions": self.recent_decisions,
            "branch": self.branch,
            "hidden_actions": self.hidden_actions,
            "hidden_blockers": self.hidden_blockers,
        }
```

- [ ] **Step 4: Rewrite `get_resume_context` in `src/chrono_core/store/store.py`**

Replace lines 367-443 with:

```python
    def get_resume_context(
        self,
        project_id: str,
        *,
        branch: str | None = None,
        include_all: bool = False,
        limit: int | None = 20,
    ) -> ResumeContext:
        conn = self._connect()
        project_row = conn.execute(
            "SELECT id, name, path, summary FROM projects WHERE id = ?", (project_id,)
        ).fetchone()

        if project_row is None:
            return ResumeContext(
                project_id=project_id,
                project_name="unknown",
                project_path="",
                current_status="No project found in continuity database.",
            )

        scoped = include_all or branch is None
        branch_filter = "" if scoped else """
            AND (s.git_branch IS NULL OR s.git_branch = :branch)
        """
        hidden_filter = "1=1" if scoped else """
            AND s.git_branch IS NOT NULL AND s.git_branch != :branch
        """

        session_row = conn.execute(
            """
            SELECT summary, git_branch, git_head, git_dirty
            FROM sessions
            WHERE project_id = :pid
            ORDER BY ended_at DESC
            LIMIT 1
            """,
            {"pid": project_id},
        ).fetchone()

        blockers = conn.execute(
            f"""
            SELECT b.id, b.title, b.status, b.detail
            FROM blockers b
            LEFT JOIN sessions s ON s.id = b.session_id
            WHERE b.project_id = :pid AND b.status = 'open'
            {branch_filter}
            ORDER BY b.created_at DESC
            {'' if limit is None else 'LIMIT :limit'}
            """,
            {"pid": project_id, "branch": branch, "limit": limit},
        ).fetchall()

        actions = conn.execute(
            f"""
            SELECT na.id, na.text, na.status, na.priority
            FROM next_actions na
            LEFT JOIN sessions s ON s.id = na.session_id
            WHERE na.project_id = :pid AND na.status = 'open'
            {branch_filter}
            ORDER BY na.created_at DESC
            {'' if limit is None else 'LIMIT :limit'}
            """,
            {"pid": project_id, "branch": branch, "limit": limit},
        ).fetchall()

        hidden_blockers = conn.execute(
            f"""
            SELECT COUNT(*) AS n
            FROM blockers b
            LEFT JOIN sessions s ON s.id = b.session_id
            WHERE b.project_id = :pid AND b.status = 'open' AND {hidden_filter}
            """,
            {"pid": project_id, "branch": branch},
        ).fetchone()["n"]

        hidden_actions = conn.execute(
            f"""
            SELECT COUNT(*) AS n
            FROM next_actions na
            LEFT JOIN sessions s ON s.id = na.session_id
            WHERE na.project_id = :pid AND na.status = 'open' AND {hidden_filter}
            """,
            {"pid": project_id, "branch": branch},
        ).fetchone()["n"]

        decisions = conn.execute(
            """
            SELECT id, title, rationale, status
            FROM decisions
            WHERE project_id = ?
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (project_id,),
        ).fetchall()

        current_status = ""
        summary = ""
        if session_row:
            summary = session_row["summary"] or ""
            dirty_flag = bool(session_row["git_dirty"])
            dirty_text = " (dirty)" if dirty_flag else ""
            branch_name = session_row["git_branch"] or "unknown"
            current_status = f"Latest session on {branch_name}{dirty_text}."
        else:
            current_status = "No sessions captured yet."

        return ResumeContext(
            project_id=project_id,
            project_name=project_row["name"],
            project_path=project_row["path"],
            current_status=current_status,
            summary=summary,
            active_blockers=[dict(row) for row in blockers],
            next_actions=[dict(row) for row in actions],
            recent_decisions=[dict(row) for row in decisions],
            branch=branch or "",
            hidden_actions=hidden_actions,
            hidden_blockers=hidden_blockers,
        )
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_resume_scoping.py tests/unit/test_resume.py tests/unit/test_resume_budget.py tests/unit/test_mcp_server.py -q`
Expected: all PASS (existing callers use positional project_id only; defaults keep old flat behavior when `branch=None`)

- [ ] **Step 6: Commit**

```bash
git add src/chrono_core/domain/models.py src/chrono_core/store/store.py tests/unit/test_resume_scoping.py
git commit -m "feat: branch-scoped resume queries with limits and hidden counts"
```

---

### Task 2: Resume service detects branch; CLI flags

**Files:**
- Modify: `src/chrono_core/resume.py`
- Modify: `src/chrono_core/cli.py` (resume subparser, lines 36-42)
- Test: `tests/unit/test_resume_cli_scope.py` (create)

**Interfaces:**
- Consumes: `Store.get_resume_context(..., branch, include_all, limit)` from Task 1; `capture.git.read_git_state(Path) -> GitState`.
- Produces: CLI flags `chrono resume [--all] [--branch NAME] [--limit N]`; text output footer `(+N more on other branches: --all to show)` when hidden > 0; JSON includes `branch`/`hidden_*`.

- [ ] **Step 1: Write failing test**

```python
import json
from pathlib import Path

from chrono_core.cli import main


def test_resume_json_reports_branch_scoping(tmp_path: Path, capsys):
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / ".git").mkdir()
    db = tmp_path / "db.sqlite"
    ws = tmp_path / "ws"
    ws.mkdir()

    import subprocess

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True)

    git("init", "-b", "feat/novel")
    git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (repo / "f.txt").write_text("x")
    git("add", "."); git("commit", "-m", "init")

    from chrono_core.store.store import Store
    from chrono_core.domain.models import GitState, HandoffPayload

    store = Store(db)
    store.init_schema()
    pid = store.upsert_project(
        project_id="p_r", name="r", path=str(repo), relative_path="proj"
    )
    other = store.create_session(
        pid, HandoffPayload(summary="other"), GitState(branch="feat/platform")
    )
    store.record_next_actions(pid, other, ["unrelated platform action"])

    rc = main([
        "resume", "--cwd", str(repo), "--workspace-root", str(ws),
        "--db-path", str(db), "--json",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["branch"] == "feat/novel"
    assert out["hidden_actions"] == 1
    assert all(a["text"] != "unrelated platform action" for a in out["next_actions"])

    rc = main([
        "resume", "--cwd", str(repo), "--workspace-root", str(ws),
        "--db-path", str(db), "--all", "--json",
    ])
    out = json.loads(capsys.readouterr().out)
    assert len(out["next_actions"]) == 1


def test_resume_text_footer_mentions_hidden(tmp_path: Path, capsys):
    repo = tmp_path / "proj"
    (repo / ".git").mkdir()
    db = tmp_path / "db.sqlite"

    from chrono_core.store.store import Store
    from chrono_core.domain.models import GitState, HandoffPayload

    store = Store(db)
    store.init_schema()
    pid = store.upsert_project(
        project_id="p_f", name="f", path=str(repo), relative_path="proj"
    )
    other = store.create_session(
        pid, HandoffPayload(summary="o"), GitState(branch="feat/other")
    )
    store.record_next_actions(pid, other, ["far away action"])

    class Args:
        cwd = str(repo)
        workspace_root = str(tmp_path / "ws")
        db_path = str(db)
        json = False
        all = False
        branch = "main"
        limit = 20

    from chrono_core.resume import resume_command

    assert resume_command(Args()) == 0
    out = capsys.readouterr().out
    assert "(+1 more on other branches: --all to show)" in out
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_resume_cli_scope.py -q`
Expected: FAIL — argparse error `unrecognized arguments: --all` / missing footer.

- [ ] **Step 3: Add CLI flags**

In `src/chrono_core/cli.py`, inside the `p_resume` block after `--json`:

```python
    p_resume.add_argument("--all", action="store_true", help="show actions from all branches")
    p_resume.add_argument("--branch", default=None, help="override the workstream branch")
    p_resume.add_argument(
        "--limit", type=int, default=20, help="max open items per category"
    )
```

- [ ] **Step 4: Wire flags through `src/chrono_core/resume.py`**

Replace `get_resume_context` and `format_resume` bodies:

```python
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from chrono_core.capture.git import read_git_state
from chrono_core.config import default_db_path, default_workspace_root
from chrono_core.domain.models import ResumeContext
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


def validate_resume_path(context: ResumeContext) -> ResumeContext:
    """Reject stored project locations that can no longer be resumed safely."""
    if context.project_path and not Path(context.project_path).is_dir():
        raise FileNotFoundError(
            f"stored resume path no longer exists: {context.project_path}"
        )
    return context


def get_resume_context(args: Namespace) -> ResumeContext:
    """Resolve project and return branch-scoped resume context from the store."""
    project_path = Path(getattr(args, "cwd", "."))
    workspace_root = Path(getattr(args, "workspace_root", None) or default_workspace_root())
    project = resolve_project(project_path, workspace_root=workspace_root)

    db_path = getattr(args, "db_path", None) or default_db_path()
    store = Store(db_path)
    store.init_schema()

    include_all = getattr(args, "all", False)
    branch = getattr(args, "branch", None)
    if not include_all and branch is None:
        branch = read_git_state(project_path).branch

    context = store.get_resume_context(
        store.resolve_project_id(project),
        branch=branch,
        include_all=include_all,
        limit=getattr(args, "limit", 20),
    )
    return validate_resume_path(context)


def format_resume(context: ResumeContext, *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(context.to_dict(), indent=2)

    lines: list[str] = [
        f"Project: {context.project_name}",
        f"Path: {context.project_path}",
    ]
    if context.current_status:
        lines.append(f"Status: {context.current_status}")
    if context.summary:
        lines.append(f"Latest session: {context.summary}")

    scope = "all branches" if context.branch == "" else context.branch
    if context.active_blockers:
        lines.append(f"\nOpen blockers ({scope}):")
        for blocker in context.active_blockers:
            lines.append(f"  - [{blocker.get('id', '')}] {blocker.get('title', '')}")
        if context.hidden_blockers:
            lines.append(
                f"  (+{context.hidden_blockers} more on other branches: --all to show)"
            )

    if context.next_actions:
        lines.append(f"\nNext actions ({scope}):")
        for action in context.next_actions:
            lines.append(f"  - [{action.get('id', '')}] {action.get('text', '')}")
        if context.hidden_actions:
            lines.append(
                f"  (+{context.hidden_actions} more on other branches: --all to show)"
            )

    if context.recent_decisions:
        lines.append("\nRecent decisions:")
        for decision in context.recent_decisions:
            lines.append(f"  - {decision.get('title', '')}")

    return "\n".join(lines)


def resume_command(args: Namespace) -> int:
    """CLI entry point for chrono resume."""
    context = get_resume_context(args)
    as_json = getattr(args, "json", False)
    print(format_resume(context, as_json=as_json))
    return 0
```

Note: delete the now-unused `_default_db_path` helper and its import indirection; `tests/unit/test_default_db_path.py` references `chrono_core.resume._default_db_path` — update that test to call `chrono_core.config.default_db_path()` instead.

- [ ] **Step 5: Run full unit suite**

Run: `uv run pytest tests/unit -q`
Expected: PASS (fix the `_default_db_path` test reference noted above)

- [ ] **Step 6: Dogfood verification on real data**

Run: `chrono resume --cwd ~/workspace/InternalProject | head -20`
Expected: header shows `(feat/...)` scope; far fewer actions than before; footer reports hidden count.

- [ ] **Step 7: Commit**

```bash
git add src/chrono_core/resume.py src/chrono_core/cli.py tests/unit/test_resume_cli_scope.py tests/unit/test_default_db_path.py
git commit -m "feat: resume scopes to current git branch by default with --all/--branch/--limit"
```

---

### Task 3: Ordered migration framework + schema v3

One atomic v3 migration: lifecycle columns, `bugs` table + `bug_fts` + triggers, first indexes.

**Files:**
- Create: `src/chrono_core/store/migrations.py`
- Modify: `src/chrono_core/store/schema.py`
- Modify: `src/chrono_core/store/store.py` (`init_schema`)
- Test: `tests/unit/test_migration_v3.py` (create)

**Interfaces:**
- Produces: `schema.SCHEMA_VERSION == 3`; `migrations.MIGRATIONS: list[tuple[int, str]]` (version, label) with `apply_pending(conn)`; new columns usable in Tasks 4/8: `next_actions.cancelled_at TEXT`, `next_actions.supersedes_id TEXT`, `next_actions.raw_history_json TEXT DEFAULT '[]'`, `blockers.cancelled_at TEXT`; `bugs(id, project_id NULLABLE, title, detail, severity, status, found_in_session_id, fixed_in_session_id, remote_url, remote_issue_id, created_at, updated_at, resolved_at)`.

- [ ] **Step 1: Write failing migration test**

```python
import sqlite3
from pathlib import Path

import pytest

from chrono_core.store.migrations import SCHEMA_VERSION, apply_pending
from chrono_core.store.schema import DDL


def _fresh(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.executescript(DDL)
    return conn


def test_v3_adds_lifecycle_columns_bugs_and_indexes(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    conn.row_factory = sqlite3.Row
    _fresh(conn)
    apply_pending(conn)

    cols = {
        r["name"]
        for r in conn.execute("PRAGMA table_info(next_actions)").fetchall()
    }
    assert {"cancelled_at", "supersedes_id", "raw_history_json"} <= cols
    assert "cancelled_at" in {
        r["name"] for r in conn.execute("PRAGMA table_info(blockers)").fetchall()
    }

    bug_cols = {
        r["name"]: r for r in conn.execute("PRAGMA table_info(bugs)").fetchall()
    }
    assert bug_cols["project_id"]["notnull"] == 0
    indexes = {
        r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    assert "idx_sessions_proj_ended" in indexes
    assert "idx_actions_proj_status_created" in indexes
    assert "idx_bugs_proj_status_created" in indexes
    applied = {
        r["version"] for r in conn.execute("SELECT version FROM schema_migrations")
    }
    assert applied == set(range(1, SCHEMA_VERSION + 1))


def test_refuses_newer_database(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    conn.row_factory = sqlite3.Row
    _fresh(conn)
    conn.execute("INSERT INTO schema_migrations VALUES (99, 'future')")
    with pytest.raises(RuntimeError, match="newer"):
        apply_pending(conn)
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/unit/test_migration_v3.py -q`
Expected: FAIL — `ModuleNotFoundError: chrono_core.store.migrations`

- [ ] **Step 3: Create `src/chrono_core/store/migrations.py`**

```python
from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 3

_V3_LIFECYCLE_BUGS = [
    "ALTER TABLE next_actions ADD COLUMN cancelled_at TEXT",
    "ALTER TABLE next_actions ADD COLUMN supersedes_id TEXT REFERENCES next_actions(id)",
    "ALTER TABLE next_actions ADD COLUMN raw_history_json TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE blockers ADD COLUMN cancelled_at TEXT",
    """
    CREATE TABLE IF NOT EXISTS bugs (
        id TEXT PRIMARY KEY,
        project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        severity TEXT NOT NULL DEFAULT 'medium',
        status TEXT NOT NULL DEFAULT 'open',
        found_in_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
        fixed_in_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
        remote_url TEXT,
        remote_issue_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        resolved_at TEXT
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS bug_fts USING fts5(
        title, detail, content='bugs', content_rowid='rowid'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS bugs_fts_insert
    AFTER INSERT ON bugs BEGIN
        INSERT INTO bug_fts (rowid, title, detail) VALUES (new.rowid, new.title, new.detail);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS bugs_fts_delete
    AFTER DELETE ON bugs BEGIN
        INSERT INTO bug_fts (bug_fts, rowid, title, detail)
        VALUES ('delete', old.rowid, old.title, old.detail);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS bugs_fts_update
    AFTER UPDATE ON bugs BEGIN
        INSERT INTO bug_fts (bug_fts, rowid, title, detail)
        VALUES ('delete', old.rowid, old.title, old.detail);
        INSERT INTO bug_fts (rowid, title, detail) VALUES (new.rowid, new.title, new.detail);
    END
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_proj_ended ON sessions(project_id, ended_at)",
    "CREATE INDEX IF NOT EXISTS idx_actions_proj_status_created"
    " ON next_actions(project_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_blockers_proj_status_created"
    " ON blockers(project_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_bugs_proj_status_created"
    " ON bugs(project_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_decisions_proj_created ON decisions(project_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_observations_proj ON observations(project_id)",
]

_MIGRATIONS: dict[int, list[str]] = {
    3: _V3_LIFECYCLE_BUGS,
}


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row["version"] for row in rows}


def apply_pending(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations in order; refuse newer-than-code databases."""
    applied = applied_versions(conn)
    newest = max(applied, default=0)
    if newest > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema version {newest} is newer than supported {SCHEMA_VERSION}"
        )
    ran: list[int] = []
    for version in sorted(_MIGRATIONS):
        if version in applied:
            continue
        for statement in _MIGRATIONS[version]:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at)"
            " VALUES (?, datetime('now'))",
            (version,),
        )
        ran.append(version)
    return ran
```

- [ ] **Step 4: Update `schema.py` and `init_schema`**

In `schema.py`: bump `SCHEMA_VERSION = 3`. In `store.py` replace the body of `init_schema` after `executescript(DDL)`:

```python
    def init_schema(self) -> None:
        conn = self._connect()
        conn.executescript(DDL)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        from chrono_core.store.migrations import apply_pending

        # Version 2 backfilled FTS via rebuild for pre-trigger rows.
        applied = {
            row["version"] for row in conn.execute("SELECT version FROM schema_migrations")
        }
        if SCHEMA_VERSION >= 2 and 2 not in applied:
            conn.execute("INSERT INTO observation_fts (observation_fts) VALUES ('rebuild')")
        apply_pending(conn)
        self._commit()
```

Keep the top-level import `from chrono_core.store.schema import DDL, SCHEMA_VERSION` (already present). Note `sqlite3.Row` access by name in migrations requires row_factory — `apply_pending` runs on connections created by `Store._connect` (Row factory set) and by the test which sets it explicitly.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_migration_v3.py tests/unit/test_search.py tests/unit/test_store.py tests/unit/test_identity_migration.py -q`
Expected: PASS (fresh DBs get v3; existing v2 DBs upgrade; identity migration unaffected because it operates on raw tables)

- [ ] **Step 6: Commit**

```bash
git add src/chrono_core/store/migrations.py src/chrono_core/store/schema.py src/chrono_core/store/store.py tests/unit/test_migration_v3.py
git commit -m "feat: ordered migration framework and schema v3 (lifecycle columns, bugs table, indexes)"
```

---

### Task 4: Store lifecycle methods with idempotency

**Files:**
- Modify: `src/chrono_core/domain/models.py` (status constants)
- Modify: `src/chrono_core/store/store.py`
- Test: `tests/unit/test_lifecycle_verbs.py` (create)

**Interfaces:**
- Consumes: v3 columns from Task 3.
- Produces (all return `dict[str, Any]` with keys `ok`, `already`, `<entity>_id`, `status`; unknown id → `{"ok": False, "<entity>_id": id, "status": "not_found"}`):
  - `Store.cancel_next_action(action_id: str, reason: str | None = None) -> dict`
  - `Store.edit_next_action(action_id: str, new_text: str) -> dict`
  - `Store.reopen_next_action(action_id: str) -> dict`
  - `Store.supersede_next_action(old_action_id: str, new_text: str) -> dict` (extra key `new_action_id`)
  - `Store.cancel_blocker(blocker_id: str, reason: str | None = None) -> dict`
  - `Store.edit_blocker(blocker_id: str, new_title: str) -> dict`
  - `Store.reopen_blocker(blocker_id: str) -> dict`

- [ ] **Step 1: Add constants to `domain/models.py`**

```python
ACTION_STATUSES = ("open", "done", "cancelled", "superseded")
BLOCKER_STATUSES = ("open", "resolved", "cancelled")
BUG_SEVERITIES = ("low", "medium", "high", "critical")
BUG_STATUSES = ("open", "confirmed", "in_progress", "fixed", "wont_fix", "cancelled")
```

- [ ] **Step 2: Write failing tests**

```python
from chrono_core.store.store import Store


def _seed_action(store: Store, text: str = "do thing") -> str:
    store.init_schema()
    pid = store.upsert_project(project_id="p", name="p", path="/tmp/p", relative_path="p")
    ids = []
    store.record_next_actions(pid, None, [text])
    row = store._connect().execute(
        "SELECT id FROM next_actions ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return row["id"]


def test_cancel_then_reopen(tmp_path):
    store = Store(tmp_path / "d.db")
    aid = _seed_action(store)
    r1 = store.cancel_next_action(aid, reason="stale")
    assert r1 == {"ok": True, "already": False, "action_id": aid, "status": "cancelled"}
    r2 = store.cancel_next_action(aid)
    assert r2["already"] is True
    history = store._connect().execute(
        "SELECT raw_history_json, cancelled_at FROM next_actions WHERE id=?", (aid,)
    ).fetchone()
    assert "stale" in history["raw_history_json"]
    assert history["cancelled_at"]
    r3 = store.reopen_next_action(aid)
    assert r3["status"] == "open"


def test_edit_appends_history(tmp_path):
    store = Store(tmp_path / "d.db")
    aid = _seed_action(store, "old text")
    r = store.edit_next_action(aid, "corrected text")
    assert r["ok"] is True
    row = store._connect().execute(
        "SELECT text, raw_history_json FROM next_actions WHERE id=?", (aid,)
    ).fetchone()
    assert row["text"] == "corrected text"
    assert "old text" in row["raw_history_json"]


def test_supersede_links_new_to_old(tmp_path):
    store = Store(tmp_path / "d.db")
    old_id = _seed_action(store, "wrong wording")
    r = store.supersede_next_action(old_id, "right wording")
    assert r["ok"] is True and r["status"] == "superseded"
    new_id = r["new_action_id"]
    row = store._connect().execute(
        "SELECT supersedes_id, status FROM next_actions WHERE id=?", (new_id,)
    ).fetchone()
    assert row["supersedes_id"] == old_id
    assert row["status"] == "open"


def test_unknown_id_not_found(tmp_path):
    store = Store(tmp_path / "d.db")
    store.init_schema()
    assert store.cancel_next_action("act_missing")["status"] == "not_found"
    assert store.edit_blocker("blk_missing", "x")["status"] == "not_found"
```

Add symmetric blocker cases (`cancel_blocker` sets `cancelled`+`cancelled_at`; `reopen_blocker` returns to `open`; `edit_blocker` swaps title with history) inside the same file, mirroring the action assertions above.

- [ ] **Step 3: Verify failure**

Run: `uv run pytest tests/unit/test_lifecycle_verbs.py -q`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'cancel_next_action'`

- [ ] **Step 4: Implement in `store.py`**

Add imports at top: `from chrono_core.domain.models import ACTION_STATUSES, BLOCKER_STATUSES` (extend the existing models import). Then:

```python
    @staticmethod
    def _append_history(current_json: str | None, entry: dict[str, Any]) -> str:
        import json as _json

        try:
            history = _json.loads(current_json or "[]")
        except ValueError:
            history = []
        history.append(entry)
        return _json.dumps(history, ensure_ascii=False)

    def _load_entity(self, table: str, entity_id: str) -> sqlite3.Row | None:
        return self._connect().execute(
            f"SELECT * FROM {table} WHERE id = ?", (entity_id,)
        ).fetchone()

    def cancel_next_action(self, action_id: str, reason: str | None = None) -> dict[str, Any]:
        row = self._load_entity("next_actions", action_id)
        if row is None:
            return {"ok": False, "action_id": action_id, "status": "not_found"}
        if row["status"] == "cancelled":
            return {"ok": True, "already": True, "action_id": action_id, "status": "cancelled"}
        now = utc_now()
        conn = self._connect()
        conn.execute(
            """
            UPDATE next_actions
            SET status = 'cancelled', cancelled_at = ?, raw_history_json = ?
            WHERE id = ?
            """,
            (
                now,
                self._append_history(
                    row["raw_history_json"],
                    {"op": "cancel", "at": now, "reason": reason or ""},
                ),
                action_id,
            ),
        )
        self._commit()
        return {"ok": True, "already": False, "action_id": action_id, "status": "cancelled"}

    def reopen_next_action(self, action_id: str) -> dict[str, Any]:
        row = self._load_entity("next_actions", action_id)
        if row is None:
            return {"ok": False, "action_id": action_id, "status": "not_found"}
        if row["status"] == "open":
            return {"ok": True, "already": True, "action_id": action_id, "status": "open"}
        conn = self._connect()
        conn.execute(
            """
            UPDATE next_actions
            SET status = 'open', completed_at = NULL, cancelled_at = NULL,
                raw_history_json = ?
            WHERE id = ?
            """,
            (
                self._append_history(
                    row["raw_history_json"], {"op": "reopen", "at": utc_now()}
                ),
                action_id,
            ),
        )
        self._commit()
        return {"ok": True, "already": False, "action_id": action_id, "status": "open"}

    def edit_next_action(self, action_id: str, new_text: str) -> dict[str, Any]:
        row = self._load_entity("next_actions", action_id)
        if row is None:
            return {"ok": False, "action_id": action_id, "status": "not_found"}
        now = utc_now()
        conn = self._connect()
        conn.execute(
            """
            UPDATE next_actions
            SET text = ?, raw_history_json = ?
            WHERE id = ?
            """,
            (
                new_text,
                self._append_history(
                    row["raw_history_json"],
                    {"op": "edit", "at": now, "previous_text": row["text"]},
                ),
                action_id,
            ),
        )
        self._commit()
        return {"ok": True, "already": False, "action_id": action_id, "status": row["status"]}

    def supersede_next_action(self, old_action_id: str, new_text: str) -> dict[str, Any]:
        old = self._load_entity("next_actions", old_action_id)
        if old is None:
            return {"ok": False, "action_id": old_action_id, "status": "not_found"}
        if old["status"] == "superseded":
            return {
                "ok": True, "already": True, "action_id": old_action_id,
                "status": "superseded", "new_action_id": None,
            }
        now = utc_now()
        new_id = make_entity_id("act")
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO next_actions
                (id, project_id, session_id, text, status, supersedes_id, created_at)
            VALUES (?, ?, ?, ?, 'open', ?, ?)
            """,
            (new_id, old["project_id"], old["session_id"], new_text, old_action_id, now),
        )
        conn.execute(
            """
            UPDATE next_actions
            SET status = 'superseded', raw_history_json = ?
            WHERE id = ?
            """,
            (
                self._append_history(
                    old["raw_history_json"],
                    {"op": "superseded_by", "at": now, "successor": new_id},
                ),
                old_action_id,
            ),
        )
        self._commit()
        return {
            "ok": True, "already": False, "action_id": old_action_id,
            "status": "superseded", "new_action_id": new_id,
        }

    def cancel_blocker(self, blocker_id: str, reason: str | None = None) -> dict[str, Any]:
        row = self._load_entity("blockers", blocker_id)
        if row is None:
            return {"ok": False, "blocker_id": blocker_id, "status": "not_found"}
        if row["status"] == "cancelled":
            return {"ok": True, "already": True, "blocker_id": blocker_id, "status": "cancelled"}
        conn = self._connect()
        conn.execute(
            "UPDATE blockers SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
            (utc_now(), blocker_id),
        )
        self._commit()
        return {"ok": True, "already": False, "blocker_id": blocker_id, "status": "cancelled"}

    def edit_blocker(self, blocker_id: str, new_title: str) -> dict[str, Any]:
        row = self._load_entity("blockers", blocker_id)
        if row is None:
            return {"ok": False, "blocker_id": blocker_id, "status": "not_found"}
        conn = self._connect()
        conn.execute("UPDATE blockers SET title = ? WHERE id = ?", (new_title, blocker_id))
        self._commit()
        return {"ok": True, "already": False, "blocker_id": blocker_id, "status": row["status"]}

    def reopen_blocker(self, blocker_id: str) -> dict[str, Any]:
        row = self._load_entity("blockers", blocker_id)
        if row is None:
            return {"ok": False, "blocker_id": blocker_id, "status": "not_found"}
        if row["status"] == "open":
            return {"ok": True, "already": True, "blocker_id": blocker_id, "status": "open"}
        conn = self._connect()
        conn.execute(
            "UPDATE blockers SET status = 'open', resolved_at = NULL, cancelled_at = NULL"
            " WHERE id = ?",
            (blocker_id,),
        )
        self._commit()
        return {"ok": True, "already": False, "blocker_id": blocker_id, "status": "open"}
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_lifecycle_verbs.py tests/unit/test_lifecycle.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/chrono_core/domain/models.py src/chrono_core/store/store.py tests/unit/test_lifecycle_verbs.py
git commit -m "feat: store-level cancel/edit/reopen/supersede for actions and blockers"
```

---

### Task 5: services.py extraction + CLI lifecycle verbs

**Files:**
- Create: `src/chrono_core/services.py`
- Modify: `src/chrono_core/cli.py`
- Test: `tests/unit/test_services_lifecycle.py` (create)

**Interfaces:**
- Consumes: Store methods from Task 4; `resolve_project`.
- Produces (used again by Task 6 MCP and Tasks 8-10 bugs):
  - `open_store(db_path: str | None) -> Store` (opens, init_schema, cached per path)
  - `resolve_project_id_from(cwd: str, workspace_root: str | None, store: Store) -> str`
  - `lifecycle_result(entity: str, verb: str, result: dict) -> dict` — canonical envelope `{"ok", "<entity>_id", "verb", "status", "already"?}`
  - `cancel_action(db_path, action_id, reason=None) -> dict`, `complete_action(db_path, action_id) -> dict`, plus `edit_action/reopen_action/supersede_action/cancel_blocker/edit_blocker/reopen_blocker/resolve_blocker` with analogous signatures.

- [ ] **Step 1: Write failing service tests**

```python
from pathlib import Path

from chrono_core.services import (
    cancel_action,
    edit_action,
    open_store,
    reopen_action,
    supersede_action,
)


def _seed(db_path: Path) -> str:
    store = open_store(str(db_path))
    pid = store.upsert_project(project_id="p", name="p", path="/tmp/p", relative_path="p")
    store.record_next_actions(pid, None, ["first cut"])
    return store._connect().execute(
        "SELECT id FROM next_actions LIMIT 1"
    ).fetchone()["id"]


def test_service_roundtrip(tmp_path: Path):
    db = str(tmp_path / "s.db")
    aid = _seed(tmp_path / "s.db")

    edited = edit_action(db, aid, "second cut")
    assert edited["ok"] is True and edited["verb"] == "edit"

    cancelled = cancel_action(db, aid, reason="obsolete")
    assert cancelled["ok"] is True and cancelled["status"] == "cancelled"

    reopened = reopen_action(db, aid)
    assert reopened["status"] == "open"

    sup = supersede_action(db, aid, "third cut")
    assert sup["new_action_id"].startswith("act_")


def test_open_store_is_cached(tmp_path: Path):
    db = str(tmp_path / "c.db")
    s1 = open_store(db)
    s2 = open_store(db)
    assert s1 is s2
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/unit/test_services_lifecycle.py -q`
Expected: FAIL — `ModuleNotFoundError: chrono_core.services`

- [ ] **Step 3: Implement `src/chrono_core/services.py`**

```python
"""Shared operations used by both the CLI and the MCP server."""
from __future__ import annotations

from typing import Any

from chrono_core.store.store import Store

_STORES: dict[str, Store] = {}


def open_store(db_path: str | None = None) -> Store:
    """Open (and cache per resolved path) a schema-initialized Store."""
    resolved = str(db_path) if db_path else default_db_path()
    store = _STORES.get(resolved)
    if store is None:
        store = Store(resolved)
        store.init_schema()
        _STORES[resolved] = store
    return store


def close_stores() -> None:
    for store in _STORES.values():
        store.close()
    _STORES.clear()


def resolve_project_id_from(cwd: str, workspace_root: str | None, store: Store) -> str:
    from chrono_core.config import default_workspace_root
    from chrono_core.workspace.resolver import resolve_project

    project = resolve_project(
        Path(cwd), workspace_root=Path(workspace_root or default_workspace_root())
    )
    return store.resolve_project_id(project)


def lifecycle_result(entity: str, verb: str, result: dict[str, Any]) -> dict[str, Any]:
    out = {"ok": result.get("ok", False), f"{entity}_id": result.get(f"{entity}_id")}
    out.update({k: v for k, v in result.items() if k not in out})
    out["verb"] = verb
    return out
```

Add top-of-file imports `from pathlib import Path` and `from chrono_core.config import default_db_path`. Then one thin wrapper per verb, e.g.:

```python
def cancel_action(
    db_path: str | None, action_id: str, reason: str | None = None
) -> dict[str, Any]:
    return lifecycle_result(
        "action", "cancel", open_store(db_path).cancel_next_action(action_id, reason)
    )


def complete_action(db_path: str | None, action_id: str) -> dict[str, Any]:
    return lifecycle_result(
        "action", "complete", open_store(db_path).complete_next_action(action_id)
    )


def edit_action(db_path: str | None, action_id: str, text: str) -> dict[str, Any]:
    return lifecycle_result(
        "action", "edit", open_store(db_path).edit_next_action(action_id, text)
    )


def reopen_action(db_path: str | None, action_id: str) -> dict[str, Any]:
    return lifecycle_result(
        "action", "reopen", open_store(db_path).reopen_next_action(action_id)
    )


def supersede_action(db_path: str | None, action_id: str, text: str) -> dict[str, Any]:
    return lifecycle_result(
        "action", "supersede", open_store(db_path).supersede_next_action(action_id, text)
    )
```

Write the five analogous blocker wrappers (`resolve_blocker`, `cancel_blocker`, `edit_blocker`, `reopen_blocker`) using `"blocker"` as the entity and the matching Store methods (`edit_blocker` takes `title: str`). Also refactor the two existing CLI/MCP duplicated envelopes to call these (see Step 4).

- [ ] **Step 4: Rewire CLI lifecycle paths**

In `src/chrono_core/cli.py`, replace the `blocker`/`action` command bodies:

```python
    if args.command == "blocker":
        if args.blocker_command == "resolve":
            result = services.resolve_blocker(args.db_path, args.blocker_id)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if args.blocker_command == "cancel":
            result = services.cancel_blocker(args.db_path, args.blocker_id, args.reason)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if args.blocker_command == "edit":
            result = services.edit_blocker(args.db_path, args.blocker_id, args.text)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if args.blocker_command == "reopen":
            result = services.reopen_blocker(args.db_path, args.blocker_id)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        parser.error("blocker requires a subcommand")

    if args.command == "action":
        handlers = {
            "complete": lambda: services.complete_action(args.db_path, args.action_id),
            "cancel": lambda: services.cancel_action(args.db_path, args.action_id, args.reason),
            "edit": lambda: services.edit_action(args.db_path, args.action_id, args.text),
            "reopen": lambda: services.reopen_action(args.db_path, args.action_id),
            "supersede": lambda: services.supersede_action(args.db_path, args.action_id, args.text),
        }
        handler = handlers.get(args.action_command)
        if handler is None:
            parser.error("action requires a subcommand")
        result = handler()
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
```

Add `from chrono_core import services` import. Extend the parsers (after the existing `complete` subparser):

```python
    p_action_cancel = action_sub.add_parser("cancel", help="close an action as cancelled")
    p_action_cancel.add_argument("action_id")
    p_action_cancel.add_argument("--reason", default=None)
    p_action_cancel.add_argument("--db-path", "--db", default=DEFAULT_DB_PATH)

    p_action_edit = action_sub.add_parser("edit", help="rewrite an action's text")
    p_action_edit.add_argument("action_id")
    p_action_edit.add_argument("--text", required=True)
    p_action_edit.add_argument("--db-path", "--db", default=DEFAULT_DB_PATH)

    p_action_reopen = action_sub.add_parser("reopen", help="return a closed action to open")
    p_action_reopen.add_argument("action_id")
    p_action_reopen.add_argument("--db-path", "--db", default=DEFAULT_DB_PATH)

    p_action_supersede = action_sub.add_parser(
        "supersede", help="replace an action with corrected text, keeping both"
    )
    p_action_supersede.add_argument("action_id")
    p_action_supersede.add_argument("--text", required=True)
    p_action_supersede.add_argument("--db-path", "--db", default=DEFAULT_DB_PATH)

    p_blocker_cancel = blocker_sub.add_parser("cancel", help="close a blocker as cancelled")
    p_blocker_cancel.add_argument("blocker_id")
    p_blocker_cancel.add_argument("--reason", default=None)
    p_blocker_cancel.add_argument("--db-path", "--db", default=DEFAULT_DB_PATH)

    p_blocker_edit = blocker_sub.add_parser("edit", help="rewrite a blocker's title")
    p_blocker_edit.add_argument("blocker_id")
    p_blocker_edit.add_argument("--text", required=True)
    p_blocker_edit.add_argument("--db-path", "--db", default=DEFAULT_DB_PATH)

    p_blocker_reopen = blocker_sub.add_parser("reopen", help="return a closed blocker to open")
    p_blocker_reopen.add_argument("blocker_id")
    p_blocker_reopen.add_argument("--db-path", "--db", default=DEFAULT_DB_PATH)
```

Update the existing `p_blocker_resolve`/`p_action_complete` to drop their local store plumbing (services handle it).

- [ ] **Step 5: Run suite**

Run: `uv run pytest tests/unit -q`
Expected: PASS (update `test_lifecycle.py` envelope assertions to include the new `verb` key if they compare exact dicts)

- [ ] **Step 6: Commit**

```bash
git add src/chrono_core/services.py src/chrono_core/cli.py tests/unit/test_services_lifecycle.py tests/unit/test_lifecycle.py
git commit -m "feat: shared service layer with CLI cancel/edit/reopen/supersede verbs"
```

---

### Task 6: MCP tools for lifecycle + cached stores

**Files:**
- Modify: `src/chrono_core/mcp_server.py`
- Test: `tests/unit/test_mcp_server.py` (extend)

**Interfaces:**
- Consumes: `services.cancel_action` etc. from Task 5.
- Produces: MCP tools `chrono_core_cancel_action(action_id, reason?, db_path?)`, `chrono_core_edit_action(action_id, text, db_path?)`, `chrono_core_reopen_action`, `chrono_core_supersede_action`, `chrono_core_cancel_blocker`, `chrono_core_edit_blocker`, `chrono_core_reopen_blocker`. All handlers route through `services.open_store` so connections are cached, and `services.close_stores()` is called on shutdown.

- [ ] **Step 1: Extend MCP tests**

Append to `tests/unit/test_mcp_server.py`:

```python
def test_cancel_action_via_handle(monkeypatch, tmp_path):
    from chrono_core import services
    from chrono_core.mcp_server import handle_cancel_action

    db = str(tmp_path / "m.db")
    store = services.open_store(db)
    pid = store.upsert_project(project_id="p", name="p", path="/tmp/p", relative_path="p")
    store.record_next_actions(pid, None, ["x"])
    aid = store._connect().execute("SELECT id FROM next_actions").fetchone()["id"]

    result = handle_cancel_action(aid, db_path=db)
    assert result["ok"] is True and result["status"] == "cancelled"


def test_registered_tools_include_lifecycle():
    from chrono_core.mcp_server import mcp

    registered = asyncio.run(mcp.list_tools())
    names = {t.name for t in registered}
    assert {
        "chrono_core_cancel_action",
        "chrono_core_edit_action",
        "chrono_core_reopen_action",
        "chrono_core_supersede_action",
        "chrono_core_cancel_blocker",
        "chrono_core_edit_blocker",
        "chrono_core_reopen_blocker",
    } <= names
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/unit/test_mcp_server.py -q`
Expected: FAIL — `ImportError: cannot import name 'handle_cancel_action'`

- [ ] **Step 3: Implement**

In `mcp_server.py`: replace every `Store(db_path or DEFAULT_DB_PATH); store.init_schema()` pair with `services.open_store(db_path)`. Delete `DEFAULT_DB_PATH`. Replace `handle_resolve_blocker`/`handle_complete_action` bodies with `services.resolve_blocker(db_path, blocker_id)` / `services.complete_action(db_path, action_id)`. Add handlers + tools:

```python
def handle_cancel_action(
    action_id: str, *, reason: str | None = None, db_path: str | None = None
) -> dict[str, Any]:
    """Close a stale or wrong next action without pretending it was done."""
    return services.cancel_action(db_path, action_id, reason)


@mcp.tool(name="chrono_core_cancel_action")
def cancel_action_tool(
    action_id: str, reason: str | None = None, db_path: str | None = None
) -> dict[str, Any]:
    """Cancel a next action so resume stops surfacing it as open work."""
    return handle_cancel_action(action_id, reason=reason, db_path=db_path)
```

Repeat the identical pattern for `handle_edit_action(action_id, text, db_path)` → tool `chrono_core_edit_action`, `handle_reopen_action`, `handle_supersede_action` (docstrings: edit rewrites truthfully keeping history; supersede links replacement), and the three blocker mirrors. In `main()` wrap the run:

```python
def main() -> int:
    """Run the Chrono Core MCP server over stdio."""
    try:
        mcp.run(transport="stdio")
    finally:
        services.close_stores()
    return 0
```

- [ ] **Step 4: Run suite + lint**

Run: `uv run pytest tests/unit -q && uv run ruff check src tests`
Expected: PASS, no lint errors

- [ ] **Step 5: Commit**

```bash
git add src/chrono_core/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "feat: MCP lifecycle tools routed through shared services with cached stores"
```

---

### Task 7: Bug store layer

**Files:**
- Modify: `src/chrono_core/store/store.py`
- Test: `tests/unit/test_bug_store.py` (create)

**Interfaces:**
- Consumes: v3 `bugs`/`bug_fts` from Task 3; `BUG_SEVERITIES`, `BUG_STATUSES` from Task 4.
- Produces:
  - `Store.report_bug(project_id: str | None, title: str, *, detail: str = "", severity: str = "medium", found_in_session_id: str | None = None) -> str` (returns bug id; raises `ValueError` on bad severity)
  - `Store.list_bugs(*, status: str | None = "open", severity: str | None = None, project_id: str | None = None, include_workspace_wide: bool = True) -> list[dict]` (joins project names; NULL project rows report `project_name: "(workspace)"`)
  - `Store.get_bug(bug_id: str) -> dict | None`
  - `Store.update_bug(bug_id: str, *, status: str | None = None, severity: str | None = None, detail: str | None = None, fixed_in_session_id: str | None = None) -> dict` (same envelope convention as Task 4; validates against `BUG_STATUSES`/`BUG_SEVERITIES`; sets `resolved_at` when entering `fixed`/`wont_fix`/`cancelled`, clears it on reopen to `open`/`confirmed`/`in_progress`)
  - `Store.search_bugs(query: str, *, limit: int = 20) -> list[dict]`

- [ ] **Step 1: Write failing tests**

```python
import pytest

from chrono_core.store.store import Store


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "b.db")
    s.init_schema()
    pid = s.upsert_project(project_id="p", name="proj", path="/tmp/p", relative_path="p")
    return s, pid


def test_report_get_list_roundtrip(store):
    s, pid = store
    bid = s.report_bug(pid, "Resume shows unrelated actions", detail="flat query", severity="high")
    assert bid.startswith("bug_")
    bug = s.get_bug(bid)
    assert bug["title"] == "Resume shows unrelated actions"
    assert bug["severity"] == "high"
    assert bug["project_name"] == "proj"
    open_bugs = s.list_bugs()
    assert [b["id"] for b in open_bugs] == [bid]
    fixed = s.update_bug(bid, status="fixed")
    assert fixed["ok"] is True and fixed["bug"]["status"] == "fixed"
    assert s.get_bug(bid)["resolved_at"]
    assert s.list_bugs(status="open") == []


def test_workspace_wide_bug_has_null_project(store):
    s, _ = store
    bid = s.report_bug(None, "cross-project issue")
    assert s.get_bug(bid)["project_name"] == "(workspace)"
    assert len(s.list_bugs()) == 1
    only_project = s.list_bugs(project_id="p")
    assert only_project == []


def test_severity_validation(store):
    s, pid = store
    with pytest.raises(ValueError, match="severity"):
        s.report_bug(pid, "bad", severity="catastrophic")


def test_search_bugs_matches_title(store):
    s, pid = store
    bid = s.report_bug(pid, "FTS syntax crash")
    hits = s.search_bugs("syntax")
    assert [h["id"] for h in hits] == [bid]
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/unit/test_bug_store.py -q`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'report_bug'`

- [ ] **Step 3: Implement bug methods in `store.py`**

```python
    def report_bug(
        self,
        project_id: str | None,
        title: str,
        *,
        detail: str = "",
        severity: str = "medium",
        found_in_session_id: str | None = None,
    ) -> str:
        from chrono_core.domain.models import BUG_SEVERITIES

        if severity not in BUG_SEVERITIES:
            raise ValueError(
                f"invalid severity '{severity}'; expected one of {BUG_SEVERITIES}"
            )
        conn = self._connect()
        now = utc_now()
        bug_id = make_entity_id("bug")
        conn.execute(
            """
            INSERT INTO bugs (
                id, project_id, title, detail, severity, status,
                found_in_session_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (bug_id, project_id, title, detail, severity, found_in_session_id, now, now),
        )
        self._commit()
        return bug_id

    def list_bugs(
        self,
        *,
        status: str | None = "open",
        severity: str | None = None,
        project_id: str | None = None,
        include_workspace_wide: bool = True,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT b.*, COALESCE(p.name, '(workspace)') AS project_name
            FROM bugs b LEFT JOIN projects p ON p.id = b.project_id
            WHERE 1=1
        """
        params: list[Any] = []
        if status is not None:
            sql += " AND b.status = ?"
            params.append(status)
        if severity is not None:
            sql += " AND b.severity = ?"
            params.append(severity)
        if project_id is not None:
            sql += " AND b.project_id = ?"
            params.append(project_id)
        elif not include_workspace_wide:
            sql += " AND b.project_id IS NOT NULL"
        sql += " ORDER BY b.created_at DESC"
        return [dict(r) for r in self._connect().execute(sql, params).fetchall()]

    def get_bug(self, bug_id: str) -> dict[str, Any] | None:
        row = self._connect().execute(
            """
            SELECT b.*, COALESCE(p.name, '(workspace)') AS project_name
            FROM bugs b LEFT JOIN projects p ON p.id = b.project_id
            WHERE b.id = ?
            """,
            (bug_id,),
        ).fetchone()
        return dict(row) if row else None

    def update_bug(
        self,
        bug_id: str,
        *,
        status: str | None = None,
        severity: str | None = None,
        detail: str | None = None,
        fixed_in_session_id: str | None = None,
    ) -> dict[str, Any]:
        from chrono_core.domain.models import BUG_SEVERITIES, BUG_STATUSES

        if status is not None and status not in BUG_STATUSES:
            raise ValueError(f"invalid status '{status}'; expected one of {BUG_STATUSES}")
        if severity is not None and severity not in BUG_SEVERITIES:
            raise ValueError(f"invalid severity '{severity}'")
        current = self.get_bug(bug_id)
        if current is None:
            return {"ok": False, "bug_id": bug_id, "status": "not_found"}
        closed = {"fixed", "wont_fix", "cancelled"}
        resolved_at = current["resolved_at"]
        if status is not None:
            resolved_at = utc_now() if status in closed else None
        self._connect().execute(
            """
            UPDATE bugs SET
                status = COALESCE(?, status),
                severity = COALESCE(?, severity),
                detail = COALESCE(?, detail),
                fixed_in_session_id = COALESCE(?, fixed_in_session_id),
                resolved_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, severity, detail, fixed_in_session_id, resolved_at, utc_now(), bug_id),
        )
        self._commit()
        return {"ok": True, "already": False, "bug_id": bug_id, "bug": self.get_bug(bug_id)}

    def search_bugs(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._connect().execute(
            """
            SELECT b.* FROM bug_fts f JOIN bugs b ON b.rowid = f.rowid
            WHERE bug_fts MATCH ? ORDER BY rank LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_bug_store.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/chrono_core/store/store.py tests/unit/test_bug_store.py
git commit -m "feat: bug store layer with workspace-wide scoping, validation, and FTS search"
```

---

### Task 8: Bug CLI verbs + services wiring

**Files:**
- Modify: `src/chrono_core/services.py`
- Modify: `src/chrono_core/cli.py`
- Test: `tests/unit/test_bug_cli.py` (create)

**Interfaces:**
- Consumes: Store bug methods (Task 7); `resolve_project_id_from` (Task 5).
- Produces: services `report_bug/list_bugs/update_bug/get_bug/search_bugs_or_observations` wrappers; CLI `chrono bug report|list|show|update`.

- [ ] **Step 1: Write failing CLI test**

```python
import json
from pathlib import Path

from chrono_core.cli import main


def test_report_list_update_flow(tmp_path: Path, capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "README.md").write_text("# marker\n")
    db = str(tmp_path / "db.sqlite")
    base = ["--cwd", str(proj), "--workspace-root", str(tmp_path), "--db-path", db]

    rc = main(["bug", "report", "Broken export", *base,
               "--severity", "high", "--detail", "nested dup"])
    assert rc == 0
    reported = json.loads(capsys.readouterr().out)
    bid = reported["bug"]["id"]
    assert reported["project_id"] == "proj-" + reported["project_id"].split("-")[-1]

    rc = main(["bug", "list", *base, "--json"])
    listed = json.loads(capsys.readouterr().out)
    assert listed["count"] == 1 and listed["bugs"][0]["id"] == bid

    rc = main(["bug", "update", bid, "--status", "confirmed", *base])
    assert rc == 0
    rc = main(["bug", "update", bid, "--status", "fixed", *base])
    assert rc == 0
    rc = main(["bug", "list", *base, "--status", "open", "--json"])
    assert json.loads(capsys.readouterr().out)["count"] == 0


def test_workspace_wide_flag(tmp_path: Path, capsys):
    db = str(tmp_path / "db.sqlite")
    rc = main(["bug", "report", "infra issue", "--db-path", db, "--workspace",
               "--cwd", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["bug"]["project_id"] is None
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/unit/test_bug_cli.py -q`
Expected: FAIL — invalid choice: 'bug'

- [ ] **Step 3: Services wrappers**

Append to `src/chrono_core/services.py`:

```python
def report_bug(
    db_path: str | None,
    cwd: str,
    *,
    title: str,
    severity: str = "medium",
    detail: str = "",
    workspace_wide: bool = False,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    from chrono_core.config import default_workspace_root
    from chrono_core.workspace.resolver import resolve_project

    store = open_store(db_path)
    project_id: str | None = None
    if not workspace_wide:
        project = resolve_project(
            Path(cwd), workspace_root=Path(workspace_root or default_workspace_root())
        )
        project_id = store.get_or_create_project(project)
    bug_id = store.report_bug(project_id, title, detail=detail, severity=severity)
    return {
        "ok": True,
        "bug_id": bug_id,
        "project_id": project_id,
        "bug": store.get_bug(bug_id),
    }


def list_bugs(
    db_path: str | None,
    *,
    status: str | None = "open",
    severity: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    bugs = open_store(db_path).list_bugs(
        status=status, severity=severity, project_id=project_id
    )
    return {"ok": True, "count": len(bugs), "bugs": bugs}


def update_bug(db_path: str | None, bug_id: str, **fields: Any) -> dict[str, Any]:
    try:
        return open_store(db_path).update_bug(bug_id, **fields)
    except ValueError as exc:
        return {"ok": False, "bug_id": bug_id, "error": str(exc)}
```

Note the resolver+`get_or_create_project` pattern above is the canonical way services bind a cwd to a stored project id — Task 9's MCP handler inherits it via this wrapper.

- [ ] **Step 4: CLI parser + dispatch**

In `build_parser()`:

```python
    p_bug = sub.add_parser("bug", help="track bugs across projects")
    bug_sub = p_bug.add_subparsers(dest="bug_command")

    p_bug_report = bug_sub.add_parser("report", help="file a bug for the project at --cwd")
    p_bug_report.add_argument("title")
    p_bug_report.add_argument("--detail", default="")
    p_bug_report.add_argument(
        "--severity", choices=["low", "medium", "high", "critical"], default="medium"
    )
    p_bug_report.add_argument(
        "--workspace", action="store_true", help="file as workspace-wide (no project)"
    )
    p_bug_report.add_argument("--cwd", default=".")
    p_bug_report.add_argument("--workspace-root", default=default_workspace_root())
    p_bug_report.add_argument("--db-path", "--db", default=DEFAULT_DB_PATH)

    p_bug_list = bug_sub.add_parser("list", help="list bugs across projects")
    p_bug_list.add_argument("--status", default="open")
    p_bug_list.add_argument("--severity", default=None)
    p_bug_list.add_argument("--project-id", default=None)
    p_bug_list.add_argument("--json", action="store_true")
    p_bug_list.add_argument("--db-path", "--db", default=DEFAULT_DB_PATH)

    p_bug_show = bug_sub.add_parser("show", help="show one bug")
    p_bug_show.add_argument("bug_id")
    p_bug_show.add_argument("--db-path", "--db", default=DEFAULT_DB_PATH)

    p_bug_update = bug_sub.add_parser("update", help="change bug status/severity/detail")
    p_bug_update.add_argument("bug_id")
    p_bug_update.add_argument(
        "--status", choices=["open", "confirmed", "in_progress", "fixed", "wont_fix", "cancelled"]
    )
    p_bug_update.add_argument(
        "--severity", choices=["low", "medium", "high", "critical"]
    )
    p_bug_update.add_argument("--detail")
    p_bug_update.add_argument("--db-path", "--db", default=DEFAULT_DB_PATH)
```

Dispatch in `main()`:

```python
    if args.command == "bug":
        if args.bug_command == "report":
            result = services.report_bug(
                args.db_path, args.cwd,
                title=args.title, severity=args.severity, detail=args.detail,
                workspace_wide=args.workspace, workspace_root=args.workspace_root,
            )
        elif args.bug_command == "list":
            result = services.list_bugs(
                args.db_path, status=args.status, severity=args.severity,
                project_id=args.project_id,
            )
            if not args.json:
                for b in result["bugs"]:
                    print(f"[{b['id']}] ({b['severity']}/{b['status']}) "
                          f"{b['project_name']}: {b['title']}")
                return 0
        elif args.bug_command == "show":
            bug = open_store(args.db_path).get_bug(args.bug_id)
            result = {"ok": bug is not None, "bug": bug}
        elif args.bug_command == "update":
            result = services.update_bug(
                args.db_path, args.bug_id,
                status=args.status, severity=args.severity, detail=args.detail,
            )
        else:
            parser.error("bug requires a subcommand")
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
```

(`open_store` imported from services.)

- [ ] **Step 5: Run suite**

Run: `uv run pytest tests/unit -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/chrono_core/services.py src/chrono_core/cli.py tests/unit/test_bug_cli.py
git commit -m "feat: chrono bug report/list/show/update across projects"
```

---

### Task 9: Bug MCP tools + dogfood bug #1

**Files:**
- Modify: `src/chrono_core/mcp_server.py`
- Test: `tests/unit/test_mcp_server.py` (extend)

**Interfaces:**
- Produces: MCP tools `chrono_core_report_bug(cwd, title, severity?, detail?, workspace?, ...)`, `chrono_core_list_bugs(status?, severity?, project_id?)`, `chrono_core_update_bug(bug_id, status?, severity?, detail?)`.

- [ ] **Step 1: Add failing registration test**

```python
def test_registered_tools_include_bugs():
    from chrono_core.mcp_server import mcp

    registered = asyncio.run(mcp.list_tools())
    names = {t.name for t in registered}
    assert {
        "chrono_core_report_bug",
        "chrono_core_list_bugs",
        "chrono_core_update_bug",
    } <= names
```

- [ ] **Step 2: Implement handlers/tools**

Same pattern as Task 6, delegating to `services.report_bug/list_bugs/update_bug` with explicit kwargs. Example:

```python
@mcp.tool(name="chrono_core_report_bug")
def report_bug_tool(
    cwd: str,
    title: str,
    severity: str = "medium",
    detail: str = "",
    workspace: bool = False,
    workspace_root: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """File a bug against the project at cwd, or workspace-wide."""
    return services.report_bug(
        db_path, cwd, title=title, severity=severity, detail=detail,
        workspace_wide=workspace, workspace_root=workspace_root,
    )
```

- [ ] **Step 3: Run suite**

Run: `uv run pytest tests/unit -q && uv run ruff check src tests`
Expected: PASS

- [ ] **Step 4: Dogfood bug #1 against the live default DB**

Run:
```bash
chrono bug report "Resume surfaces unrelated workstream actions project-globally" \
  --severity high \
  --detail "Pre-fix resume selected all open actions flat; fixed by branch-scoped queries in Task 1-2; regression tests test_resume_scoping.py" \
  --status confirmed \
  --cwd ~/workspace/cores/chrono-core
chrono bug update <printed_bug_id> --status confirmed
```
Expected: bug recorded for project chrono-core; `chrono bug list` shows it.

- [ ] **Step 5: Commit**

```bash
git add src/chrono_core/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "feat: bug tracking MCP tools; dogfood bug #1 for the resume-surfacing defect"
```

---

### Task 10: Portability — remove machine-specific paths

**Files:**
- Modify: `src/chrono_core/config.py`
- Modify: `src/chrono_core/integrations/gearcore.py`
- Move: `src/chrono_core/migrations.py` → `scripts/migrate_legacy_db.py` (adjust its imports to package-relative; keep behavior)
- Modify: `tests/unit/test_config_env.py`, `tests/unit/test_mcp_server.py` (lines pinning personal paths)

**Interfaces:**
- Produces: `default_workspace_root()` returns `CHRONO_WORKSPACE_ROOT` or `CONTINUITY_WORKSPACE_ROOT` env, else falls back to the nearest ancestor of cwd containing multiple project-marker dirs, else cwd. `default_db_path()` honors `CHRONO_DB_PATH` at call time before `~/.local/share/chrono-core/chrono.db`.

- [ ] **Step 1: Rewrite failing config tests**

Update `tests/unit/test_config_env.py`:

```python
def test_env_overrides_win(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONO_WORKSPACE_ROOT", str(tmp_path))
    assert default_workspace_root() == str(tmp_path)


def test_legacy_var_still_accepted(monkeypatch, tmp_path):
    monkeypatch.delenv("CHRONO_WORKSPACE_ROOT", raising=False)
    monkeypatch.setenv("CONTINUITY_WORKSPACE_ROOT", str(tmp_path))
    assert default_workspace_root() == str(tmp_path)


def test_no_personal_fallback(monkeypatch, tmp_path, monkeypatch_cwd):
    monkeypatch.delenv("CHRONO_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("CONTINUITY_WORKSPACE_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert "~" not in default_workspace_root()


def test_db_path_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONO_DB_PATH", str(tmp_path / "x.db"))
    assert default_db_path() == str(tmp_path / "x.db")


def test_db_path_default_under_home(monkeypatch):
    monkeypatch.delenv("CHRONO_DB_PATH", raising=False)
    assert default_db_path().endswith(".local/share/chrono-core/chrono.db")
```

- [ ] **Step 2: Implement config changes**

```python
def default_workspace_root() -> str:
    """Workspace root: env override, else cwd (no machine-specific fallback)."""
    return (
        os.environ.get("CHRONO_WORKSPACE_ROOT")
        or os.environ.get("CONTINUITY_WORKSPACE_ROOT")
        or os.getcwd()
    )


def default_db_path() -> str:
    """Continuity DB: CHRONO_DB_PATH override, else canonical home location."""
    override = os.environ.get("CHRONO_DB_PATH")
    if override:
        return override
    return str(Path.home() / ".local" / "share" / "chrono-core" / "chrono.db")
```

Delete `FALLBACK_WORKSPACE_ROOT`. In `cli.py`/`mcp_server.py`, ensure `default_db_path()` is invoked inside functions, never at module import (Task 5/6 already removed `DEFAULT_DB_PATH`; make parser defaults `default=None` and let services resolve at call time — change remaining `default=DEFAULT_DB_PATH` occurrences to `default=None`).

- [ ] **Step 3: GearCore skill path**

In `integrations/gearcore.py` replace the module constant with a function argument defaulting to None and resolved lazily; when absent, omit skill-copy commands from the plan output rather than guessing `parents[3]`.

- [ ] **Step 4: Move ops script**

```bash
mkdir -p scripts && git mv src/chrono_core/migrations.py scripts/migrate_legacy_db.py
```

Fix its imports (`from chrono_core.…`) and add a module docstring noting it is a one-off ops script. Update `tests/unit/test_identity_migration.py` to import from `scripts.migrate_legacy_db` via `sys.path` insertion or move the test alongside under `scripts/` invocation with subprocess.

- [ ] **Step 5: Run suite + grep for leftovers**

Run: `uv run pytest tests/unit -q && grep -rn "user\|FALLBACK_WORKSPACE" src/ || true`
Expected: PASS; grep finds no hits under `src/`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: portable configuration; legacy ops script moved to scripts/"
```

---

### Task 11: Robustness fixes

**Files:**
- Modify: `src/chrono_core/store/store.py` (FTS error wrapping)
- Modify: `src/chrono_core/capture/git.py` (timeouts)
- Modify: `src/chrono_core/capture/handoff.py` (JSON errors)
- Modify: `src/chrono_core/export/markdown.py` (escaping)
- Modify: `src/chrono_core/mcp_server.py` (`max_tokens` truthiness)
- Test: `tests/unit/test_error_paths.py` (create)

- [ ] **Step 1: Write failing tests**

```python
import json

import pytest

from chrono_core.capture.handoff import build_handoff_payload
from chrono_core.export.markdown import _render_escape
from chrono_core.services import search_observations_safe


def test_bad_fts_query_is_structured_error(tmp_path):
    result = search_observations_safe(str(tmp_path / "d.db"), '"unbalanced')
    assert result["ok"] is False
    assert "error" in result


def test_handoff_missing_json_file_message(tmp_path, capsys):
    with pytest.raises(SystemExit):
        build_handoff_payload(json_path=str(tmp_path / "nope.json"))


def test_markdown_escapes_structure_chars():
    assert _render_escape("# not a heading](link") .startswith("\\#")


def test_zero_max_tokens_is_honored():
    from chrono_core.mcp_server import _fit_to_token_budget

    result = _fit_to_token_budget(
        {"summary": "s" * 500, "next_actions": [{"a": 1}] * 50}, 10
    )
    assert result["truncated"] is True
```

- [ ] **Step 2: Implement**

1. New services wrapper:

```python
def search_observations_safe(
    db_path: str | None, query: str, *, project_id: str | None = None, limit: int = 20
) -> dict[str, Any]:
    import sqlite3

    try:
        results = open_store(db_path).search_observations(
            query, project_id=project_id, limit=max(limit, 0)
        )
    except sqlite3.OperationalError as exc:
        return {"ok": False, "query": query, "error": f"invalid query: {exc}", "results": []}
    return {"ok": True, "query": query, "count": len(results), "results": results}
```

Route CLI `search` and MCP `handle_search_observations` through it.

2. `handoff.build_handoff_payload(json_path)`: wrap file-open/parse failures in `parser.error`-style exit — accept an optional `on_error` callback or raise `SystemExit` via `argparse` at CLI layer; catch `OSError`/`json.JSONDecodeError` and re-raise as `ValueError("unreadable --json payload: ...")`, caught in CLI dispatch printing a clean message and returning 2.

3. `git.py`: add `timeout=10` to each `subprocess.run`.

4. `markdown.py`: add

```python
def _render_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("#", "\\#").replace("[", "\\[").replace("]", "\\]")
```

and apply to user-derived strings before rendering headings/lists/links.

5. `mcp_server.handle_get_resume_context`: change `if max_tokens:` to `if max_tokens is not None:`.

- [ ] **Step 3: Run suite + lint**

Run: `uv run pytest tests/unit -q && uv run ruff check src tests`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "fix: structured FTS errors, clean handoff JSON errors, git timeouts, markdown escaping"
```

---

### Task 12: Packaging metadata

**Files:**
- Modify: `pyproject.toml`
- Create: `LICENSE` (MIT)
- Modify: `src/chrono_core/__init__.py` (version source of truth)
- Modify: `tests/dev-deps` concern: add `anyio` to dev extra

- [ ] **Step 1: Update pyproject.toml**

```toml
[project]
name = "chrono-core"
dynamic = ["version"]
description = "Local-first project memory for humans and AI agents: session handoffs, resume context, and cross-project continuity over SQLite."
readme = "README.md"
license = "MIT"
requires-python = ">=3.12"
dependencies = ["mcp>=1.0,<2"]
authors = [{ name = "Chrono Core Maintainers" }]
keywords = ["mcp", "agent-memory", "session-handoff", "continuity", "sqlite", "fts5", "cli"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.12",
    "Topic :: Software Development :: Version Control",
]

[project.urls]
Homepage = "https://github.com/YOUR_ORG/chrono-core"
Repository = "https://github.com/YOUR_ORG/chrono-core"
Issues = "https://github.com/YOUR_ORG/chrono-core/issues"

[project.scripts]
chrono = "chrono_core.cli:main"
chrono-mcp = "chrono_core.mcp_server:main"

[tool.hatch.version]
path = "src/chrono_core/__init__.py"
```

Remove the hardcoded `version = "..."` line and the transitional `continuity` alias scripts (documented decision: pre-publication cleanup). Keep `[project.optional-dependencies]` dev group and add `"anyio>=4"`.

- [ ] **Step 2: Write LICENSE**

Standard MIT text, copyright `2026 Chrono Core Maintainers`.

- [ ] **Step 3: Verify**

Run: `uv sync && uv run python -c "import chrono_core; print(chrono_core.__version__)" && uv run pytest tests/unit -q && uv run chrono --version`
Expected: version resolves from `__init__.py`, suite passes, `chrono-core 0.1.0` prints.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml LICENSE src/chrono_core/__init__.py uv.lock
git commit -m "chore: PyPI-ready packaging metadata, MIT license, dynamic version"
```

---

### Task 13: Distill/review fold in open high-severity bugs

**Files:**
- Modify: `src/chrono_core/management/distill.py`
- Modify: `src/chrono_core/management/review.py`
- Test: extend `tests/unit/test_distill.py`, `tests/unit/test_management_review.py`

- [ ] **Step 1: Failing test**

```python
def test_high_severity_open_bugs_lower_health(store_with_project):
    store, pid = store_with_project
    store.report_bug(pid, "critical flaw", severity="critical")
    result = distill_project(cwd="/tmp/p", workspace_root="/tmp", store=store)
    health = result["health"]
    assert health["score"] < 70
    assert any("bug" in str(advice).lower() for advice in result.get("advice", []))
```

(Reuse the existing fixtures in those test files; adapt names to what exists.)

- [ ] **Step 2: Implement**

In `distill.py`, after existing counts, fetch `store.list_bugs(status="open")` filtered to the project and subtract `min(15, 5 * count_of_open_high_or_critical)` from the health score; emit an advice line `"N open high-severity bug(s) need triage"`. Mirror the count into `review.py`'s health section using the same helper (extract `bug_pressure(store, project_id) -> int` into `management/distill.py` and import it in `review.py`).

- [ ] **Step 3: Run + commit**

Run: `uv run pytest tests/unit -q`
Commit: `git commit -am "feat: open high-severity bugs reduce distilled health and feed advice"`

---

### Task 14: Beautified README.md

**Files:**
- Modify: `README.md` (full rewrite preserving accurate claims)

- [ ] **Step 1: Rewrite README**

Structure (keep every claim truthful — deterministic heuristics, no AI reconciliation):

1. Title + one-line tagline + centered badges (static shields: python version, license MIT, code style ruff — no CI badges yet)
2. "Why" paragraph (loss of continuity problem, from PROJECT_BRIEF.md)
3. Quick start: `uv tool install chrono-core` (note: pending publication; show `uv pip install -e .` alternative), `chrono handoff`, `chrono resume`, sample terminal output block showing branch-scoped footer
4. Feature table: handoff capture, branch-scoped resume, lifecycle (cancel/edit/reopen/supersede), cross-project bugs, FTS search, markdown export, MCP server (17 tools listed), GearCore adapter
5. Architecture snippet (ASCII diagram from spec §Architecture)
6. Docs links table (existing docs/)
7. Roadmap: Phase 4 cross-project intelligence + future GitHub bug dump/sync
8. License section

Use fenced code blocks with realistic output captured from actual runs (`chrono resume --cwd …`), not invented transcripts.

- [ ] **Step 2: Verify links and commit**

Run: link check by eye + `uv run pytest tests/unit/test_chrono_identity.py -q`
Commit: `git commit -am "docs: beautified README with quick start, feature table, and architecture"`

---

### Task 15: Local SEO landing page HTML

**Files:**
- Create: `docs/site/index.html`

- [ ] **Step 1: Build the page**

Single self-contained HTML file (inline CSS, no external deps except fonts):

- `<title>`: "Chrono Core — Project Memory & Session Handoff for AI Agents (MCP, SQLite)"
- Meta description (~155 chars): "Chrono Core gives humans and AI agents local-first project memory: structured session handoffs, branch-scoped resume context, cross-project bug tracking over SQLite."
- Keywords meta: mcp server, agent memory, project continuity, session handoff, ai coding agents, sqlite fts5, developer tools
- Open Graph tags (og:title, og:description, og:type=website)
- Semantic HTML5: header/nav/main/section/footer; h1 exactly once; sections: What, Why, Features (dl list), How it works (the ASCII diagram), Quick start (pre/code), FAQ (3 entries: Is it AI-based? No—deterministic heuristics. Does it need the cloud? No—SQLite local-first. Which agents? Anything speaking MCP.)
- JSON-LD `SoftwareApplication` schema block with name, applicationCategory DeveloperApplication, operatingSystem "Cross-platform", offers price 0
- Footer: "Not yet published — local preview artifact." + license MIT

Validate: `python -c "from html.parser import HTMLParser; HTMLParser().feed(open('docs/site/index.html').read()); print('parses')"`.

- [ ] **Step 2: Commit**

```bash
git add docs/site/index.html
git commit -m "docs: standalone SEO landing page (local preview, unpublished)"
```

---

## Final verification (after all tasks)

1. `uv run pytest -q` — whole suite green
2. `uv run ruff check src tests` — clean
3. `chrono resume --cwd ~/workspace/InternalProject` — only current-branch items + hidden-count footer
4. `chrono bug list --status open --db ~/.local/share/chrono-core/chrono.db` — shows dogfooded bug #1
5. `chrono action cancel act_<some-stale-id> --reason "superseded by corrective handoff"` — works against live DB
6. Write a closing `chrono handoff` summarizing the slice set, files changed, and verification evidence
