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
