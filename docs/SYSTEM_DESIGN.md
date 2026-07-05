# System Design

## Positioning

Continuity Core sits above existing workspace tooling.

- `workspace-intelligence` tracks project inventory, git state, and lightweight metadata.
- `_MetaFactory` collects and consolidates cross-project knowledge snapshots.
- Continuity Core coordinates operational memory: sessions, decisions, blockers, next actions, docs, and reusable patterns.

The first implementation should integrate with those systems where practical, then decide later whether to supersede parts of them.

## Architecture

```text
AI Agent / Human
      |
      v
MCP tools + CLI
      |
      v
Continuity service layer
      |
      +-- Project resolver / workspace traversal
      +-- Session capture
      +-- Management distillation
      +-- Documentation reconciliation
      +-- Resume-context generator
      +-- Pattern/reuse lookup
      |
      v
Local canonical store
      |
      +-- SQLite tables
      +-- FTS indexes
      +-- graph-shaped edge table
      |
      v
Derived views
      +-- project wiki markdown
      +-- session handoff markdown
      +-- dashboard/API later
```

## Storage Choice

Start with SQLite, not a dedicated graph database.

Reasons:

- local-first and simple to operate
- easy backups and migrations
- supports relational integrity
- supports FTS for document search
- can represent graph relationships through an `edges` table

A later graph engine such as Kuzu or Neo4j can be added if traversal queries become central enough to justify the operational cost.


## Plugin-Level Packaging

Continuity Core is a plugin-level capability. MCP is one runtime interface, not the whole product.

The package should expose:

- core Python library
- SQLite store and migrations
- workspace traversal/resolution
- CLI
- MCP server
- GearCore skill adapter
- public plugin manifests
- markdown/wiki export templates

GearCore is the personal workspace distribution layer. Public users should be able to install and run Continuity Core through standard package/plugin/MCP paths without GearCore.

## Primary Interfaces

### MCP First

AI agents are the primary users. The MCP server should expose:

- `continuity_core_resolve_project`
- `continuity_core_session_handoff`
- `continuity_core_get_resume_context`
- `continuity_core_record_decision`
- `continuity_core_record_blocker`
- `continuity_core_distill_project`
- `continuity_core_reconcile_docs`
- `continuity_core_review_project_health`
- `continuity_core_find_reusable_patterns`

### CLI Second

The CLI should support diagnostics and manual use:

- `continuity discover`
- `continuity status <project>`
- `continuity handoff <project>`
- `continuity resume <project>`
- `continuity distill <project>`
- `continuity reconcile <project>`
- `continuity doctor`

### Dashboard Later

A web UI can come after the schema and workflows stabilize.

## Project Resolution

An AI working inside any project should be able to call handoff directly.

Resolution algorithm:

1. Accept explicit `cwd`, path, or project id.
2. Walk upward from `cwd` looking for markers:
   - `.git` directory or file
   - `hive.project.json`
   - `pyproject.toml`
   - `package.json`
   - `Cargo.toml`
   - `go.mod`
   - `README.md`
3. Normalize against `~/workspace`.
4. If project is known, attach the session to it.
5. If unknown, create a provisional project record.
6. Capture current git branch, head, dirty state, and relevant manifest fields.

## Capture vs Management

Continuity Core separates two modes.

### Project Agent Capture

Fast, low-friction, every session:

- summary
- files changed
- tests run
- decisions made
- blockers found/resolved
- next actions
- risks/confidence

### Management Session

Deeper periodic maintenance:

- distill many sessions into current project state
- reconcile scattered docs
- identify stale or contradictory documentation
- generate improvement advice
- link decisions/tasks/specs/files
- find reusable cross-project patterns
- update wiki exports

## Documentation Policy

Continuity Core should enforce: if it is not documented, it did not happen.

That does not mean every project agent must write perfect docs. It means every session must leave structured evidence, and management sessions must convert evidence into durable project documentation.
