---
name: chrono-core
description: Project continuity, session handoff, resume context, and documentation management for workspace projects.
---

# Chrono Core

Use this skill when working on a software/project repository where continuity across sessions matters.

## When To Use

Use Chrono Core when the user asks to:

- handoff
- wrap up
- park the work
- save state
- resume a project
- explain current project status
- find next actions
- reconcile project docs
- run a management/distillation pass

For non-trivial project work, prefer loading a resume context before making changes.

## Session Start

If starting or resuming project work, run:

```bash
chrono resume --cwd "$PWD"
```

Or, when using the MCP server, call `chrono_core_get_resume_context` with `cwd`.

Use the returned context to understand project status, blockers, decisions, and next actions.

When a blocker is no longer real or a next action is finished, close it so resume context stays accurate — `chrono blocker resolve <id>` / `chrono action complete <id>` (or the matching MCP tools). Ids appear in resume output.

## Handoff

When the user says `handoff` or equivalent, prepare a concise structured handoff and run:

```bash
chrono handoff --cwd "$PWD" --summary "<one sentence summary>"
```

Or call `chrono_core_session_handoff` with `cwd`, `summary`, and optional structured fields (`files_changed`, `tests`, `decisions`, `blockers`, `next_actions`, `risks`).

Include summary, files changed, verification, decisions, blockers, next actions, and risks.

## MCP Tools

When Chrono Core is installed as an MCP server (`chrono-mcp`), the following tools are available:

- `chrono_core_resolve_project` — identify the project for a given `cwd`.
- `chrono_core_session_handoff` — persist a structured handoff.
- `chrono_core_get_resume_context` — fetch compact resume context.
- `chrono_core_record_decision` — persist a project decision outside a handoff.
- `chrono_core_record_blocker` — persist a blocker outside a handoff.
- `chrono_core_resolve_blocker` — mark an open blocker resolved by id.
- `chrono_core_complete_action` — mark an open next action done by id.
- `chrono_core_distill_project` — derive and persist compact project state from captured records.
- `chrono_core_search_observations` — full-text search captured observations across projects.
- `chrono_core_review_project` — run doc reconciliation, health review, advice, and review queue generation.

All tools accept `workspace_root` and `db_path` overrides. Prefer the defaults unless the project is outside `~/workspace` or the database location must change.

## Management Pass

Only run a deeper management pass when explicitly asked. Management includes distillation, stale-doc detection, improvement advice, and wiki updates.

For compact state distillation, run:

```bash
chrono distill --cwd "$PWD"
```

For the full deterministic management review, run:

```bash
chrono review --cwd "$PWD"
```

## GearCore Registration

To expose Chrono Core through GearCore, run:

```bash
chrono gearcore install-plan
```

Review the emitted commands, then run them to register the skill and MCP server. Use `--scope project --project-root <path>` for project-scoped registration.
