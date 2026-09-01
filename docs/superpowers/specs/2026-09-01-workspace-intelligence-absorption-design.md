# Chrono Core: Workspace Intelligence Absorption — Design

Date: 2026-09-01
Status: Approved staged implementation contract
Phase: 5 — Supersession / Consolidation
Related: `docs/INTEGRATION_SUPERSESSION.md`, `docs/ROADMAP.md`

## Evidence and problem

The authoritative `tool-project-tracker` source snapshot implements a compact
`workspace-intelligence` registry. Its durable user workflows are:

- discover git projects and collect current git state;
- list projects with status, dirty, tag, and limit filters;
- show one project by id, absolute path, or workspace-relative path;
- refresh one project's README and git-derived state;
- update lifecycle and descriptive metadata or current progress;
- export an Obsidian-oriented index and one Markdown page per project.

Chrono Core already exceeds the source tool for continuity history, project
identity reconciliation, lifecycle records, review, search, and Markdown
export. It can also import the source SQLite registry without discarding its
metadata. It does not yet expose equivalent project list/show/update/progress
workflows, and its canonical `projects` row lacks several source fields.
Therefore the source tool is not yet safe to archive.

## Parity decision

Absorb the capability in three independently reviewable stages:

1. **Project catalog management (this slice):** make project metadata canonical
   in Chrono and expose stable list/show/update/progress services through CLI
   and MCP.
2. **Live inventory refresh:** reconcile discovery with missing projects,
   collect current git/README state, and support dirty filtering without
   treating session-time git snapshots as live inventory state.
3. **Migration acceptance:** prove source-to-Chrono field parity, compare
   exported records, update canonical-tool documentation, then archive the
   source only through a separately authorized operation.

The existing importer remains available throughout the transition.

## Stage 1 data contract

Schema version 5 adds nullable `priority`, `owner`, `description_usage`,
`current_progress`, `notes`, and `lifecycle_phase` columns plus JSON-text
`tags` and `other_factors` columns to `projects`. Existing `status`, `phase`,
and `summary` remain canonical. Legacy `lifecycle_phase` must stay separate
from Chrono's operational `phase`: distillation writes values such as
`active`, `blocked`, and `unknown`, while lifecycle maturity uses `prototype`,
`validation`, `commercialisation`, `maintenance`, and `archived`.

Tags are a JSON array of unique strings in caller order. Other factors are a
JSON object. Store reads decode both fields and reject malformed update input
before mutation. Supported status values are `active`, `paused`, `missing`,
and `archived`; lifecycle phase and priority retain the source tool's
enumerations. Operational `phase` remains owned by Chrono distillation and is
readable but is not changed by the project-catalog metadata command.

Project selectors resolve in this order: exact id, exact absolute path, then
exact relative path. Unknown or ambiguous selectors return structured errors.

## Stage 1 interfaces

### Store and shared services

- list with optional `status`, `tag`, and `limit` filters;
- show a complete project catalog record;
- update one or more metadata fields;
- update `current_progress` through a narrow convenience operation.

All service envelopes include `ok`; failures include a stable `code`. Reads
must not create a database or project or mutate an existing schema. An older
schema returns `schema_upgrade_required` rather than leaking a SQLite error;
opening it through an authorized write path runs the migration. Updates change
`updated_at` and return the refreshed record. An update with no supplied
fields is rejected.

### CLI

```text
chrono project list [--status STATUS] [--tag TAG] [--limit N] [--db-path PATH]
chrono project show PROJECT [--db-path PATH]
chrono project update PROJECT [metadata options] [--db-path PATH]
chrono project progress PROJECT TEXT [--db-path PATH]
```

The CLI emits the same JSON envelope as services. `--tag` is repeatable on
update and replaces the tag set. `--lifecycle-phase` changes maturity without
overwriting Chrono's distilled operational `phase`. `--other-factors` accepts
one JSON object.

### MCP

Expose equivalent `chrono_core_list_projects`, `chrono_core_get_project`,
`chrono_core_update_project_metadata`, and `chrono_core_update_project_progress`
tools. MCP handlers delegate to shared services so CLI and MCP semantics cannot
drift.

## Project page decision

Markdown project pages should include canonical status, operational phase,
lifecycle phase, priority, tags, owner, description/usage, current progress,
and notes when present. They should
retain the latest session summary and current blockers/actions/decisions.
They should not dump arbitrary observations or full session history by default;
those remain searchable evidence and would make routine exports noisy and
potentially sensitive. A later explicit history export can add that scope.

## Non-goals for Stage 1

- Live git refresh, dirty filtering, README re-extraction, or missing marking.
- Background scanning or daemon behavior.
- Deleting, moving, or changing `tool-project-tracker`.
- Automatically exporting Markdown after each metadata mutation.
- Treating imported source observations as the new metadata truth.

## Acceptance

1. Empty and v4 databases migrate to v5 with defaults preserving old rows.
2. Store selectors, filtering, JSON fields, updates, and no-op rejection are
   covered by tests.
3. CLI and MCP expose the shared contracts and structured missing-project
   errors.
4. Markdown pages render the new canonical metadata without dumping raw
   observations or full history.
5. Existing ingestion, discovery, resume, review, and export tests remain
   green.
6. Documentation states that Stage 1 is partial parity and the source tool is
   still retained until Stages 2 and 3 pass.
