# Chrono Core — Context

## Current Phase

Phase 3 management session workflows are complete over the Phase 1 local core and Phase 2 agent interface. The project has moved out of the Hub incubator incubator into its own workspace folder. Phase 4 cross-project intelligence is the next focus.

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

1. Start Phase 4: design the reusable pattern index.
2. Add a MetaFactory ingestion adapter for consolidated pattern snapshots.
3. Add project similarity search over captured observations and distilled state.
4. Surface pattern recommendations in resume context.
5. Promote validated patterns into GearCore skills once recommendations are proven useful.

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
