# SQLite Schema

## Decision

Start with SQLite plus FTS and graph-shaped edges. Do not introduce a dedicated graph database until the local schema proves insufficient.

## Version

Schema version: `2`

- v1: initial tables and the `observation_fts` virtual table.
- v2: FTS sync triggers on `observations` (insert/update/delete). The
  `observation_fts` table is external-content, so without triggers it stayed
  permanently empty. Migrating to v2 runs an FTS `rebuild` so rows captured
  under v1 become searchable.

## Canonical Tables

The initial executable DDL lives in `src/continuity_core/store/schema.py`.

Core tables:

- `projects`
- `sessions`
- `decisions`
- `blockers`
- `next_actions`
- `documents`
- `observations`
- `edges`
- `observation_fts`

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
- upgrade SQL
- tests against an empty database
- tests against the previous schema once schema v2 exists
