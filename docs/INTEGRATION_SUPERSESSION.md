# Existing Tool Integration and Supersession Plan

## Existing Pieces

### `project-tracking`

Status: historical placeholder, now archived as source evidence in Continuity.

It already points to `tool-project-tracker` / `workspace-intelligence` as canonical. Continuity Core can supersede this immediately in documentation once Continuity Core has a README and handoff model.

`continuity ingest-existing-tools` imports the `project-tracking` directory as an `archived_source_evidence` observation on a dedicated project entry, preserving its README and files without treating it as active.

### `tool-project-tracker` / `workspace-intelligence`

Status: useful existing implementation.

Current strengths:

- workspace git project discovery
- SQLite registry
- git status tracking
- project metadata and current progress
- markdown export
- MCP server
- GearCore skill packaging

Current gaps relative to Continuity Core:

- no session handoff as a first-class record
- no graph of decisions, blockers, tasks, specs, and docs
- no dedicated management/distillation workflow
- no stale/contradictory documentation review queue
- no cross-project pattern recommendation loop

Recommended path:

1. Read and reuse the implementation where possible.
2. Import registry data or wrap its discovery service.
3. **Status:** `continuity_core.integrations.workspace_intelligence` now imports the SQLite registry via `continuity ingest-existing-tools`, including project metadata, git state, and lifecycle phase.
4. Avoid deleting or replacing it until Continuity Core has feature parity for project discovery and metadata export.
5. Decide later whether to absorb it as `continuity_core.workspace`.

### `_MetaFactory`

Status: valuable knowledge distillation pipeline.

Current strengths:

- collects `DISTILL`, `AGENTS`, `CLAUDE`, `CONTEXT`, and skill docs across projects
- supports immutable snapshots
- has consolidation prompts for reusable patterns and GearCore skill output

Current gaps relative to Continuity Core:

- not live operational state
- not tied to sessions, blockers, decisions, or next actions
- consolidation is manual/AI-assisted rather than a managed workflow
- active pattern enforcement remains unresolved

Recommended path:

1. Treat `_MetaFactory` as an upstream pattern/insight source.
2. Add a Continuity Core adapter to read latest snapshots/consolidations.
3. Later fold collector behavior into `continuity_core.management` if the boundary becomes artificial.

## Supersession Rule

Supersede only after three conditions are true:

1. Continuity Core can import existing state without data loss.
2. Continuity Core has equivalent or better user-facing workflows.
3. Documentation clearly tells agents which tool is canonical.
