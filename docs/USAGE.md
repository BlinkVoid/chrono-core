# Chrono Core Usage

These are the default session patterns for AI CLI tools working in a project under `~/workspace`.

## Codex

At session start:

```bash
chrono resume --cwd "$PWD"
```

At handoff:

```bash
chrono handoff --cwd "$PWD" --summary "One-sentence session summary."
```

If GearCore is available, load the `chrono-core` skill first so the tool use is explicit:

```bash
gearcore request-skill chrono-core
```

## Claude

At session start:

```bash
chrono resume --cwd "$PWD"
```

At handoff:

```bash
chrono handoff --cwd "$PWD" --summary "One-sentence session summary."
```

If the MCP server is connected, use:

- `chrono_core_get_resume_context`
- `chrono_core_session_handoff`
- `chrono_core_review_project`

## Kimi

At session start:

```bash
chrono resume --cwd "$PWD"
```

At handoff:

```bash
chrono handoff --cwd "$PWD" --summary "One-sentence session summary."
```

If the GearCore hub is available, use:

```bash
gearcore request-skill chrono-core
```

## Shared Rules

- Resolve the project before capturing state.
- Include summary, files changed, tests, decisions, blockers, next actions, and risks in the handoff.
- Prefer structured records over free-form notes when the tool is available.
- Close finished work: `chrono blocker resolve <id>` and `chrono action complete <id>` keep resume context and the distilled phase truthful.
- Reserve deeper management workflows for dedicated review sessions. Use `chrono review --cwd "$PWD"` for doc reconciliation, health review, improvement advice, and review queue output.

## Lifecycle Verbs

Resume context is workstream-scoped by default (the current git branch):

```bash
chrono resume --cwd "$PWD"                 # current branch only
chrono resume --all                        # every branch
chrono resume --branch feat/x              # explicit branch override
chrono resume --limit 50                   # cap open items per category
```

Next-action lifecycle (`chrono action ...`): `complete`, `cancel <id> [--reason]`,
`edit <id> <text>`, `reopen <id>`, `supersede <old-id> <new-text>` (creates a
replacement action linked via `supersedes_id`; cancelling a superseded action
is rejected).

Blocker lifecycle (`chrono blocker ...`): `resolve`, `cancel <id>`,
`edit <id> <title>`, `reopen <id>`.

Bug tracking (`chrono bug ...`): `report --cwd "$PWD" <title> [--severity S]`,
`list [--status] [--severity]`, `show <id>`, `update <id> [--status] [--severity]`.

Capture reusable semantic evidence explicitly; arbitrary operational kinds are
rejected so they cannot contaminate pattern mining:

```bash
chrono observe "Bound retries with an explicit budget" --kind lesson --cwd "$PWD"
chrono observe "Single client boundary for provider calls" \
  --kind pattern_candidate --cwd "$PWD"
```

Audit the database without modifying it. Warnings do not fail the command;
integrity, foreign-key, ownership, legacy residue, or unsafe mined-pattern
failures return exit code 1:

```bash
chrono doctor
chrono doctor --json
```

Search covers observations and bug text in one envelope:

```bash
chrono search "parser"                     # results + bugs keys, counts for each
```

The same verbs are exposed over MCP via the `chrono_core_*` tools listed in
`docs/MVP_CONTRACT.md`.
