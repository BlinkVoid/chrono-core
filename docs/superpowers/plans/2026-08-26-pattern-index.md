# Pattern Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Phase 4 reusable pattern index per `docs/superpowers/specs/2026-08-26-pattern-index-design.md`: MetaFactory ingestion, deterministic candidate mining, and FTS-based pattern recommendations in resume context.

**Architecture:** Schema v4 adds a `patterns` table plus `pattern_fts` (mirroring the bugs/observations FTS setup). Three focused units sit on top: `integrations/metafactory.py` (parse + idempotent ingest), `management/patterns.py` (deterministic keyword mining), and recommendation scoring inside `Store.get_resume_context` using a shared tokenizer in `chrono_core/textutil.py`.

**Tech Stack:** Python ≥ 3.12, stdlib `sqlite3` FTS5, pytest, ruff. Run tests with `uv run --extra dev pytest`; lint with `uv run --extra dev ruff check .`.

## Global Constraints

- Work in an isolated worktree created per `superpowers:using-git-worktrees` (`.worktrees/<name>`, branch `feat/pattern-index`).
- Python ≥ 3.12; no new runtime dependencies (stdlib only).
- ruff line-length 100; select E,F,I,UP,B — `uv run --extra dev ruff check .` must pass every task.
- Repo style: docstrings allowed, type hints on public functions, `from __future__ import annotations` at top of new modules.
- All timestamps via `chrono_core.store.store.utc_now()`; entity ids via `make_entity_id("pat")`.
- Never regress a pattern's `promoted`/`retired` status during upserts.
- Recommendations must never fail a resume (FTS errors → empty list).
- Spec is the authority: `docs/superpowers/specs/2026-08-26-pattern-index-design.md`.

---

### Task 1: Schema v4 — patterns table + pattern_fts

**Files:**
- Modify: `src/chrono_core/store/schema.py`
- Modify: `src/chrono_core/store/migrations.py`
- Test: `tests/unit/test_pattern_store.py` (create)

**Interfaces:**
- Produces: `SCHEMA_VERSION = 4`; tables `patterns`, `pattern_fts` usable by all later tasks.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_pattern_store.py`:

```python
from __future__ import annotations

from pathlib import Path

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/unit/test_pattern_store.py -v`
Expected: FAIL — `no such table: patterns`.

- [ ] **Step 3: Implement schema v4**

In `src/chrono_core/store/schema.py`: change `SCHEMA_VERSION = 3` to `SCHEMA_VERSION = 4`, and append before the closing quote of `DDL` (after the `bugs`-related objects, before `schema_migrations`):

```sql
CREATE TABLE IF NOT EXISTS patterns (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL UNIQUE,
    statement TEXT NOT NULL DEFAULT '',
    category TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    source TEXT NOT NULL DEFAULT 'authored',
    source_ref TEXT,
    projects_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS pattern_fts USING fts5(
    title, statement, content='patterns', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS patterns_fts_insert
AFTER INSERT ON patterns BEGIN
    INSERT INTO pattern_fts (rowid, title, statement) VALUES (new.rowid, new.title, new.statement);
END;

CREATE TRIGGER IF NOT EXISTS patterns_fts_delete
AFTER DELETE ON patterns BEGIN
    INSERT INTO pattern_fts (pattern_fts, rowid, title, statement)
    VALUES ('delete', old.rowid, old.title, old.statement);
END;

CREATE TRIGGER IF NOT EXISTS patterns_fts_update
AFTER UPDATE ON patterns BEGIN
    INSERT INTO pattern_fts (pattern_fts, rowid, title, statement)
    VALUES ('delete', old.rowid, old.title, old.statement);
    INSERT INTO pattern_fts (rowid, title, statement) VALUES (new.rowid, new.title, new.statement);
END;
```

In `src/chrono_core/store/migrations.py`: extend `MIGRATIONS` with `(4, "patterns table + FTS")`, add:

```python
_V4_PATTERNS = [
    """
    CREATE TABLE IF NOT EXISTS patterns (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL UNIQUE,
        statement TEXT NOT NULL DEFAULT '',
        category TEXT,
        status TEXT NOT NULL DEFAULT 'candidate',
        source TEXT NOT NULL DEFAULT 'authored',
        source_ref TEXT,
        projects_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS pattern_fts USING fts5(
        title, statement, content='patterns', content_rowid='rowid'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS patterns_fts_insert
    AFTER INSERT ON patterns BEGIN
        INSERT INTO pattern_fts (rowid, title, statement)
        VALUES (new.rowid, new.title, new.statement);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS patterns_fts_delete
    AFTER DELETE ON patterns BEGIN
        INSERT INTO pattern_fts (pattern_fts, rowid, title, statement)
        VALUES ('delete', old.rowid, old.title, old.statement);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS patterns_fts_update
    AFTER UPDATE ON patterns BEGIN
        INSERT INTO pattern_fts (pattern_fts, rowid, title, statement)
        VALUES ('delete', old.rowid, old.title, old.statement);
        INSERT INTO pattern_fts (rowid, title, statement)
        VALUES (new.rowid, new.title, new.statement);
    END
    """,
]
```

and register `_STATEMENTS[4] = _V4_PATTERNS` alongside the existing `3:` entry.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/unit/test_pattern_store.py tests/unit/test_schema.py tests/unit/test_migration_v3.py -v`
Expected: PASS (new tests green, existing schema/migration suites unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/chrono_core/store/schema.py src/chrono_core/store/migrations.py tests/unit/test_pattern_store.py
git commit -m "feat: schema v4 adds patterns table with FTS index"
```

---

### Task 2: Shared tokenizer (`chrono_core/textutil.py`)

**Files:**
- Create: `src/chrono_core/textutil.py`
- Test: `tests/unit/test_textutil.py` (create)

**Interfaces:**
- Produces:
  - `tokenize(text: str) -> list[str]`
  - `salient_terms(text: str, limit: int = 12) -> list[str]`
  - `term_project_counts(documents: list[tuple[str, str]]) -> dict[str, dict[str, int]]` — takes `(project_id, text)` pairs, returns `term -> {project_id: total_count}`.
- Consumed by Tasks 3 (recommendations), 5 (mining).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_textutil.py`:

```python
from __future__ import annotations

from chrono_core.textutil import salient_terms, term_project_counts, tokenize


def test_tokenize_lowercases_drops_stopwords_and_short_tokens():
    tokens = tokenize("The Retry Loop retries retries flaky DB calls")
    assert "retries" in tokens
    assert "flaky" in tokens
    assert "the" not in tokens
    assert "db" not in tokens  # too short (min 3 chars)
    assert tokens == [t.lower() for t in tokens]


def test_salient_terms_rank_by_frequency_then_term():
    terms = salient_terms("alpha beta alpha gamma beta alpha", limit=2)
    assert terms == ["alpha", "beta"]


def test_term_project_counts_counts_distinct_projects():
    docs = [
        ("p1", "circuit breaker circuit"),
        ("p2", "circuit breaker"),
        ("p3", "breaker breaker breaker"),
    ]
    counts = term_project_counts(docs)
    assert counts["circuit"] == {"p1": 2, "p2": 1}
    assert counts["breaker"]["p3"] == 3
    assert set(counts["breaker"]) == {"p1", "p2", "p3"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/unit/test_textutil.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chrono_core.textutil'`.

- [ ] **Step 3: Implement**

Create `src/chrono_core/textutil.py`:

```python
"""Shared deterministic text tokenizing used by pattern mining and scoring."""
from __future__ import annotations

import re

# Small curated English stopword list plus Chrono-domain filler words.
STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "into", "when",
        "then", "than", "are", "was", "were", "been", "have", "has", "had",
        "not", "but", "all", "any", "can", "will", "would", "should", "could",
        "our", "their", "its", "each", "which", "who", "whom", "out", "use",
        "used", "using", "new", "one", "two", "also", "may", "might", "per",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens of length >= 3 with stopwords removed."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def salient_terms(text: str, limit: int = 12) -> list[str]:
    """Most frequent tokens, ties broken alphabetically."""
    counts: dict[str, int] = {}
    for token in tokenize(text):
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, _count in ranked[:limit]]


def term_project_counts(documents: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """Per-term totals keyed by project: ``term -> {project_id: count}``."""
    counts: dict[str, dict[str, int]] = {}
    for project_id, text in documents:
        for token in tokenize(text):
            per_project = counts.setdefault(token, {})
            per_project[project_id] = per_project.get(project_id, 0) + 1
    return counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/unit/test_textutil.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/chrono_core/textutil.py tests/unit/test_textutil.py
git commit -m "feat: shared tokenizer utilities for pattern mining/scoring"
```

---

### Task 3: Store pattern operations

**Files:**
- Modify: `src/chrono_core/store/store.py`
- Modify: `src/chrono_core/domain/models.py` (add `recommended_patterns` to `ResumeContext`)
- Test: `tests/unit/test_pattern_store.py` (extend)

**Interfaces:**
- Consumes: Task 1 tables, Task 2 `salient_terms`.
- Produces (used by Tasks 4–7):
  - `Store.upsert_pattern(*, title: str, statement: str = "", category: str | None = None, source: str = "authored", source_ref: str | None = None, projects: list[str] | None = None, status: str = "candidate") -> str`
  - `Store.set_pattern_status(pattern_id: str, status: str) -> dict` — `{"ok": bool, "pattern_id": ..., "status": <final or "not_found">}`; raises `ValueError` on unknown status.
  - `Store.list_patterns(*, status: str | None = None, limit: int | None = None) -> list[dict]`
  - `Store.search_patterns_safe(query: str, *, limit: int = 3, statuses: tuple[str, ...] = ("candidate", "validated")) -> list[dict]`
  - `ResumeContext.recommended_patterns: list[dict[str, Any]]` (included in `to_dict()`).
  - Status rule: `PATTERN_STATUSES = ("candidate", "validated", "promoted", "retired")` exported from `chrono_core.domain.models`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_pattern_store.py`:

```python
import pytest

from chrono_core.domain.models import ResumeContext


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
        __import__("chrono_core.domain.models", fromlist=["HandoffPayload"]).HandoffPayload(
            summary="s"
        ),
        __import__("chrono_core.domain.models", fromlist=["GitState"]).GitState(),
    )
    store.record_decisions(pid, session, [{"title": "retry loop around flaky upstream"}])
    seeded_pattern(store)

    context = store.get_resume_context(pid)

    titles = [p["title"] for p in context.recommended_patterns]
    assert "Single Client Boundary" in titles or titles == []
    assert all(set(p.keys()) == {"id", "title", "category", "status"} for p in context.recommended_patterns)
```

Note: replace the awkward `__import__` lines with normal imports at the top of the file
(`from chrono_core.domain.models import GitState, HandoffPayload`) and use them directly —
the imports belong with the existing ones added in Task 1's test file header.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/unit/test_pattern_store.py -v`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'upsert_pattern'`.

- [ ] **Step 3: Implement**

In `src/chrono_core/domain/models.py`: add to the module-level constants area (near `BUG_SEVERITIES`):

```python
PATTERN_STATUSES = ("candidate", "validated", "promoted", "retired")
```

Add to `ResumeContext` after `hidden_blockers: int = 0`:

```python
    recommended_patterns: list[dict[str, Any]] = field(default_factory=list)
```

and inside `ResumeContext.to_dict()` add `"recommended_patterns": self.recommended_patterns,`
(matching the existing key style in that method).

In `src/chrono_core/store/store.py`: add import `from chrono_core.textutil import salient_terms` and this constant near the top:

```python
_PATTERN_STATUS_RANK = {"candidate": 0, "validated": 1, "promoted": 2}
```

Add these methods to `Store` (after `update_bug`):

```python
    def upsert_pattern(
        self,
        *,
        title: str,
        statement: str = "",
        category: str | None = None,
        source: str = "authored",
        source_ref: str | None = None,
        projects: list[str] | None = None,
        status: str = "candidate",
    ) -> str:
        """Insert or refresh a pattern keyed by its unique title.

        Field values always refresh. The stored status never regresses away
        from promoted/retired, and otherwise only moves forward along
        candidate -> validated -> promoted.
        """
        if status not in _PATTERN_STATUS_RANK:
            raise ValueError(f"invalid pattern status '{status}'")
        conn = self._connect()
        now = utc_now()
        existing = conn.execute(
            "SELECT id, status FROM patterns WHERE title = ?", (title,)
        ).fetchone()
        if existing is None:
            pattern_id = make_entity_id("pat")
            conn.execute(
                """
                INSERT INTO patterns (
                    id, title, statement, category, status, source,
                    source_ref, projects_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pattern_id,
                    title,
                    statement,
                    category,
                    status,
                    source,
                    source_ref,
                    json.dumps(projects or [], ensure_ascii=False),
                    now,
                    now,
                ),
            )
            self._commit()
            return pattern_id

        kept = existing["status"]
        if kept not in ("promoted", "retired"):
            if _PATTERN_STATUS_RANK[status] > _PATTERN_STATUS_RANK[kept]:
                kept = status
        conn.execute(
            """
            UPDATE patterns SET statement = ?, category = ?, source = ?,
                source_ref = ?, projects_json = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                statement,
                category,
                source,
                source_ref,
                json.dumps(projects or [], ensure_ascii=False),
                kept,
                now,
                existing["id"],
            ),
        )
        self._commit()
        return existing["id"]

    def set_pattern_status(self, pattern_id: str, status: str) -> dict[str, Any]:
        from chrono_core.domain.models import PATTERN_STATUSES

        if status not in PATTERN_STATUSES:
            raise ValueError(f"invalid pattern status '{status}'")
        cursor = self._connect().execute(
            "UPDATE patterns SET status = ?, updated_at = ? WHERE id = ?",
            (status, utc_now(), pattern_id),
        )
        self._commit()
        return {
            "ok": cursor.rowcount > 0,
            "pattern_id": pattern_id,
            "status": status if cursor.rowcount > 0 else "not_found",
        }

    def list_patterns(
        self, *, status: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, title, statement, category, status, source,
                   source_ref, projects_json, created_at, updated_at
            FROM patterns
        """
        params: list[Any] = []
        if status is not None:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY title"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._connect().execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def search_patterns_safe(
        self,
        query: str,
        *,
        limit: int = 3,
        statuses: tuple[str, ...] = ("candidate", "validated"),
    ) -> list[dict[str, Any]]:
        """FTS match against patterns; malformed queries return []."""
        try:
            rows = self._connect().execute(
                """
                SELECT p.id, p.title, p.category, p.status
                FROM pattern_fts f JOIN patterns p ON p.rowid = f.rowid
                WHERE pattern_fts MATCH ?
                ORDER BY rank LIMIT ?
                """,
                (query, max(limit * 4, limit)),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        hits = [dict(row) for row in rows if row["status"] in statuses]
        return hits[:limit]
```

Then wire recommendations into `get_resume_context`: just before the `return ResumeContext(...)` at the end of that method, add:

```python
        rec_text = " ".join(
            [d["title"] for d in decisions]
            + [b["title"] for b in blockers]
            + [a["text"] for a in actions]
        )
        rec_terms = salient_terms(rec_text)
        recommended_patterns = (
            self.search_patterns_safe(" OR ".join(rec_terms), limit=3)
            if rec_terms
            else []
        )
```

and add `recommended_patterns=recommended_patterns,` to the `ResumeContext(...)` constructor call.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/unit/test_pattern_store.py tests/unit/test_resume.py tests/unit/test_resume_budget.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chrono_core/store/store.py src/chrono_core/domain/models.py tests/unit/test_pattern_store.py
git commit -m "feat: Store pattern CRUD, safe FTS search, and resume recommendations"
```

---

### Task 4: MetaFactory ingestion adapter

**Files:**
- Create: `src/chrono_core/integrations/metafactory.py`
- Test: `tests/unit/test_metafactory_ingest.py` (create)

**Interfaces:**
- Consumes: `Store.upsert_pattern` (Task 3).
- Produces:
  - `parse_patterns_library(text: str) -> list[dict]` — dicts with keys `title`, `statement`, `category`, `projects`.
  - `find_latest_patterns_file(root: Path) -> Path | None`
  - `ingest_metafactory_patterns(store: Store, *, metafactory_root: str | Path | None = None, file: str | Path | None = None) -> dict` — `{"ok": True, "source_file": str, "ingested": N, "patterns": [{"id", "title", "status"}]}`; raises `ValueError` when nothing resolvable.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_metafactory_ingest.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from chrono_core.integrations.metafactory import (
    find_latest_patterns_file,
    ingest_metafactory_patterns,
    parse_patterns_library,
)

SAMPLE = """# Patterns Library — 2026-08-01_090633

Intro text ignored.

---

## Pattern: Fail-Closed Gating at Trust Boundaries

**Category**: security
**Frequency**: 5 projects (3 codebases)
**Projects**: FigmentLab†, gear-sandbox

**Pattern Statement**:
At any boundary where unsafe input could pass, the default is rejection.

**Implementation Variants**:
- FigmentLab†: validators reject unknown features rather than guessing.

**When to Use**:
Any system processing untrusted input.

---

## Pattern: Single Client Boundary

**Category**: architecture
**Frequency**: 2 projects
**Projects**: ProjectMik, GearCore

**Pattern Statement**:
All external provider calls flow through exactly one client abstraction.
"""


def write_snapshot(root: Path, stamp: str, text: str) -> Path:
    snap = root / "consolidated" / stamp
    snap.mkdir(parents=True)
    path = snap / "patterns_library.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_patterns_library_extracts_blocks():
    patterns = parse_patterns_library(SAMPLE)

    assert [p["title"] for p in patterns] == [
        "Fail-Closed Gating at Trust Boundaries",
        "Single Client Boundary",
    ]
    first = patterns[0]
    assert first["category"] == "security"
    assert first["projects"] == ["FigmentLab", "gear-sandbox"]
    assert first["statement"].startswith("At any boundary")
    assert "validators reject unknown features" in first["statement"]
    assert "Any system processing untrusted input." in first["statement"]


def test_find_latest_picks_newest_snapshot(tmp_path: Path):
    write_snapshot(tmp_path, "2026-07-31_154240", SAMPLE)
    newest = write_snapshot(tmp_path, "2026-08-01_090633", SAMPLE)

    assert find_latest_patterns_file(tmp_path) == newest
    assert find_latest_patterns_file(tmp_path / "missing") is None


def test_ingest_is_idempotent_and_marks_validated(tmp_path: Path):
    from chrono_core.store.store import Store

    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    snapshot = write_snapshot(tmp_path, "2026-08-01_090633", SAMPLE)

    first = ingest_metafactory_patterns(store, metafactory_root=tmp_path)
    second = ingest_metafactory_patterns(store, file=snapshot)

    assert first["ok"] and second["ok"]
    assert first["source_file"] == str(snapshot)
    assert first["ingested"] == 2
    assert second["ingested"] == 2  # updated in place
    rows = store.list_patterns()
    assert len(rows) == 2
    assert all(r["status"] == "validated" for r in rows)


def test_ingest_does_not_regress_promoted(tmp_path: Path):
    from chrono_core.store.store import Store

    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    write_snapshot(tmp_path, "2026-08-01_090633", SAMPLE)
    ingest_metafactory_patterns(store, metafactory_root=tmp_path)
    pid = store.list_patterns()[0]["id"]
    store.set_pattern_status(pid, "promoted")

    ingest_metafactory_patterns(store, metafactory_root=tmp_path)

    statuses = {r["id"]: r["status"] for r in store.list_patterns()}
    assert statuses[pid] == "promoted"


def test_ingest_missing_sources_raise_value_error(tmp_path: Path):
    from chrono_core.store.store import Store

    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    with pytest.raises(ValueError):
        ingest_metafactory_patterns(store, metafactory_root=tmp_path / "nope")
    with pytest.raises(ValueError):
        ingest_metafactory_patterns(store, file=tmp_path / "absent.md")


def test_ingest_parses_nothing_into_zero_without_error(tmp_path: Path):
    from chrono_core.store.store import Store

    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    write_snapshot(tmp_path, "2026-08-01_090633", "# Patterns Library\n\nNo blocks.\n")

    result = ingest_metafactory_patterns(store, metafactory_root=tmp_path)

    assert result == {
        "ok": True,
        "source_file": str(tmp_path / "consolidated" / "2026-08-01_090633" / "patterns_library.md"),
        "ingested": 0,
        "patterns": [],
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/unit/test_metafactory_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chrono_core.integrations.metafactory'`.

- [ ] **Step 3: Implement**

Create `src/chrono_core/integrations/metafactory.py`:

```python
"""Ingest _MetaFactory consolidated pattern snapshots into the pattern index."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from chrono_core.store.store import Store

_HEADER_RE = re.compile(r"^## Pattern:\s*(.+?)\s*$", re.MULTILINE)
_CATEGORY_RE = re.compile(r"\*\*Category\*\*:\s*(.+?)\s*$", re.MULTILINE)
_PROJECTS_RE = re.compile(r"\*\*Projects\*\*:\s*(.+?)\s*$", re.MULTILINE)
_STATEMENT_MARKER = "**Pattern Statement**:"
# Worktree-family markers used by MetaFactory frequency notes.
_MARKERS_RE = re.compile(r"[†‡]")


def parse_patterns_library(text: str) -> list[dict[str, Any]]:
    """Parse a patterns_library.md into pattern dicts (best effort per block)."""
    patterns: list[dict[str, Any]] = []
    headers = list(_HEADER_RE.finditer(text))
    for index, match in enumerate(headers):
        start = match.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        block = text[start:end]

        title = match.group(1).strip()
        category_match = _CATEGORY_RE.search(block)
        category = category_match.group(1).strip() if category_match else None

        projects: list[str] = []
        projects_match = _PROJECTS_RE.search(block)
        if projects_match:
            raw = _MARKERS_RE.sub("", projects_match.group(1))
            projects = [part.strip() for part in raw.split(",") if part.strip()]

        statement_start = block.find(_STATEMENT_MARKER)
        statement = ""
        if statement_start >= 0:
            body = block[statement_start + len(_STATEMENT_MARKER):]
            statement = "\n".join(
                line.strip() for line in body.strip().splitlines()
            ).strip()

        patterns.append(
            {
                "title": title,
                "statement": statement,
                "category": category,
                "projects": projects,
            }
        )
    return patterns


def find_latest_patterns_file(root: Path) -> Path | None:
    """Newest consolidated/<stamp>/patterns_library.md, or None."""
    consolidated = Path(root) / "consolidated"
    if not consolidated.is_dir():
        return None
    for entry in sorted(consolidated.iterdir(), reverse=True):
        candidate = entry / "patterns_library.md"
        if candidate.is_file():
            return candidate
    return None


def ingest_metafactory_patterns(
    store: Store,
    *,
    metafactory_root: str | Path | None = None,
    file: str | Path | None = None,
) -> dict[str, Any]:
    """Ingest one snapshot's patterns as validated, source='metafactory'."""
    if file is not None:
        source = Path(file)
    else:
        resolved = Path(metafactory_root) if metafactory_root else default_metafactory_root()
        found = find_latest_patterns_file(resolved)
        if found is None:
            raise ValueError(f"no consolidated patterns_library.md under {resolved}")
        source = found
    if not source.is_file():
        raise ValueError(f"patterns file not found: {source}")

    parsed = parse_patterns_library(source.read_text(encoding="utf-8"))
    ingested: list[dict[str, Any]] = []
    with store.transaction():
        for pattern in parsed:
            pattern_id = store.upsert_pattern(
                title=pattern["title"],
                statement=pattern["statement"],
                category=pattern["category"],
                source="metafactory",
                source_ref=str(source),
                projects=pattern["projects"],
                status="validated",
            )
            ingested.append({"id": pattern_id, "title": pattern["title"], "status": "validated"})
    return {
        "ok": True,
        "source_file": str(source),
        "ingested": len(ingested),
        "patterns": ingested,
    }


def default_metafactory_root() -> Path:
    return Path.home() / "workspace" / "_MetaFactory"
```

Note: place `default_metafactory_root` above its first use or rely on call-time resolution
(it is called at runtime, so definition order in the module does not matter).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/unit/test_metafactory_ingest.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/chrono_core/integrations/metafactory.py tests/unit/test_metafactory_ingest.py
git commit -m "feat: MetaFactory patterns_library ingestion adapter"
```

---

### Task 5: Deterministic candidate mining

**Files:**
- Create: `src/chrono_core/management/patterns.py`
- Test: `tests/unit/test_pattern_mining.py` (create)

**Interfaces:**
- Consumes: `term_project_counts` (Task 2), direct SQL over `decisions`/`observations`.
- Produces: `mine_pattern_candidates(store: Store, *, min_projects: int = 2, limit: int = 20) -> dict` — `{"ok": True, "mined": [{"id", "title"}], "skipped_existing": int}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_pattern_mining.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/unit/test_pattern_mining.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chrono_core.management.patterns'`.

- [ ] **Step 3: Implement**

Create `src/chrono_core/management/patterns.py`:

```python
"""Deterministic cross-project pattern candidate mining."""
from __future__ import annotations

from typing import Any

from chrono_core.textutil import term_project_counts
from chrono_core.store.store import Store


def mine_pattern_candidates(
    store: Store, *, min_projects: int = 2, limit: int = 20
) -> dict[str, Any]:
    """Cluster recurring keywords across projects into candidate patterns.

    Terms must appear in at least ``min_projects`` distinct projects. A term
    whose candidate title already exists is skipped, never overwritten.
    """
    conn = store._connect()
    documents: list[tuple[str, str]] = []
    for row in conn.execute(
        "SELECT project_id, title, rationale FROM decisions"
    ).fetchall():
        documents.append((row["project_id"], f"{row['title']} {row['rationale'] or ''}"))
    for row in conn.execute(
        "SELECT project_id, content FROM observations"
    ).fetchall():
        documents.append((row["project_id"], row["content"]))

    counts = term_project_counts(documents)
    qualified = [
        (term, per_project)
        for term, per_project in counts.items()
        if len(per_project) >= min_projects
    ]
    qualified.sort(key=lambda item: (-len(item[1]), -sum(item[1].values()), item[0]))

    mined: list[dict[str, Any]] = []
    skipped = 0
    for term, per_project in qualified[:limit]:
        title = f"Recurring theme: {term}"
        if conn.execute("SELECT 1 FROM patterns WHERE title = ?", (title,)).fetchone():
            skipped += 1
            continue
        project_list = sorted(per_project)
        statement = (
            f"Term '{term}' recurs across {len(project_list)} projects "
            f"({', '.join(project_list)}); totals: "
            f"{', '.join(f'{pid}={n}' for pid, n in sorted(per_project.items()))}."
        )
        pattern_id = store.upsert_pattern(
            title=title,
            statement=statement,
            category=None,
            source="mined",
            source_ref=None,
            projects=project_list,
            status="candidate",
        )
        mined.append({"id": pattern_id, "title": title})

    return {"ok": True, "mined": mined, "skipped_existing": skipped}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/unit/test_pattern_mining.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/chrono_core/management/patterns.py tests/unit/test_pattern_mining.py
git commit -m "feat: deterministic pattern candidate mining across projects"
```

---

### Task 6: CLI wiring

**Files:**
- Modify: `src/chrono_core/cli.py`
- Test: `tests/unit/test_pattern_cli.py` (create)

**Interfaces:**
- Consumes: `ingest_metafactory_patterns`, `mine_pattern_candidates`, `Store.list_patterns`, `Store.set_pattern_status` (Tasks 3–5).
- Produces: subcommands `chrono ingest-patterns`, `chrono mine-patterns`, `chrono patterns {list,set-status}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_pattern_cli.py`:

```python
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
    snap = tmp_path / "_MetaFactory" / "consolidated" / "2026-08-01_090633"
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/unit/test_pattern_cli.py -v`
Expected: FAIL — argparse exits with "invalid choice" / unrecognized args.

- [ ] **Step 3: Wire the CLI**

In `src/chrono_core/cli.py`, add parsers inside `build_parser()` (after `p_export` definitions):

```python
    p_ingest_patterns = sub.add_parser(
        "ingest-patterns", help="ingest _MetaFactory consolidated patterns"
    )
    p_ingest_patterns.add_argument(
        "--metafactory-root",
        default=str(Path.home() / "workspace" / "_MetaFactory"),
        help="_MetaFactory checkout root",
    )
    p_ingest_patterns.add_argument(
        "--file", default=None, help="explicit patterns_library.md path"
    )
    p_ingest_patterns.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_mine = sub.add_parser(
        "mine-patterns", help="mine recurring keyword patterns across projects"
    )
    p_mine.add_argument("--min-projects", type=int, default=2)
    p_mine.add_argument("--limit", type=int, default=20)
    p_mine.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_patterns = sub.add_parser("patterns", help="inspect and manage the pattern index")
    patterns_sub = p_patterns.add_subparsers(dest="patterns_command")
    p_patterns_list = patterns_sub.add_parser("list", help="list patterns")
    p_patterns_list.add_argument("--status", default=None)
    p_patterns_list.add_argument("--limit", type=int, default=50)
    p_patterns_list.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )
    p_patterns_set = patterns_sub.add_parser(
        "set-status", help="transition a pattern's lifecycle status"
    )
    p_patterns_set.add_argument("pattern_id")
    p_patterns_set.add_argument(
        "status", choices=["candidate", "validated", "promoted", "retired"]
    )
    p_patterns_set.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )
```

And dispatch in `main()` (before the `if args.command == "export":` block):

```python
    if args.command == "ingest-patterns":
        from chrono_core.integrations.metafactory import ingest_metafactory_patterns

        store = services.open_store(args.db_path)
        try:
            result = ingest_metafactory_patterns(
                store,
                metafactory_root=args.metafactory_root,
                file=args.file,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "mine-patterns":
        from chrono_core.management.patterns import mine_pattern_candidates

        result = mine_pattern_candidates(
            services.open_store(args.db_path),
            min_projects=args.min_projects,
            limit=args.limit,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "patterns":
        if args.patterns_command == "list":
            store = services.open_store(args.db_path)
            patterns = store.list_patterns(status=args.status, limit=args.limit)
            for row in patterns:
                row.pop("statement", None)
            print(json.dumps({"ok": True, "count": len(patterns), "patterns": patterns}, indent=2))
            return 0
        if args.patterns_command == "set-status":
            store = services.open_store(args.db_path)
            try:
                result = store.set_pattern_status(args.pattern_id, args.status)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        parser.error("patterns requires a subcommand")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/unit/test_pattern_cli.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/chrono_core/cli.py tests/unit/test_pattern_cli.py
git commit -m "feat: CLI for pattern ingestion, mining, listing, and lifecycle"
```

---

### Task 7: Full verification, smoke test, docs, merge prep

**Files:**
- Modify: `docs/ROADMAP.md`
- Modify: `docs/CONTEXT.md`

**Interfaces:** none (documentation + verification only).

- [ ] **Step 1: Full suite + lint**

Run: `uv run --extra dev pytest -q && uv run --extra dev ruff check .`
Expected: all tests pass, lint clean. Fix anything before continuing.

- [ ] **Step 2: End-to-end smoke test**

```bash
rm -rf /tmp/opencode/pattern-smoke && mkdir -p /tmp/opencode/pattern-smoke/proj-a /tmp/opencode/pattern-smoke/proj-b /tmp/opencode/pattern-smoke/mf/consolidated/2026-08-26_000000
printf '## Pattern: Fail-Closed Gating\n\n**Category**: security\n**Projects**: proj-a\n\n**Pattern Statement**:\nDefault is rejection.\n' > /tmp/opencode/pattern-smoke/mf/consolidated/2026-08-26_000000/patterns_library.md
DB=/tmp/opencode/pattern-smoke/db.sqlite
for p in proj-a proj-b; do uv run chrono handoff --cwd /tmp/opencode/pattern-smoke/$p --workspace-root /tmp/opencode/pattern-smoke --db-path $DB --summary s --decision "circuit breaker for $p" >/dev/null; done
uv run chrono ingest-patterns --metafactory-root /tmp/opencode/pattern-smoke/mf --db-path $DB
uv run chrono mine-patterns --db-path $DB
uv run chrono resume --cwd /tmp/opencode/pattern-smoke/proj-a --workspace-root /tmp/opencode/pattern-smoke --db-path $DB --json | python3 -c "import json,sys; print([p['title'] for p in json.load(sys.stdin)['recommended_patterns']])"
```

Expected: ingest reports 1 pattern; mine reports a `Recurring theme:` candidate; resume JSON lists recommended pattern titles (non-empty list containing either the Fail-Closed pattern or a recurring-theme candidate).

- [ ] **Step 3: Update roadmap and context docs**

In `docs/ROADMAP.md` Phase 4, tick:

```markdown
- [x] reusable pattern index.
- [x] pattern recommendation in resume context.
```

In `docs/CONTEXT.md`, append to "What Landed" (after the export graph bullet):

```markdown
- Pattern index (Phase 4 slice): `chrono ingest-patterns` imports MetaFactory
  consolidated patterns, `chrono mine-patterns` derives deterministic
  candidates, and resume/MCP context carries FTS-scored
  `recommended_patterns` (see
  `docs/superpowers/specs/2026-08-26-pattern-index-design.md`).
```

- [ ] **Step 4: Commit**

```bash
git add docs/ROADMAP.md docs/CONTEXT.md
git commit -m "docs: mark pattern index and resume recommendations landed"
```

---

## Self-Review Notes

- Spec coverage: schema v4 (T1), shared tokenizer (T2), Store CRUD + lifecycle + safe search + recommendations (T3), MetaFactory adapter incl. errors/idempotency/no-regression (T4), mining threshold/limit/skip semantics (T5), all four CLI surfaces + resume payload (T6), docs + verification (T7). `patterns set-status` rejecting unknown ids non-zero is covered (exit code 1 via `result["ok"]`); unknown statuses exit 2.
- Type consistency: `search_patterns_safe(query, *, limit, statuses)` used identically in T3 internal call; `upsert_pattern` kwargs consistent across T3/T4/T5.
