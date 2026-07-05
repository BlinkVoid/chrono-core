# Continuity Core Usage

These are the default session patterns for AI CLI tools working in a project under `~/workspace`.

## Codex

At session start:

```bash
continuity resume --cwd "$PWD"
```

At handoff:

```bash
continuity handoff --cwd "$PWD" --summary "One-sentence session summary."
```

If GearCore is available, load the `continuity-core` skill first so the tool use is explicit:

```bash
gearcore request-skill continuity-core
```

## Claude

At session start:

```bash
continuity resume --cwd "$PWD"
```

At handoff:

```bash
continuity handoff --cwd "$PWD" --summary "One-sentence session summary."
```

If the MCP server is connected, use:

- `continuity_core.get_resume_context`
- `continuity_core.session_handoff`

## Kimi

At session start:

```bash
continuity resume --cwd "$PWD"
```

At handoff:

```bash
continuity handoff --cwd "$PWD" --summary "One-sentence session summary."
```

If the GearCore hub is available, use:

```bash
gearcore request-skill continuity-core
```

## Shared Rules

- Resolve the project before capturing state.
- Include summary, files changed, tests, decisions, blockers, next actions, and risks in the handoff.
- Prefer structured records over free-form notes when the tool is available.
- Reserve deeper management workflows for dedicated review sessions.
