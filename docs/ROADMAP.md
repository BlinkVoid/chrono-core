# Roadmap

## Phase 0 — Design Incubator

- [x] Create incubator project.
- [x] Document mission and principles.
- [x] Document initial system design.
- [x] Document graph-shaped data model.
- [x] Document management workflows.
- [x] Document plugin/GearCore distribution strategy.
- [x] Document existing-tool integration and supersession plan.
- [x] Review existing `workspace-intelligence` implementation in detail.
- [ ] Review `_MetaFactory` collection/consolidation outputs in detail.
- [x] Decide exact integration/supersession boundary.

## Phase 1 — Local Core

Goal: useful local prototype without MCP dependency.

- [x] Python package scaffold.
- [x] SQLite schema and migrations.
- [x] Workspace traversal and project resolver.
- [x] Project registry import from workspace-intelligence SQLite registry (`chrono ingest-existing-tools`).
- [x] Project registry import from a live workspace scan (`chrono discover`).
- [x] Session handoff capture command.
- [x] Resume context generator.
- [x] Basic markdown export.
- [x] Tests for resolver, schema, handoff, and resume context.

- [x] Consolidate CLI on canonical Store/capture/resume path.

Phase 1 persistence slice (completed): deterministic project IDs, `Store` CRUD,
`chrono handoff` with `--summary` and optional JSON/CLI args, `chrono resume`
reading from SQLite, and focused unit tests. MCP, GearCore, and management workflows
are now covered by Phase 2 and Phase 3.

## Phase 2 — Agent Interface

Goal: AI agents can use Chrono Core directly.

- [x] MCP server (`chrono-mcp`) exposing `resolve_project`, `session_handoff`, and `get_resume_context`.
- [x] `session_handoff` tool.
- [x] `get_resume_context` tool.
- [x] `record_decision` / `record_blocker` standalone tools.
- [x] GearCore skill or plugin adapter.
- [x] Codex/Claude/Kimi usage instructions.

## Phase 3 — Management Session

Goal: project state becomes coherent and maintainable.

- [x] `distill_project` workflow.
- [x] `reconcile_docs` workflow.
- [x] stale/contradictory doc detection.
- [x] improvement advice generator.
- [x] project health review output.
- [x] wiki export with review queue.

## Phase 4 — Cross-Project Intelligence

Goal: reuse hard-won patterns across projects.

- [x] MetaFactory ingestion adapter.
- [x] reusable pattern index.
- [x] project similarity search (`chrono similar` + `chrono_core_find_similar_projects`).
- [x] pattern recommendation in resume context.
- [x] promote validated patterns into GearCore skills through reviewed
  `promotion-plan`/digest-gated `promote` commands.

## Phase 5 — Supersession / Consolidation

Goal: reduce duplicated infrastructure.

Candidates:

- `project-tracking` placeholder should become obsolete immediately.
- `tool-project-tracker` / `workspace-intelligence` may be absorbed if Chrono Core implements registry/discovery better.
- `_MetaFactory` may remain a specialized collector or become a Chrono Core management workflow.

Do not delete or replace existing tools until Chrono Core has feature parity and migration tests.

Stages 1–3 of the workspace-intelligence absorption are accepted: schema-v5
catalog parity, bounded live inventory refresh/dirty filtering, and isolated
migration/export acceptance all pass. The final export preserves registered
identity and does not mutate catalog or lifecycle state. Phase 5 remains in
progress only because retiring the live `tool-project-tracker` source and its
GearCore registrations requires separate authorization; the source is retained
until that reviewed archival operation occurs (see
`docs/superpowers/specs/2026-09-01-workspace-intelligence-migration-acceptance.md`
and `docs/superpowers/specs/2026-09-01-tool-project-tracker-archival-plan.md`).
