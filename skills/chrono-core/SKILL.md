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
- find related projects
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

When a reusable lesson or candidate mechanism is established, capture it
explicitly with `chrono observe "<evidence>" --kind lesson --cwd "$PWD"` (or
`--kind pattern_candidate`). This constrained path is eligible for safe
cross-project pattern mining; ordinary decisions and operational handoff data
are not.

## Health Check

Use `chrono doctor` for a concise read-only database audit, or `chrono doctor
--json` for structured findings. Warnings identify reviewable ambiguity; a
non-zero exit indicates integrity, ownership, legacy residue, or provenance
failures. Doctor never repairs or creates a database.

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
- `chrono_core_record_observation` — persist an explicitly semantic lesson or pattern candidate for safe mining.
- `chrono_core_record_blocker` — persist a blocker outside a handoff.
- `chrono_core_resolve_blocker` — mark an open blocker resolved by id.
- `chrono_core_complete_action` — mark an open next action done by id.
- `chrono_core_distill_project` — derive and persist compact project state from captured records.
- `chrono_core_search_observations` — full-text search captured observations across projects.
- `chrono_core_find_similar_projects` — rank other managed projects by shared distilled evidence and observations.
- `chrono_core_push_bug_to_github` — explicitly create or update one GitHub issue from a local bug; this mutates an external repository, while `dry_run` only returns the plan.
- `chrono_core_review_project` — run doc reconciliation, health review, advice, and review queue generation.
- `chrono_core_discover_projects` — persist a bounded workspace scan with current Git inventory and missing reconciliation.
- `chrono_core_refresh_project` — refresh one registered project's current Git inventory.
- `chrono_core_list_projects` accepts optional `dirty=true|false` for current inventory filtering.

All tools accept `workspace_root` and `db_path` overrides. Prefer the defaults unless the project is outside `~/workspace` or the database location must change.

## Cross-Project Similarity

When the user asks which other projects contain related work or knowledge, run:

```bash
chrono similar --cwd "$PWD"
```

Or call `chrono_core_find_similar_projects` with `cwd`. Results are read-only
and explainable: each match carries a rounded similarity score and
`shared_terms` naming the evidence that connected the two projects. A missing
database or unregistered project returns a structured error without side
effects.

## Reviewed Pattern Promotion

When an operator has already authored a tested GearCore skill bundle and
sanitized matching before/after evidence, preview the exact registration first:

```bash
chrono patterns promotion-plan PATTERN_ID --skill-path PATH --evidence PATH
```

This is read-only. To apply the reviewed plan, require its exact digest:

```bash
chrono patterns promote PATTERN_ID --skill-path PATH --evidence PATH \
  --plan-digest PLAN_DIGEST
```

The skill bundle is never generated or rewritten by Chrono. Registration is
symlinked by default (`--copy` opts out); project scope additionally requires
an existing `--project-root`. A stale plan, failure, or timeout leaves the
pattern validated. This workflow is CLI-only; do not infer an MCP tool for it.

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
