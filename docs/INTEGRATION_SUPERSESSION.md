# Existing Tool Integration and Supersession Plan

## Existing Pieces

### `project-tracking`

Status: historical placeholder, now archived as source evidence in Chrono Core.

It already points to `tool-project-tracker` / `workspace-intelligence` as canonical. Chrono Core can supersede this immediately in documentation once Chrono Core has a README and handoff model.

`chrono ingest-existing-tools` imports the `project-tracking` directory as an `archived_source_evidence` observation on a dedicated project entry, preserving its README and files without treating it as active.

### `tool-project-tracker` / `workspace-intelligence`

Status: feature parity accepted; retained pending separately authorized archival.

Current strengths:

- workspace git project discovery
- SQLite registry
- git status tracking
- project metadata and current progress
- markdown export
- MCP server
- GearCore skill packaging

Current gaps relative to Chrono Core:

- no session handoff as a first-class record
- no graph of decisions, blockers, tasks, specs, and docs
- no dedicated management/distillation workflow
- no stale/contradictory documentation review queue
- no cross-project pattern recommendation loop

Recommended path:

1. Read and reuse the implementation where possible.
2. Import registry data or wrap its discovery service.
3. **Status:** `chrono_core.integrations.workspace_intelligence` now imports the SQLite registry via `chrono ingest-existing-tools`, including project metadata, git state, and lifecycle phase.
4. **Status (Stages 1–3 accepted):** schema v5 carries the source
   registry's catalog fields on `projects`, and `chrono project
   list/show/update/progress` plus the
   `chrono_core_list_projects` / `chrono_core_get_project` /
   `chrono_core_update_project_metadata` /
   `chrono_core_update_project_progress` MCP tools cover the source tool's
   project metadata workflows. Stage 2 covers bounded live Git refresh,
   missing reconciliation, and dirty filtering through `chrono discover` and
   `chrono project refresh`. Stage 3 proves exact isolated migration parity and
   fast, non-mutating Markdown export against the live 80-project registry. See
   `docs/superpowers/specs/2026-09-01-workspace-intelligence-migration-acceptance.md`.
5. Retain the live implementation and GearCore registrations until the separate
   archival plan is explicitly authorized and its rollback package is ready.
6. After a verified archival operation, route active project tracking to Chrono
   Core while retaining source-registry import compatibility.

### `_MetaFactory`

Status: valuable knowledge distillation pipeline.

Current strengths:

- collects `DISTILL`, `AGENTS`, `CLAUDE`, `CONTEXT`, and skill docs across projects
- supports immutable snapshots
- has consolidation prompts for reusable patterns and GearCore skill output

Current gaps relative to Chrono Core:

- not live operational state
- not tied to sessions, blockers, decisions, or next actions
- consolidation is manual/AI-assisted rather than a managed workflow
- active pattern enforcement remains unresolved

Recommended path:

1. Treat `_MetaFactory` as an upstream pattern/insight source.
2. Add a Chrono Core adapter to read latest snapshots/consolidations.
3. Later fold collector behavior into `chrono_core_management` if the boundary becomes artificial.

## Supersession Rule

Supersede only after three conditions are true:

1. Chrono Core can import existing state without data loss.
2. Chrono Core has equivalent or better user-facing workflows.
3. Documentation clearly tells agents which tool is canonical.
