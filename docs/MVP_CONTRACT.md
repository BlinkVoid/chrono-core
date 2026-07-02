# MVP CLI and MCP Contract

## Scope

This is the first executable contract. It favors low-friction session handoff and project resume over full project-management features.

## CLI Commands

### `continuity resolve`

Resolve the current project from a path.

```bash
continuity resolve --cwd ~/workspace/projects/example-agent
```

Output shape:

```json
{
  "name": "example-agent",
  "path": "~/workspace/projects/example-agent",
  "relative_path": "projects/example-agent",
  "marker": ".git",
  "known": false
}
```

### `continuity handoff`

Capture a session handoff.

```bash
continuity handoff --cwd . --summary "Updated Discord bot setup docs."
```

MVP persistence fields:

- project
- session summary
- raw payload
- git branch/head/dirty state
- decisions
- blockers
- next actions
- tests/verification
- touched files

### `continuity resume`

Return a compact resume context.

```bash
continuity resume --cwd .
```

Output tiers:

1. Project identity.
2. Current status.
3. Recent session summary.
4. Active blockers.
5. Next actions.
6. Key decisions.
7. Docs to read first.
8. Stale-doc warnings.

### `continuity ingest-existing-tools`

Import project metadata from the Workspace Intelligence SQLite registry and archive the legacy `project-tracking` directory as source evidence.

```bash
continuity ingest-existing-tools \
  --registry-path ~/workspace/tool-project-tracker/data/registry.db \
  --workspace-root ~/workspace \
  --db-path data/continuity.db
```

Output shape:

```json
{
  "ok": true,
  "workspace_root": "~/workspace",
  "registry_path": "~/workspace/tool-project-tracker/data/registry.db",
  "sources": {
    "workspace-intelligence": {
      "ok": true,
      "source": "workspace-intelligence",
      "registry_path": "~/workspace/tool-project-tracker/data/registry.db",
      "workspace_root": "~/workspace",
      "imported_count": 1,
      "skipped_count": 0,
      "projects": [
        {
          "project_id": "tool-project-tracker-abc123",
          "source_project_id": "workspace-intelligence-id",
          "name": "tool-project-tracker",
          "relative_path": "tool-project-tracker"
        }
      ],
      "skipped": []
    },
    "project-tracking": {
      "ok": true,
      "source": "project-tracking",
      "registry_path": "~/workspace/project-tracking",
      "workspace_root": "~/workspace",
      "imported_count": 1,
      "skipped_count": 0,
      "projects": [
        {
          "project_id": "project-tracking-abc123",
          "source_project_id": "project-tracking",
          "name": "project-tracking",
          "relative_path": "project-tracking"
        }
      ],
      "skipped": []
    }
  },
  "imported_count": 2,
  "skipped_count": 0
}
```

### Future CLI Commands

- `continuity discover`
- `continuity distill`
- `continuity reconcile`
- `continuity health`
- `continuity export markdown`

## MCP Tools

### `continuity_core.resolve_project`

Input:

```json
{
  "cwd": "~/workspace/example",
  "workspace_root": "~/workspace"
}
```

Output: same as `continuity resolve`.

### `continuity_core.session_handoff`

Input:

```json
{
  "cwd": "~/workspace/example",
  "summary": "Implemented provider settings.",
  "files_changed": ["src/config.py", "tests/test_config.py"],
  "tests": ["uv run pytest -q: passed"],
  "decisions": [
    {
      "title": "Use provider-neutral LLM boundary",
      "rationale": "Keeps provider swaps local to the LLM layer."
    }
  ],
  "blockers": [
    {
      "title": "Live smoke requires credentials",
      "status": "open"
    }
  ],
  "next_actions": ["Run live smoke", "Update runbook"],
  "risks": ["Credential path is not validated"]
}
```

Output:

```json
{
  "ok": true,
  "project_id": "example-abc12345",
  "session_id": "sess_...",
  "resume_hint": "Live smoke remains blocked on credentials. Next: update runbook."
}
```

### `continuity_core.get_resume_context`

Input:

```json
{
  "cwd": "~/workspace/example",
  "max_tokens": 2000
}
```

Output:

```json
{
  "project": {"name": "example", "path": "~/workspace/example"},
  "summary": "One paragraph project state.",
  "current_status": "Phase 2, blocked on live smoke credentials.",
  "active_blockers": [],
  "next_actions": [],
  "recent_decisions": [],
  "docs_to_read": [],
  "warnings": []
}
```

### Management Tools

Not MVP persistence-critical, but contract names are reserved:

- `continuity_core.distill_project`
- `continuity_core.reconcile_docs`
- `continuity_core.review_project_health`
- `continuity_core.find_reusable_patterns`
