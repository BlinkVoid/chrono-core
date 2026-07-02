# Continuity Core — Context

## Current Phase

Phase 2 MCP tool layer is implemented over the Phase 1 local core. The project has moved out of the Hub incubator incubator into its own workspace folder.

## What Landed

- Deterministic project IDs derived from workspace-relative path.
- `continuity_core.store.Store` SQLite persistence with schema initialization.
- `continuity handoff` persists projects, sessions, decisions, blockers, next actions, and observations.
  - Backwards-compatible `--summary`.
  - Optional JSON payload via `--json PATH` (`-` for stdin).
  - Structured CLI args: `--file`, `--test`, `--decision`, `--blocker`, `--next-action`, `--risk`.
- `continuity resume` reads the database and prints the latest session summary, open blockers, next actions, and recent decisions.
- Git branch/head/dirty state captured when available.
- MCP server (`continuity-mcp`) exposing `resolve_project`, `session_handoff`, and `get_resume_context` tools backed by the same Store/resolver/capture paths as the CLI.
- Focused unit tests covering resolver, store, handoff, resume, and MCP tool handlers.

## Project Location

- Project root: `~/workspace/continuity-core`
- Intended scope: `~/workspace`
- Default database: `~/.local/share/continuity-core/continuity.db`

## Related Existing Projects

### `~/workspace/project-tracking`

Old placeholder. It points to `tool-project-tracker` as canonical.

### `~/workspace/tool-project-tracker`

Current `workspace-intelligence` package. It already implements project discovery, SQLite registry, git state tracking, markdown export, MCP tools, and GearCore skill packaging. Missing richer continuity entities such as milestones, next actions, blockers, decisions, and review history.

### `~/workspace/_MetaFactory`

Cross-project knowledge distillery. It collects project docs and skills into snapshots, then uses AI prompts to consolidate patterns. Strong for reusable knowledge extraction, weaker as live operational project state.

## Design Direction

Continuity Core should integrate with the existing pieces first and supersede them later only if boundaries become artificial.

Current preferred split:

- `workspace-intelligence`: upstream project registry/discovery source.
- `_MetaFactory`: upstream reusable pattern/distillation source.
- `continuity-core`: operational continuity graph and management workflows.

## Immediate Next Work

1. Basic markdown export of resume context and project state.
2. Review existing `workspace-intelligence` schema/service implementation.
3. Review `_MetaFactory` latest consolidated outputs and collector patterns.
4. Decide whether Continuity Core should import from, wrap, or fork `workspace-intelligence`.
5. Add remaining standalone MCP tools for decisions/blockers and start Phase 3 management workflows.

## Packaging Decision

Continuity Core is a plugin-level capability. Personal use should flow through GearCore; public/open-source use should support standard package, CLI, plugin manifest, and MCP server installation.

GearCore does not currently appear to provide hard workflow hooks, so the MVP should rely on a core skill that recognizes user phrases such as `handoff`, `wrap up`, and `park this`, then runs Continuity Core handoff behavior explicitly.

## Implementation Snapshot — 2026-06-28

Implemented the MCP tool layer over the Phase 1 local core:

- `continuity_core.mcp_server` registers `resolve_project`, `session_handoff`, and `get_resume_context` tools via FastMCP.
- Tool handlers reuse the canonical `Store`, `capture/handoff`, `resume`, and `workspace.resolver` code paths.
- `continuity-mcp` entry point is wired in `pyproject.toml` and referenced by `.mcp.json` and `.codex-plugin/plugin.json`.
- Added focused unit tests for pure MCP tool handlers that exercise the handlers directly without a live MCP client process.

Canonical implementation path remains unchanged:

- `capture/handoff.py` builds and persists handoff payloads.
- `store/store.py` owns SQLite persistence.
- `resume.py` formats DB-backed resume context.
- `cli.py` and `mcp_server.py` are thin adapters over those modules.
