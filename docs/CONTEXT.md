# Chrono Core — Context

## Current Phase

Phase 3 management session workflows are complete over the Phase 1 local core and Phase 2 agent interface. The project has moved out of the incubator into its own workspace folder. Phase 4 cross-project intelligence is the next focus.

## What Landed

- Deterministic project IDs derived from workspace-relative path. The absolute
  path remains the true identity: reads and writes both reconcile through it,
  so a changed workspace root cannot orphan a project's history (see
  `docs/SQLITE_SCHEMA.md`, "Project path is the physical identity").
- `chrono_core.store.Store` SQLite persistence with schema initialization.
- `chrono handoff` persists projects, sessions, decisions, blockers, next actions, and observations.
  - Backwards-compatible `--summary`.
  - Optional JSON payload via `--json PATH` (`-` for stdin).
  - Structured CLI args: `--file`, `--test`, `--decision`, `--blocker`, `--next-action`, `--risk`.
- `chrono resume` reads the database and prints the latest session summary, open blockers, next actions, and recent decisions.
- Git branch/head/dirty state captured when available.
- MCP server (`chrono-mcp`) exposing resume, handoff, lifecycle, search, distill, and review tools backed by the same Store/resolver/capture paths as the CLI.
- Deterministic management review with doc reconciliation, stale/contradictory doc detection, project health, improvement advice, and review queue output.
- Markdown/wiki export now writes project pages plus a `ReviewQueue.md`.
- `chrono export json` emits per-project records (decisions, blockers, next
  actions) as stable, date-filterable JSON for consumer backfill/incremental
  sync (see `docs/superpowers/specs/2026-08-26-record-export-json-design.md`).
- `chrono export graph` emits the same project's records as a derived
  `{nodes, edges}` graph (session-hub co-occurrence plus supersession links;
  no graph DB — see
  `docs/superpowers/specs/2026-08-26-record-graph-export-design.md`).
- Pattern index (Phase 4 slice): `chrono ingest-patterns` imports MetaFactory
  consolidated patterns, `chrono mine-patterns` derives deterministic
  multiword candidates from explicitly semantic observations,
  and resume/MCP context carries FTS-scored
  `recommended_patterns` (see
  `docs/superpowers/specs/2026-08-26-pattern-index-design.md`).
- Project similarity search (Phase 4 slice): `chrono similar` and the
  `chrono_core_find_similar_projects` MCP tool rank other registered projects
  against the current one with deterministic sublinear-TF/IDF cosine scores
  over distilled phase/summary plus observation content, including
  contribution-ranked `shared_terms` (see
  `docs/superpowers/specs/2026-08-31-project-similarity-design.md`).
- Reviewed GearCore pattern promotion (final Phase 4 slice): authored skill
  bundles and before/after evidence can be inspected with `chrono patterns
  promotion-plan` and registered only through `chrono patterns promote` with
  its unchanged digest. Planning is read-only; failed GearCore registration
  leaves the pattern validated (see
  `docs/superpowers/specs/2026-09-01-gearcore-pattern-promotion-design.md`).
- `chrono doctor` provides a read-only database audit for integrity, foreign
  keys, project identity ambiguity, session ownership, legacy collision
  residue, and mined-pattern provenance.
- Focused unit tests covering resolver, store, handoff, resume, MCP tool handlers, distillation, review, and export.

## Project Location

- Project root: `~/workspace/chrono-core`
- Intended scope: `~/workspace`
- Default database: `~/.local/share/chrono-core/chrono.db`

## Related Existing Projects

### `~/workspace/project-tracking`

Old placeholder. It points to `tool-project-tracker` as canonical.

### `~/workspace/tool-project-tracker`

Current `workspace-intelligence` package. It already implements project discovery, SQLite registry, git state tracking, markdown export, MCP tools, and GearCore skill packaging. Missing richer continuity entities such as milestones, next actions, blockers, decisions, and review history.

### `~/workspace/_MetaFactory`

Cross-project knowledge distillery. It collects project docs and skills into snapshots, then uses AI prompts to consolidate patterns. Strong for reusable knowledge extraction, weaker as live operational project state.

## Design Direction

Chrono Core should integrate with the existing pieces first and supersede them later only if boundaries become artificial.

Current preferred split:

- `workspace-intelligence`: upstream project registry/discovery source.
- `_MetaFactory`: upstream reusable pattern/distillation source.
- `chrono-core`: operational continuity graph and management workflows.

## Immediate Next Work

1. Evaluate Phase 4 adoption evidence and prioritize the next roadmap phase.

## Packaging Decision

Chrono Core is a plugin-level capability. Personal use should flow through GearCore; public/open-source use should support standard package, CLI, plugin manifest, and MCP server installation.

GearCore does not currently appear to provide hard workflow hooks, so the MVP should rely on a core skill that recognizes user phrases such as `handoff`, `wrap up`, and `park this`, then runs Chrono Core handoff behavior explicitly.

## Implementation Snapshot — 2026-06-28

Implemented the MCP tool layer over the Phase 1 local core:

- `chrono_core_mcp_server` registers `resolve_project`, `session_handoff`, and `get_resume_context` tools via FastMCP.
- Tool handlers reuse the canonical `Store`, `capture/handoff`, `resume`, and `workspace.resolver` code paths.
- `chrono-mcp` entry point is wired in `pyproject.toml` and referenced by `.mcp.json` and `.codex-plugin/plugin.json`.
- Added focused unit tests for pure MCP tool handlers that exercise the handlers directly without a live MCP client process.

Canonical implementation path remains unchanged:

- `capture/handoff.py` builds and persists handoff payloads.
- `store/store.py` owns SQLite persistence.
- `resume.py` formats DB-backed resume context.
- `cli.py` and `mcp_server.py` are thin adapters over those modules.

## Implementation Snapshot — 2026-07-05

Completed Phase 3 management session workflows:

- `chrono review` runs deterministic doc reconciliation, stale/contradictory doc detection, project health review, improvement advice, and review queue generation.
- `chrono_core_review_project` exposes the same workflow through MCP.
- `chrono export markdown` includes health/review sections on project pages and writes a top-level `ReviewQueue.md`.
- Roadmap status now treats Phase 4 cross-project intelligence as the active next phase.

## Implementation Snapshot — 2026-08-31

Landed the project similarity search Phase 4 slice (see
`docs/superpowers/specs/2026-08-31-project-similarity-design.md`):

- `Store.find_similar_projects` scores other registered projects against a
  selected project using cosine similarity over sublinear-TF/IDF term weights;
  each project document combines its distilled phase/summary with captured
  observation content. Scores are rounded for a stable JSON contract and each
  result carries up to eight `shared_terms` ordered by score contribution.
- The shared `services.find_similar_projects` path is read-only: it verifies
  the project's physical path is already registered, never registers unknown
  projects, and reports a missing database structurally.
- `chrono similar --cwd PATH [--workspace-root PATH] [--limit N] [--db-path PATH]`
  prints the service JSON envelope and exits non-zero for a missing database or
  unknown project.
- `chrono_core_find_similar_projects` exposes the same envelope through MCP.

## Implementation Snapshot — 2026-09-01

Completed the reviewed GearCore promotion boundary (see
`docs/superpowers/specs/2026-09-01-gearcore-pattern-promotion-design.md`):

- `chrono patterns promotion-plan` validates an operator-authored `SKILL.md`
  bundle and matching UTF-8 before/after evidence, then returns the exact
  shell-free `gearcore add-skill` argv and its content digest without writing
  the database, the skill, or GearCore configuration.
- `chrono patterns promote` recomputes the plan and invokes GearCore only when
  the supplied digest is unchanged. It marks the pattern `promoted` only after
  registration succeeds; command failures retain `validated`, while an
  unexpected final status-write failure is reported as partial success.
- Skill prose and evidence are never passed as command arguments, persisted to
  Chrono, or echoed from provider stderr in the structured error envelope.
