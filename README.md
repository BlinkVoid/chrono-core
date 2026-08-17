# Chrono Core

Chrono Core is workspace-level project memory infrastructure for humans and AI agents working across many projects in parallel.

It began in Hub incubator as an incubator and now lives as its own workspace project. Its scope is `~/workspace`: project discovery, session handoff capture, documentation reconciliation, decision tracking, and reusable knowledge distillation across repositories.

## Current Status

Phase 1 local core, Phase 2 agent interface, and Phase 3 management session workflows are implemented. Chrono Core now supports SQLite persistence, project resolution/discovery, session handoff capture, resume context, lifecycle closure, search, markdown/wiki export, workspace-intelligence ingestion, MCP/GearCore integration, deterministic distillation, doc reconciliation, stale/contradictory doc detection, project health review, improvement advice, and a review queue. Phase 4 cross-project intelligence is the next roadmap focus.

Available CLI commands:

- `chrono resolve` — identify the project from a working directory.
- `chrono discover` — scan a workspace for project markers and upsert discovered projects.
- `chrono handoff` — capture a session handoff into the continuity database.
- `chrono resume` — show resume context for a project.
- `chrono distill` — derive and persist compact project state from captured records.
- `chrono review` — reconcile docs, report stale/contradictory state, generate health/advice, and build a review queue.
- `chrono blocker resolve <id>` — mark an open blocker resolved (ids are shown in resume output).
- `chrono action complete <id>` — mark an open next action done.
- `chrono search <query>` — full-text search captured observations (FTS5).
- `chrono ingest-existing-tools` — import project metadata from the `workspace-intelligence` SQLite registry and archive the legacy `project-tracking` directory as source evidence.
- `chrono export markdown` — write a derived project index and project pages from the continuity database.
- `chrono gearcore install-plan` — print GearCore registration commands for the skill and MCP server.

## Core Problem

AI agents and humans lose continuity when project state is scattered across TODO files, plans, specs, READMEs, chat sessions, issue notes, and partially updated documentation. After a project pauses for weeks, it becomes hard to answer:

- What is this project?
- What happened last?
- What is blocked?
- What should happen next?
- Which design decisions still matter?
- Which docs are stale or contradictory?
- What reusable patterns from other projects apply here?

Chrono Core treats project state as something that must be explicitly captured, distilled, reconciled, and queryable.

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
