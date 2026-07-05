# Continuity Core

Continuity Core is workspace-level project memory infrastructure for humans and AI agents working across many projects in parallel.

It began in Hub incubator as an incubator and now lives as its own workspace project. Its scope is `~/workspace`: project discovery, session handoff capture, documentation reconciliation, decision tracking, and reusable knowledge distillation across repositories.

## Current Status

Phase 1 local core implemented with SQLite persistence, project resolution, workspace discovery, session handoff capture, resume context, markdown export, and workspace-intelligence ingestion. Phase 2 MCP server and GearCore install-plan adapter are implemented. Phase 3 has a deterministic project distillation workflow. Additional management workflows remain Phase 3.

Available CLI commands:

- `continuity resolve` — identify the project from a working directory.
- `continuity discover` — scan a workspace for project markers and upsert discovered projects.
- `continuity handoff` — capture a session handoff into the continuity database.
- `continuity resume` — show resume context for a project.
- `continuity distill` — derive and persist compact project state from captured records.
- `continuity ingest-existing-tools` — import project metadata from the `workspace-intelligence` SQLite registry and archive the legacy `project-tracking` directory as source evidence.
- `continuity export markdown` — write a derived project index and project pages from the continuity database.
- `continuity gearcore install-plan` — print GearCore registration commands for the skill and MCP server.

## Core Problem

AI agents and humans lose continuity when project state is scattered across TODO files, plans, specs, READMEs, chat sessions, issue notes, and partially updated documentation. After a project pauses for weeks, it becomes hard to answer:

- What is this project?
- What happened last?
- What is blocked?
- What should happen next?
- Which design decisions still matter?
- Which docs are stale or contradictory?
- What reusable patterns from other projects apply here?

Continuity Core treats project state as something that must be explicitly captured, distilled, reconciled, and queryable.

## Design Docs

- [Project Brief](PROJECT_BRIEF.md)
- [System Design](docs/SYSTEM_DESIGN.md)
- [Data Model](docs/DATA_MODEL.md)
- [Management Workflows](docs/MANAGEMENT_WORKFLOWS.md)
- [Plugin Strategy](docs/PLUGIN_STRATEGY.md)
- [GearCore Skill Spec](docs/GEARCORE_SKILL_SPEC.md)
- [Usage](docs/USAGE.md)
- [Integration and Supersession Plan](docs/INTEGRATION_SUPERSESSION.md)
- [Roadmap](docs/ROADMAP.md)
- [Project Context](docs/CONTEXT.md)
- [MVP CLI and MCP Contract](docs/MVP_CONTRACT.md)
- [SQLite Schema](docs/SQLITE_SCHEMA.md)
- [Doc Consolidation Playbook](docs/DOC_CONSOLIDATION_PLAYBOOK.md)
