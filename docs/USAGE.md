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

Reviewed pattern promotion validates an authored skill bundle and recorded
before/after evidence before showing the exact mutation command:

```bash
chrono patterns promotion-plan PATTERN_ID \
  --skill-path skills/example --evidence evidence.json
chrono patterns promote PATTERN_ID \
  --skill-path skills/example --evidence evidence.json \
  --plan-digest PLAN_DIGEST
```

Plans are read-only. Apply requires the unchanged digest; `--scope project`
also requires an existing `--project-root`, and `--copy` omits the default
symlink registration flag. GearCore failures leave the local pattern validated.

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
`list [--status] [--severity]`, `show <id>`, `update <id> [--status] [--severity]`,
and `push <id> [--repo [HOST/]OWNER/REPO] [--dry-run]`. Push uses the
authenticated `gh api` bridge, infers a project repository from Git `origin`,
requires `--repo` for workspace-wide bugs, and records the remote issue link so
later pushes update the same issue. GitHub Enterprise hosts are supported.

Project catalog (`chrono project ...`) manages canonical metadata for
registered projects. Selectors resolve by exact project id, then exact
absolute path, then exact workspace-relative path; an ambiguous relative path
is a structured error:

```bash
chrono project list [--status STATUS] [--tag TAG] [--limit N] [--dirty | --no-dirty]
chrono project refresh PROJECT

# Persisted workspace inventory refresh (Git state + missing reconciliation)
chrono discover --workspace-root ~/workspace
# Read-only traversal; no database or Git subprocesses
chrono discover --workspace-root ~/workspace --no-persist
chrono project show PROJECT
chrono project update PROJECT [--status S] [--lifecycle-phase P] [--priority PRI] \
  [--tag TAG ...] [--owner O] [--description-usage D] [--summary S] \
  [--notes N] [--other-factors '{"k": "v"}']
chrono project progress PROJECT "Current status in one line"
```

`--tag` is repeatable on update and replaces the whole tag set.
`--other-factors` accepts one JSON object string. Supported statuses are
`active`, `paused`, `missing`, and `archived`; lifecycle phase and priority use the
workspace-intelligence enumerations. Operational `phase` is maintained by
Chrono distillation and is read-only to this command. Updates reject invalid values, malformed
JSON, and empty updates, printing the structured error envelope and exiting
non-zero. Every command prints the shared JSON service envelope.

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
