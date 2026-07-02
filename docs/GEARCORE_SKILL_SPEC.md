# GearCore Skill Spec

## Skill Name

`continuity-core`

## Purpose

Make Continuity Core available as a lightweight project-work ritual across AI CLI tools.

The skill should help agents know when to load project continuity context and when to save a session handoff.

## Initial SKILL.md Draft

```markdown
---
name: continuity-core
description: Project continuity, session handoff, resume context, and documentation management for workspace projects.
---

# Continuity Core

Use this skill when working on a software/project repository where continuity across sessions matters.

## When To Use

Use Continuity Core when the user asks to:

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
continuity resume --cwd "$PWD"
```

Use the returned context to understand project status, blockers, decisions, and next actions.

## Handoff

When the user says `handoff` or equivalent, prepare a concise structured handoff and run:

```bash
continuity handoff --cwd "$PWD"
```

Include:

- summary of work completed
- files changed
- tests/verification run
- decisions made
- blockers found or resolved
- next actions
- risks or uncertainties

If the CLI is not implemented yet, write the handoff in the response using the Continuity Core handoff schema and note that persistence is pending.

## Management Pass

Only run a deeper management pass when explicitly asked. Management includes distillation, stale-doc detection, improvement advice, and wiki updates.
```

## Notes

The first implementation can ship this skill before all commands exist. The skill should be honest about unavailable persistence and fall back to producing structured handoff text.
