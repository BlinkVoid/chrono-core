# Chrono Core — Project Brief

## Mission

Build a local-first continuity layer that helps humans and AI agents maintain coherent project memory across the whole workspace.

The system should make it cheap for any agent to record what happened, easy for a management session to distill that into durable project state, and reliable for future sessions to resume work with the right context.

## Scope

Chrono Core is not a Incubator-only tool. Incubator hosts the incubator, but the product operates over `~/workspace` and should eventually become a standalone package, MCP server, and GearCore-compatible capability.

## Users

- Human operator managing many active and paused projects.
- AI coding agents working inside individual projects.
- AI management/review sessions that reconcile, distill, and improve project state.

## Non-Negotiable Principles

1. **If it is not documented, it did not happen.** Session work must land in structured continuity records.
2. **Low-friction capture first.** A project agent must be able to call session handoff directly from any project without setup.
3. **Facts before synthesis.** Working agents capture facts; management sessions distill and reconcile them.
4. **Database canonical, markdown useful.** The database is the source of truth; wiki/markdown exports are readable views with import/reconciliation support.
5. **Workspace traversal is core.** Project resolution and discovery must start at the workspace level from day one.
6. **Supersede by integration first.** Existing tools such as `workspace-intelligence` and `_MetaFactory` should be integrated before being absorbed or replaced.

## Initial Deliverable

A working local-first continuity prototype with:

- deterministic project resolver and registry import from `workspace-intelligence`
- SQLite-backed `Store` for projects, sessions, decisions, blockers, next actions, observations, and edges
- `chrono` CLI for resolve, handoff, resume, and workspace-intelligence ingestion
- MCP server exposing `resolve_project`, `session_handoff`, and `get_resume_context`
- distillation/management workflow design
- graph-shaped data model
- MCP/GearCore integration path
- migration/supersession plan for existing project-tracking and knowledge-distillation tools
