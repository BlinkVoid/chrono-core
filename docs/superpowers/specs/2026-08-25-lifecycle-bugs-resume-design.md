# Design: Action Lifecycle, Cross-Project Bugs, Workstream-Scoped Resume

Date: 2026-08-25
Status: Approved
Scope: Full sweep — lifecycle, bug tracking, resume scoping, hygiene, packaging.

## Problem

1. **Stale actions surface forever.** `chrono action` only has `complete`; mis-captured
   or obsolete actions (e.g. a stale "Book 2 six volumes" item) cannot be cancelled,
   edited, or superseded — only marked done, which is untruthful.
2. **Resume drowns current work.** `Store.get_resume_context` selects open actions and
   blockers flat project-global with no limit (`store.py:402-410`) and picks the latest
   session regardless of branch. Projects with parallel work streams (novel lane vs
   platform lane in InternalProject) surface ~30 unrelated items.
3. **No cross-project bug tracking.** Bugs live nowhere queryable; chrono's own defects
   (this design's motivation) are tracked as prose in next_actions.
4. **Hygiene debt** blocks publication: machine-specific path constants, zero SQL
   indexes, CLI/MCP duplication, connection leaks, missing PyPI metadata.

## Decisions (user-approved)

- Scope: full sweep including packaging metadata.
- Bug model: dedicated `bugs` table; local-native truth with nullable
  `remote_url`/`remote_issue_id` columns readying a future one-way GitHub dump/sync
  adapter (implementation deferred to Phase 4). GitHub issues rejected as primary
  store: most workspace projects are unpublished/local, cross-project queries need SQL
  joins with sessions/actions, and offline dogfooding is required.
- Resume scoping: branch-scoped by default with `--all` / `--branch` / `--limit`.
  Explicit workstream entities rejected as over-engineered for now.
- Lifecycle: cancel + edit + reopen + supersede (fullest option).
- Implementation shape: thin service extraction first (Approach B), so every new verb
  costs one implementation shared by CLI and MCP instead of two copies.
- Presentation last: beautified README + local HTML landing page; no repo publishing.

## Architecture

```
cli.py ─────────┐
                ├─► services.py ─► Store ─► SQLite (WAL)
mcp_server.py ──┘
```

- New `src/chrono_core/services.py`: pure functions taking explicit kwargs
  (`project_path`, `db_path`, ids/options), returning canonical result dicts.
  No `argparse.Namespace` in service signatures.
- `mcp_server.py` keeps only tool registration + JSON-RPC plumbing; the ~8 duplicated
  handler bodies collapse into service calls.
- Store caches one connection per db_path for long-lived MCP processes; closed at
  shutdown / explicit close.
- Upward dependency inverted: resolver moves to `domain/`; store no longer imports
  from `workspace/`.

## Schema v3

Ordered migration list `{version: fn}` replaces the binary v2 check; refuses DBs
written by a newer schema version. Personal-path ops script moves to `scripts/`.

### New table `bugs`

| column | notes |
|---|---|
| id | `bug_` prefix |
| project_id | NULLABLE; NULL = workspace-wide |
| title, detail | FTS-covered via external-content `bug_fts` mirroring observation trigger pattern |
| severity | low / medium / high / critical |
| status | open / confirmed / in_progress / fixed / wont_fix / cancelled |
| found_in_session_id | FK sessions |
| fixed_in_session_id | FK sessions |
| remote_url, remote_issue_id | nullable; future gh sync |
| created_at / updated_at / resolved_at | ISO-8601 UTC strings |

### Indexes (first in project history)

`sessions(project_id, ended_at)`; `next_actions(project_id, status, created_at)`;
`blockers(project_id, status, created_at)`; `bugs(project_id, status, created_at)`;
`decisions(project_id, created_at)`; `observations(project_id)`.

## Lifecycle

Centralized status vocabulary in `domain/models.py`:

- next_actions: `open → done | cancelled | superseded`; reopen from done/cancelled.
- blockers: `open → resolved | cancelled`; reopen from either.

New verbs (CLI + MCP mirror):

- `chrono action cancel <id> [--reason]` — sets `cancelled`, `cancelled_at`, audit note
- `chrono action edit <id> --text "..."` — rewrites text, keeps prior text in
  `raw_history_json`
- `chrono action reopen <id>` — back to `open`, clears closure timestamps
- `chrono action supersede <old_id> --text "..."` — inserts replacement carrying
  `supersedes_id=old`, marks old `superseded`; both remain queryable
- `blocker cancel|edit|reopen` mirrors (no blocker supersede)

Idempotency: transitioning to the current status returns
`{"ok": true, "already": true}` without touching timestamps.

Schema additions to existing tables: `next_actions.cancelled_at`, `.supersedes_id`,
`.raw_history_json`; `blockers.cancelled_at`; matching columns via v3 migration.

## Workstream-scoped resume

- Default: detect project's current git branch (existing git.py reader); surface open
  actions/blockers whose originating session has that `git_branch`, plus branch-less
  legacy items. Header shows counts of hidden items on other branches.
- `--all` groups flat list by branch; `--branch X` overrides; `--limit N` default 20
  per category (ends the unbounded list; MCP token budget stays second defense).
- SQL joins `sessions` on `session_id` filtering `git_branch = ?`; NULL-session items
  stay visible.
- Regression test FIRST: two branches, each with its own session + action; default
  resume must show only current-branch items. Reproduces and closes the original
  defect and act_1bf310be06f14655.

## Bug UX

```
chrono bug report "<title>" [--severity S] [--detail ...] [--workspace]
chrono bug list [--status open] [--severity high] [--project PATH]
chrono bug show <id>
chrono bug update <id> [--status ...] [--severity ...] [--detail ...]
                  [--fixed-in-session sess_xxx]
```

- Project from cwd unless `--workspace` (NULL project_id). Listing is cross-project
  by default.
- `chrono search` covers bug text through `bug_fts`.
- Distill/review heuristics fold open high-severity bugs into health scoring.
- Dogfood: file bug #1 = "resume surfaces unrelated workstream actions" referencing
  the regression-test action.

## Hygiene sweep

1. Portability: remove `~/workspace` fallback from config (env var, else
   cwd-based detection); honor `CHRONO_DB_PATH` at call time not import time;
   GearCore skill path configurable instead of `parents[3]`; personal ops script to
   `scripts/`; un-pin tests from personal paths.
2. Robustness: FTS5 MATCH syntax errors → structured `{"ok": false}`; handoff JSON /
   file errors → clean messages; git subprocess `timeout=`; markdown escaping in
   export; `max_tokens=0` handled via `is not None`.
3. Packaging: MIT license + LICENSE (unless user overrides), keywords/classifiers/
   urls/authors, dynamic version from `__init__.py`, `anyio` declared dev dep.

## Rollout order (TDD per slice; pytest + ruff after each)

1. Resume scoping regression (closes original defect)
2. Lifecycle verbs via services extraction
3. Bugs schema + UX; dogfood bug #1
4. Hygiene + packaging
5. Presentation last: beautified README.md + standalone local HTML landing page at
   `docs/site/index.html` (SEO keywords: MCP, project memory, session handoff, agent
   continuity). No publishing.

## Non-goals this cycle

- GitHub sync adapter implementation (columns only)
- Workstream entities; decisions supersede flow; project reopen
- Repo publication; CI setup

## Verification

Full pytest suite + ruff per slice. Dogfood check: `chrono resume` on InternalProject
surfaces only current-branch items; `chrono bug list` finds bug #1 cross-project.
