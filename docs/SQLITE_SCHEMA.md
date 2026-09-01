# SQLite Schema

## Decision

Start with SQLite plus FTS and graph-shaped edges. Do not introduce a dedicated graph database until the local schema proves insufficient.

## Version

Schema version: `6`

- v1: initial tables and the `observation_fts` virtual table.
- v2: FTS sync triggers on `observations` (insert/update/delete). The
  `observation_fts` table is external-content, so without triggers it stayed
  permanently empty. Migrating to v2 runs an FTS `rebuild` so rows captured
  under v1 become searchable.
- v3 (`store/migrations.py`, "lifecycle columns, bugs table + FTS, first
  indexes"): adds lifecycle columns to `next_actions`
  (`cancelled_at`, `supersedes_id` self-reference, `raw_history_json`) and
  `blockers` (`cancelled_at`); adds the `bugs` table with an external-content
  `bug_fts` index plus sync triggers; adds per-table indexes on
  `(project_id, status, created_at)` for sessions/actions/blockers/bugs/
  decisions and `observations(project_id)`.
- v4 (`store/migrations.py`, "patterns table + FTS"): adds the `patterns`
  table with an external-content `pattern_fts` index plus sync triggers.
- v5 (`store/migrations.py`, "project catalog metadata"): adds nullable
  `priority`, `lifecycle_phase`, `owner`, `description_usage`, `current_progress`, and `notes`
  columns plus JSON-text `tags` (default `'[]'`) and `other_factors`
  (default `'{}'`) columns to `projects`, mirroring the
  `tool-project-tracker` registry field set. Existing rows keep their values
  and receive the JSON defaults.
- v6 (`store/migrations.py`, "current project Git inventory and missing
  reconciliation"): adds one current `project_inventory` row per physical
  project, including exact scan-root/depth provenance, bounded Git state,
  failure details, and reversible missing status tracking.

## Migration Framework

Per-version migrations live in `src/chrono_core/store/migrations.py`. Each
migration is a `(version, label)` entry with ordered SQL statements in
`_STATEMENTS`; `apply_pending()` applies pending versions in order, records
them in `schema_migrations`, refuses databases newer than the code's
`SCHEMA_VERSION`, and backfills ledger entries for pre-framework versions so
the ledger stays contiguous from 1 to `SCHEMA_VERSION`. `ALTER TABLE ... ADD
COLUMN` statements are guarded against columns that already exist (SQLite has
no `ADD COLUMN IF NOT EXISTS`). `Store.init_schema()` runs the monolithic DDL,
the v2 FTS rebuild, and then `apply_pending()`.

## Canonical Tables

The initial executable DDL lives in `src/chrono_core/store/schema.py`.

Core tables:

- `projects` (v5 adds `priority`, JSON-text `tags`, `owner`,
  `lifecycle_phase`,
  `description_usage`, `current_progress`, `notes`, and JSON-text
  `other_factors`; `tags` is a JSON array of unique strings and
  `other_factors` a JSON object; the store decodes both on read and validates
  updates before mutation). `phase` remains Chrono's operational/distilled
  state; catalog maturity is stored separately in `lifecycle_phase`.
- `project_inventory` (v6: current Git state and exact-scope missing
  reconciliation; Git command output is never persisted)
- `sessions`
- `decisions`
- `blockers`
- `next_actions` (v3 adds `cancelled_at`, `supersedes_id`, `raw_history_json`)
- `bugs` (v3: severity/status lifecycle, optional session links, remote ids)
- `documents`
- `observations`
- `edges`
- `observation_fts` (external-content over `observations`)
- `bug_fts` (external-content over `bugs.title`/`bugs.detail`, v3)

## Design Notes

### Journaling and write batching

Connections run with `journal_mode=WAL` and `synchronous=NORMAL`. Why: the
store commits per logical record, and with the default rollback journal each
commit costs multiple fsyncs — a single handoff was taking seconds on slow
disks. WAL with `NORMAL` reduces that to one WAL append per commit; the
tradeoff (a power loss can drop the last few commits, never corrupting the
database) is acceptable for continuity metadata that can be re-captured.

Multi-record operations (e.g. `persist_handoff`) additionally batch their
store calls in `Store.transaction()` so a handoff is one atomic commit:
either the session and all its records land, or none do.

### Project path is the physical identity

`projects.path` is UNIQUE. When an upsert arrives with a new project id but a
path that is already registered (the same directory resolved under a different
workspace root), the existing row and its id win; only the metadata is
updated. This keeps sessions, blockers, and actions attached to one project
record instead of raising an IntegrityError or splitting history across ids.
The most specific observed `relative_path` is retained, so resolving the same
directory through a narrower workspace root cannot flatten its metadata later.

The inverse case is also guarded: two different absolute paths may produce the
same workspace-relative id when each is named identically under a different
configured root. The first project keeps that id; the newcomer receives a
deterministic absolute-path fallback id. Chrono never resolves this collision
by overwriting the first project's path or history.

**Reads must resolve through the same rule.** A project id hashes the
workspace-*relative* path, so `cores/DesignCore` under `~/workspace` and
`DesignCore` under `~/workspace/cores` are the same directory with different
ids. Writers reconciled on path but readers did not, so a handoff captured
under one root reported "No project found" under the other — the records were
never lost, just unreachable. `Store.resolve_project_id()` is the read-only
counterpart to `get_or_create_project()`: it prefers an id already registered
for the absolute path and falls back to the computed id. Every read path that
starts from a `ResolvedProject` goes through it (`resume.get_resume_context`,
`mcp_server.handle_get_resume_context`); paths that write first
(`distill`, `review`, `record_decision`, `record_blocker`) already reconcile
via `get_or_create_project`.

### Raw observations are preserved

Management distillation should not destroy evidence. Raw handoff payloads and observations stay in the database even if a later management pass updates project state.

### Edges are generic

The `edges` table allows graph relationships without committing to a graph database too early.

Examples:

- `session -> produced -> artifact`
- `task -> blocked_by -> blocker`
- `decision -> affects -> code_area`
- `document -> contradicts -> document`

### FTS is for retrieval, not truth

FTS indexes help find evidence and prior context. They are derived search surfaces, not the canonical state.

## Migration Rule

Every schema change must have:

- a migration number
- upgrade SQL registered in `store/migrations.py`
- tests against an empty database
- tests against the previous schema once schema v2 exists
