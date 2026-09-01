# Chrono Core: Live Project Inventory — Design

Date: 2026-09-01
Status: Approved implementation contract
Phase: 5 — Workspace Intelligence Absorption, Stage 2
Related: `2026-09-01-workspace-intelligence-absorption-design.md`

## Problem

Stage 1 made project catalog metadata canonical in Chrono, but the legacy
`workspace-intelligence` tool still owns three live-inventory capabilities:

- refreshing current Git state independently from session handoffs;
- reconciling projects that disappear and later return;
- filtering the project list by current dirty state.

Chrono's `sessions.git_*` columns are historical snapshots and must not be
reused as current inventory. Project `status` is operator-visible metadata, so
missing reconciliation must also preserve the status that existed before a
temporary disappearance.

## Goal

Make `chrono discover` the canonical persisted workspace refresh, add a
single-project refresh, expose current inventory through CLI and MCP, and
support dirty filtering. The implementation remains local-only and does not
archive or modify `tool-project-tracker`.

## Storage contract

Schema version 6 adds one `project_inventory` row per physical project:

```text
project_id (PK/FK projects.id)
workspace_root
marker
depth
last_seen_at
missing_since
status_before_missing
last_error_json
is_git
branch
detached
head_sha
head_subject
remote_name
remote_url
default_branch
dirty
changed_count
untracked_count
collected_at
```

This table is current derived state, not historical evidence. Session Git
snapshots remain unchanged. Project reads expose it as a nested `inventory`
object; the existing catalog fields stay flat.

Each inventory row records the exact scan root and discovery depth that last
saw the project. A scan reconciles only prior rows from that exact root whose
stored depth is within the current `max_depth`. A provisional row is eligible
for reconciliation only when the current scan includes provisional projects.
This prevents a narrower or differently configured scan from falsely marking
out-of-scope projects missing.

## Discovery and missing reconciliation

Persisted `chrono discover` performs one bounded workflow:

1. Traverse deterministically using the existing marker and skip rules.
2. Upsert every discovered physical project.
3. Collect current Git state for projects with a `.git` directory or file.
4. Upsert inventory state and clear `missing_since` / `last_error_json` on
   success.
5. Reconcile eligible inventory rows not seen in this scan as missing.

When a project becomes missing, store its current status in
`status_before_missing` unless it is already `missing`, then set catalog status
to `missing`. When it returns, restore `status_before_missing` (default
`active`) and clear the saved value. This makes missing state reversible without
losing `paused` or `archived` metadata.

`--no-persist` remains a pure traversal: it does not initialize a database,
run Git commands, or reconcile missing projects.

One project's filesystem or Git failure must not abort the scan. Record a
bounded structured error for that project, keep its last successful Git fields,
and continue. A missing/unreadable workspace root returns the existing
structured failure and performs no reconciliation.

## Git collection

Use shell-free, bounded `git -C PATH ...` subprocess calls with an explicit
timeout. Collect:

- porcelain-v1 branch/status;
- changed and untracked counts;
- detached state, short HEAD, and latest subject;
- first configured remote name and URL;
- remote default branch when available, otherwise local `main`/`master`.

Non-Git marker projects remain valid inventory entries with `is_git=false`,
null branch/HEAD fields, and `dirty=false`. Dirty filters apply to current
inventory only and never infer from the latest session.

## Interfaces

### Store and services

- `refresh_workspace_inventory(...)` returns counts for discovered, persisted,
  refreshed, missing, and failed projects plus bounded failures.
- `refresh_project_inventory(selector, ...)` refreshes one registered project
  and returns the same complete project record shape as `project show`.
- `list_projects(..., dirty=None)` joins current inventory and filters by
  `dirty` when supplied.
- `get_project(...)` includes nested inventory or `null` for catalog-only rows.

Unknown selectors, missing paths, non-current schemas, timeouts, and Git
failures use stable error codes. Read-only list/show calls never refresh.

### CLI

```text
chrono discover [existing options]
chrono project refresh PROJECT [--db-path PATH]
chrono project list [--dirty | --no-dirty] [existing filters]
```

All commands emit stable JSON. Persisted discovery refreshes and reconciles;
`--no-persist` retains its previous read-only meaning.

### MCP

Add:

- `chrono_core_discover_projects(workspace_root?, max_depth=3,
  include_provisional=false, db_path?)`
- `chrono_core_refresh_project(project, db_path?)`

Extend `chrono_core_list_projects` with optional `dirty`. MCP discovery and
refresh are documented local database/filesystem mutations.

### Markdown

When inventory exists, project pages show branch, HEAD, dirty, changed,
untracked, last seen/refreshed, and missing time. The project index adds compact
branch and dirty columns. No Git history or command output is exported.

## Non-goals

- Background scanning, file watchers, or a daemon.
- Persisting Git command stdout/stderr.
- Automatically committing, fetching, pulling, or modifying repositories.
- README metadata extraction; Stage 1 catalog metadata remains authoritative.
- Multi-root membership history. The latest successful exact-root provenance
  is sufficient for this absorption stage.
- Archiving or deleting the source tool.

## Acceptance

1. Fresh and v5 databases migrate to v6; old project/session state survives.
2. Git directory and `.git` file repositories refresh correctly; non-Git
   marker projects remain clean inventory entries.
3. Dirty true/false filters use inventory, not session snapshots.
4. Missing reconciliation is exact-root/depth/provisional scoped and restores
   the prior status when a project returns.
5. Per-project Git failures are bounded, recorded, and do not abort other
   refreshes.
6. `--no-persist`, list, and show have no refresh or migration side effects.
7. CLI, MCP, Markdown, importer, and migration contracts are covered.
8. Full tests, Ruff, and `git diff --check` pass; Phase 5 remains incomplete
   until Stage 3 migration/export acceptance succeeds.
