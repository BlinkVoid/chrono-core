# Plugin Strategy

## Decision

Continuity Core is a plugin-level capability, not just an MCP server.

MCP is one runtime interface. The product should package a core library, local store, CLI, MCP tools, GearCore skill/instructions, plugin manifests, and export templates as one coherent capability.

## Distribution Modes

### Personal Workspace Mode

Personal mode is optimized for `~/workspace` and AI agents launched through GearCore.

Goals:

- make Continuity Core available across Codex, Claude, Kimi, and future AI CLIs
- use GearCore as the cross-tool distribution and progressive-disclosure layer
- support workspace traversal over `~/workspace`
- integrate with local Incubator, `workspace-intelligence`, and `_MetaFactory`
- keep private project state in a local database

GearCore should be an adapter and distribution mechanism, not a core dependency.

### Public Plugin Mode

Public mode is the later open-source route.

Goals:

- standard installable package
- portable config with no hardcoded Incubator assumptions
- MCP server for compatible clients
- CLI for manual workflows
- optional plugin manifests for clients that support plugin packages
- safe defaults for private local state

## Package Shape

```text
continuity-core/
  pyproject.toml
  README.md
  .mcp.json
  .codex-plugin/plugin.json
  skills/
    continuity-core/SKILL.md
  src/continuity_core/
    domain/
    store/
    workspace/
    capture/
    management/
    export/
    integrations/
      gearcore.py
      workspace_intelligence.py
      metafactory.py
    cli.py
    mcp_server.py
```

## GearCore Role

GearCore provides:

- skill discovery
- project scoping
- progressive disclosure
- core-skill auto-activation
- cross-client sync

GearCore does not currently appear to provide true workflow hooks such as `on_session_end` or `on_project_start`. Continuity Core should therefore rely on skill instructions and explicit commands for MVP.

## Handoff Trigger Behavior

A GearCore skill should teach agents to treat these user phrases as continuity triggers:

- `handoff`
- `session handoff`
- `wrap up`
- `park this`
- `save state`
- `resume later`
- `what should the next session know?`

When triggered inside a project, the agent should:

1. Resolve the current project from `cwd`.
2. Inspect relevant git/test/doc state if needed.
3. Build a structured handoff.
4. Save it through Continuity Core.
5. Return a compact human-readable summary.

## Core Skill Strategy

For personal use, once stable, Continuity Core can be configured as a GearCore core skill.

Global example:

```yaml
version: 2

disclosure:
  core_skills:
    - continuity-core
```

Project example:

```yaml
version: 2

context:
  name: "Example Project"

scope:
  skills:
    include:
      - continuity-core

disclosure:
  core_skills:
    - continuity-core
```

The skill should not force a full management pass on every session. It should make low-friction capture easy and reserve distillation/reconciliation for dedicated management sessions.

## GearCore Adapter Command

The MVP adapter does not mutate GearCore config directly. It emits an explicit installation plan:

```bash
continuity gearcore install-plan
```

For project-scoped registration:

```bash
continuity gearcore install-plan --scope project --project-root /path/to/project
```

The plan includes one `gearcore add-skill` command for `skills/continuity-core` and one `gearcore add-mcp` command for `continuity-mcp`.

## Future Hook Support

If GearCore later adds hooks, Continuity Core could support:

```yaml
hooks:
  on_project_start:
    - continuity resume --cwd .
  on_session_end:
    - continuity handoff --cwd .
```

Do not make MVP depend on hooks because AI client lifecycle events are inconsistent across tools.
