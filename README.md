# Chrono Core

Local-first project memory for humans and AI agents working across many projects in parallel.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Code style](https://img.shields.io/badge/code_style-ruff-261230)

## Why

AI agents and humans lose continuity when project state is scattered across TODO files, plans, specs, READMEs, chat sessions, issue notes, and partially updated documentation. After a project pauses for weeks, it becomes hard to answer: what happened last, what is blocked, what should happen next, which decisions still matter, and which docs are stale or contradictory?

Chrono Core treats project state as something that must be explicitly captured, distilled, reconciled, and queryable — a local SQLite-backed continuity layer that any agent can call from any project without setup.

## Quick start

Installation (PyPI publication is pending; for now install from a checkout):

```bash
# once published:
uv tool install chrono-core

# today, from a clone of this repository:
uv pip install -e .
```

Capture a session handoff from inside any project:

```bash
chrono handoff \
  --summary "Implemented JWT token refresh; tests green on the new endpoint." \
  --file src/auth/tokens.py \
  --test "pytest tests/test_tokens.py" \
  --decision "Use short-lived access tokens with rotating refresh tokens" \
  --blocker "Staging Redis credentials not provisioned yet" \
  --next "Wire refresh endpoint into the client SDK"
```

```json
{
  "ok": true,
  "project_id": "demo-app-52926082b7",
  "session_id": "sess_f0866f0ed0064f278b6cb749b11c6c92",
  "resume_hint": "Implemented JWT token refresh; tests green on the new endpoint."
}
```

Later — even weeks afterwards, from the same project — resume with the right context. Resume output is branch-scoped: it shows only what is open on your current workstream:

```text
$ chrono resume
Project: demo-app
Path: /tmp/opencode/demo-app
Status: Latest session on spike/queue-backend.
Latest session: Spiked Redis Streams vs SQS; leaning Redis Streams.

Open blockers (spike/queue-backend):
  (+1 more on other branches: --all to show)

Next actions (spike/queue-backend):
  - [act_dbd199039c1c49a1] Write spike findings into docs/queue-spike.md
  (+1 more on other branches: --all to show)

Recent decisions:
  - Use short-lived access tokens with rotating refresh tokens
```

Widen the lens when you need to:

```text
$ chrono resume --all

Open blockers (all branches):
  - [blk_e0b22d3fb441401f] Staging Redis credentials not provisioned yet

Next actions (all branches):
  - [act_dbd199039c1c49a1] Write spike findings into docs/queue-spike.md
  - [act_d26c9981e6ae43ab] Wire refresh endpoint into the client SDK
```

(Use `--branch <name>` to view another workstream and `--limit N` to cap open items per category.)

## Features

| Feature | What you get |
| --- | --- |
| Session handoff capture | `chrono handoff` records summary, files changed, tests run, decisions, blockers, next actions, risks, and git state via CLI flags or a JSON payload. |
| Branch-scoped resume | `chrono resume` surfaces only the current workstream's open items; `--all`, `--branch`, and `--limit` widen or trim the view. |
| Full lifecycle verbs | `chrono action complete/cancel/edit/reopen/supersede` and `chrono blocker resolve/cancel/edit/reopen` correct captured state instead of duplicating it. |
| Cross-project bug tracking | `chrono bug report/list/show/update` files and tracks bugs across every project in the workspace, exposed through MCP tools as well. The schema carries `remote_url` / `remote_issue_id` for future external sync. |
| Full-text search | `chrono search <query>` runs FTS5 queries over captured observations. |
| Markdown export | `chrono export markdown` writes a derived project index, per-project pages, and a top-level `ReviewQueue.md`. |
| Distill & review heuristics | `chrono distill` compacts sessions into current state; `chrono review` runs deterministic doc reconciliation, stale/contradictory-doc detection, health scoring (including bug pressure), improvement advice, and a review queue. These are deterministic heuristics, not semantic/AI reconciliation. |
| MCP server | `chrono-mcp` exposes 20 tools (resolve, handoff, resume, decisions/blockers/actions lifecycle, search, bugs, distill, review) backed by the same store and code paths as the CLI. |
| GearCore adapter | `chrono gearcore install-plan` prints registration commands for the GearCore skill and MCP server; Chrono Core works fine without GearCore. |

## Architecture

```text
AI Agent / Human
      |
      v
MCP tools + CLI          (chrono-mcp: 20 tools · chrono: 13 command groups)
      |
      v
Chrono Core service layer
      +-- Project resolver / workspace traversal
      +-- Session capture
      +-- Management distillation
      +-- Documentation reconciliation
      +-- Resume-context generator
      |
      v
Store (canonical local state)
      +-- SQLite tables (WAL mode)
      +-- FTS indexes
      +-- graph-shaped edge table
      |
      v
Derived views
      +-- project wiki markdown
      +-- ReviewQueue.md
```

The database is canonical; markdown exports are readable views. See [System Design](docs/SYSTEM_DESIGN.md) for the full picture.

## Documentation

| Document | Contents |
| --- | --- |
| [Project Brief](PROJECT_BRIEF.md) | Mission, scope, principles |
| [System Design](docs/SYSTEM_DESIGN.md) | Architecture, storage choice, resolution algorithm |
| [Data Model](docs/DATA_MODEL.md) | Entities and graph shape |
| [SQLite Schema](docs/SQLITE_SCHEMA.md) | Tables, identity model, migrations |
| [Management Workflows](docs/MANAGEMENT_WORKFLOWS.md) | Distillation and review workflows |
| [Usage](docs/USAGE.md) | CLI and MCP usage details |
| [MVP CLI and MCP Contract](docs/MVP_CONTRACT.md) | Interface contract |
| [Plugin Strategy](docs/PLUGIN_STRATEGY.md) | Packaging as a plugin-level capability |
| [GearCore Skill Spec](docs/GEARCORE_SKILL_SPEC.md) | GearCore adapter design |
| [Integration and Supersession Plan](docs/INTEGRATION_SUPERSESSION.md) | Relationship to workspace-intelligence and _MetaFactory |
| [Doc Consolidation Playbook](docs/DOC_CONSOLIDATION_PLAYBOOK.md) | How docs are consolidated |
| [Roadmap](docs/ROADMAP.md) | Phases and status |
| [Project Context](docs/CONTEXT.md) | Current phase and implementation snapshots |

## Roadmap

- **Phase 4 — cross-project intelligence:** reusable pattern index, MetaFactory ingestion, project similarity search, and pattern recommendations surfaced in resume context.
- **External bug sync:** a one-way GitHub bug dump/sync adapter. The bugs table already carries `remote_url` and `remote_issue_id` columns in anticipation.

## License

[MIT](LICENSE)
