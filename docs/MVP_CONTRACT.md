# MVP CLI and MCP Contract

## Scope

This is the first executable contract. It favors low-friction session handoff and project resume over full project-management features.

## CLI Commands

All commands read and write the continuity database at
`~/.local/share/chrono-core/chrono.db` by default. This is the single
canonical location shared by the CLI and the MCP server, so handoffs captured
through one surface are visible from the other. Pass `--db-path` (CLI) or
`db_path` (MCP) to override it.

The workspace root defaults to `~/workspace`; set the
`CHRONO_WORKSPACE_ROOT` environment variable (or pass
`--workspace-root` / `workspace_root`) to override it.

### `chrono resolve`

Resolve the current project from a path.

```bash
chrono resolve --cwd ~/workspace/projects/example-agent
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

### `chrono handoff`

Capture a session handoff.

```bash
chrono handoff --cwd . --summary "Updated Discord bot setup docs."
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

### `chrono resume`

Return a compact resume context.

```bash
chrono resume --cwd .
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

### `chrono distill`

Derive compact project state from captured sessions, blockers, next actions, and decisions.

```bash
chrono distill --cwd .
```

Output shape:

```json
{
  "ok": true,
  "project_id": "example-abc123",
  "project_name": "example",
  "phase": "blocked",
  "summary": "Implemented management state capture.",
  "current_status": "Latest session on main.",
  "active_blocker_count": 1,
  "next_action_count": 1,
  "recent_decision_count": 1
}
```

### `chrono blocker resolve` / `chrono action complete`

Close captured records so resume context and distilled phase stay accurate.
Blocker and next-action ids appear in `chrono resume` output.

```bash
chrono blocker resolve blk_1a2b3c4d5e6f7a8b
chrono action complete act_1a2b3c4d5e6f7a8b
```

Output shape:

```json
{
  "ok": true,
  "blocker_id": "blk_1a2b3c4d5e6f7a8b",
  "status": "resolved"
}
```

Unknown ids return `"ok": false`, `"status": "not_found"`, and exit code 1.

### `chrono observe`

Capture project-scoped semantic evidence outside a handoff. The kind is
restricted to `lesson`, `pattern`, or `pattern_candidate`; file, test, risk,
git, and importer metadata cannot enter through this command.

```bash
chrono observe "Bound retries with an explicit budget" --kind lesson --cwd .
```

The default kind is `lesson`. Successful output contains `project_id`,
`recorded_count: 1`, and the stored observation (including its `obs_` id and
`source: "direct"`). Blank content or an unsupported kind returns
`{"ok": false, "error": ...}` and exit code 2 without creating a database.

### `chrono search`

Full-text search captured observations (changed files, tests, risks, imported
metadata) using SQLite FTS5 match syntax.

```bash
chrono search "credential" --limit 10
chrono search "deploy AND pipeline" --project-id example-abc123
```

Output shape:

```json
{
  "ok": true,
  "query": "credential",
  "count": 1,
  "results": [
    {
      "id": "obs_1a2b3c4d5e6f7a8b",
      "project_id": "example-abc123",
      "session_id": null,
      "kind": "risk",
      "content": "Credential rotation is unverified",
      "source": "handoff",
      "observed_at": "2026-07-05T00:00:00+00:00"
    }
  ]
}
```

### `chrono similar`

Rank other registered projects against the project at `--cwd` by shared
evidence. Each project document combines its distilled phase/summary with its
captured observation content; scoring is cosine similarity over
sublinear-TF/IDF term weights, so repeated evidence has diminishing returns and
terms present in every project contribute little. The query is read-only: an
unknown project or missing database is reported without registering anything.

```bash
chrono similar --cwd ~/workspace/example --limit 5
```

Output shape:

```json
{
  "ok": true,
  "project_id": "example-abc12345",
  "count": 1,
  "results": [
    {
      "project_id": "sibling-def67890",
      "project_name": "sibling",
      "project_path": "~/workspace/sibling",
      "phase": "active",
      "summary": "Hardening the SQLite export pipeline.",
      "score": 0.742381,
      "shared_terms": ["export", "pipeline", "sqlite"]
    }
  ]
}
```

Scores are rounded for a stable contract. Only positive-score matches are
returned, ordered by score descending then by project id, capped by `--limit`
(a zero or negative limit returns an empty set). Each result lists up to eight
`shared_terms`, ordered by their contribution to the score then
alphabetically. Missing databases and unknown projects return
`{"ok": false, "error": ...}` and exit code 1.

### `chrono project list` / `show` / `update` / `progress`

Manage canonical project catalog metadata (Stage 1 of the
workspace-intelligence absorption; see
`docs/superpowers/specs/2026-09-01-workspace-intelligence-absorption-design.md`):

```bash
chrono project list [--status STATUS] [--tag TAG] [--limit N] [--dirty | --no-dirty] [--db-path PATH]
chrono project show PROJECT [--db-path PATH]
chrono project update PROJECT [metadata options] [--db-path PATH]
chrono project progress PROJECT TEXT [--db-path PATH]
chrono project refresh PROJECT [--db-path PATH]
chrono discover --workspace-root ROOT [--max-depth N] [--include-provisional] [--no-persist]
```

`PROJECT` selectors resolve by exact id, then exact absolute path, then exact
workspace-relative path; an ambiguous relative path is a structured
`ambiguous_project` error. Records include `tags` (decoded JSON array of
unique strings) and `other_factors` (decoded JSON object). Updates accept
`--status` (`active|paused|missing|archived`), `--lifecycle-phase`
(`prototype|validation|commercialisation|maintenance|archived`), `--priority`
(`low|normal|high|critical`), repeatable `--tag` (replaces the tag set),
`--owner`, `--description-usage`, `--summary`, `--notes`, and one
`--other-factors` JSON object string. Empty updates, unknown fields, invalid
enums, and malformed JSON are rejected (`empty_update` / `invalid_input`
codes) before mutation. Updates stamp `updated_at` and return the refreshed
record. Reads are side-effect free: a missing database reports
`database_not_found` without creating it. A readable database on an older
schema returns `schema_upgrade_required`; reads never apply migrations.

Output shape (list):

```json
{
  "ok": true,
  "count": 1,
  "projects": [
    {
      "id": "alpha-abc12345",
      "name": "alpha",
      "path": "~/workspace/alpha",
      "relative_path": "alpha",
      "status": "paused",
      "phase": "active",
      "lifecycle_phase": "maintenance",
      "summary": "Hardening the SQLite export pipeline.",
      "priority": "high",
      "tags": ["infra"],
      "owner": "r345",
      "description_usage": null,
      "current_progress": "Catalog API wired.",
      "notes": null,
      "other_factors": {},
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

`show`, `update`, and `progress` return `{"ok": true, "project": {...}}` with
the same record; failures return `{"ok": false, "code": ..., "project": null}`.

### `chrono bug push`

Push one local bug to a GitHub issue through the authenticated `gh api` bridge:

```bash
chrono bug push BUG_ID [--repo [HOST/]OWNER/REPO] [--dry-run] [--db-path PATH]
```

Project bugs infer the destination from Git `origin`; workspace-wide bugs
require `--repo`. An existing `remote_url`/`remote_issue_id` link is updated and
cannot be relinked with a conflicting repository. Request JSON is passed via
stdin (`--input -`), and GitHub Enterprise hosts use `gh api --hostname HOST`.
`--dry-run` returns an inspectable plan without subprocess calls or database
writes. A successful create persists the link before any close-state PATCH, so
a retry converges on the same issue if that PATCH fails.

### `chrono ingest-existing-tools`

Import project metadata from the Workspace Intelligence SQLite registry and archive the legacy `project-tracking` directory as source evidence.

```bash
chrono ingest-existing-tools \
  --registry-path ~/.local/state/workspace-intelligence/registry.db \
  --workspace-root ~/workspace
```

Output shape:

```json
{
  "ok": true,
  "workspace_root": "~/workspace",
  "registry_path": "~/.local/state/workspace-intelligence/registry.db",
  "sources": {
    "workspace-intelligence": {
      "ok": true,
      "source": "workspace-intelligence",
      "registry_path": "~/.local/state/workspace-intelligence/registry.db",
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

### `chrono export markdown`

Write a derived Markdown project index and one resume-style project page per project.

```bash
chrono export markdown --output-dir exports/markdown
```

Output shape:

```json
{
  "ok": true,
  "output_dir": "exports/markdown",
  "index_path": "exports/markdown/Projects.md",
  "exported_count": 1,
  "projects": [
    {
      "project_id": "example-abc123",
      "name": "example",
      "path": "exports/markdown/projects/example-abc123.md",
      "relative_path": "projects/example-abc123.md"
    }
  ]
}
```

### `chrono gearcore install-plan`

Print explicit GearCore registration commands for the Chrono Core skill and MCP server without mutating GearCore config.

```bash
chrono gearcore install-plan
```

Output shape:

```json
{
  "ok": true,
  "scope": "global",
  "project_root": null,
  "skill_path": "~/workspace/chrono-core/skills/chrono-core",
  "symlink": true,
  "mcp_server": {
    "id": "chrono-core",
    "type": "stdio",
    "command": "chrono-mcp"
  },
  "commands": [
    {
      "description": "Register Chrono Core skill",
      "argv": ["gearcore", "add-skill", "--scope", "global", "--symlink", "..."],
      "shell": "gearcore add-skill --scope global --symlink ..."
    }
  ]
}
```

### `chrono review`

Run the Phase 3 management review for one project. The workflow distills captured records, reconciles Markdown docs against the roadmap phase, detects stale or contradictory phase claims, emits project health, generates improvement advice, and returns a review queue for wiki/export use.

```bash
chrono review --cwd ~/workspace/example
```

Output shape:

```json
{
  "ok": true,
  "project_id": "example-abc12345",
  "canonical_phase": "Phase 4",
  "health": {
    "status": "needs_review",
    "open_blockers": 0,
    "open_actions": 1,
    "stale_docs": 1,
    "contradictions": 1
  },
  "findings": [],
  "improvement_advice": [],
  "review_queue": []
}
```

### `chrono doctor`

Run a read-only health audit against an existing Chrono database:

```bash
chrono doctor
chrono doctor --json
```

Checks cover SQLite integrity, foreign keys, ambiguous project identities,
child/session ownership, the legacy workspace-root collision bucket, and
mined-pattern provenance. Each check reports `pass`, `warn`, or `fail`.
Warnings keep exit code 0; any failure returns exit code 1. A missing or
unreadable database is reported without creating or mutating it.

## MCP Tools

Tool names use underscores only (`chrono_core_<verb>`), never dots:
Anthropic's API constrains tool names to `^[a-zA-Z0-9_-]+$`, and clients that
pass MCP tool names through verbatim reject dotted names.

### `chrono_core_resolve_project`

Input:

```json
{
  "cwd": "~/workspace/example",
  "workspace_root": "~/workspace"
}
```

Output: same as `chrono resolve`.

### `chrono_core_session_handoff`

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

### `chrono_core_get_resume_context`

Input:

```json
{
  "cwd": "~/workspace/example",
  "max_tokens": 2000,
  "branch": null,
  "include_all": false,
  "limit": 20
}
```

Scopes to the project's current git branch unless `include_all` is true or an
explicit `branch` is given (mirroring `chrono resume` semantics); `limit`
caps open items per category in every mode.

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

When `max_tokens` is provided, the result is trimmed to that approximate
budget (~4 characters per token on the serialized JSON) and gains a
`"truncated"` boolean. Trimming drops the oldest `recent_decisions`, then
`next_actions`, then `active_blockers`, then shortens `summary`; project
identity and current status always survive.

### `chrono_core_record_decision`

Input:

```json
{
  "cwd": "~/workspace/example",
  "title": "Use provider-neutral LLM boundary",
  "rationale": "Keeps provider swaps local to the LLM layer."
}
```

Output:

```json
{
  "ok": true,
  "project_id": "example-abc12345",
  "recorded_count": 1,
  "decision": {
    "title": "Use provider-neutral LLM boundary",
    "rationale": "Keeps provider swaps local to the LLM layer."
  }
}
```

### `chrono_core_record_observation`

Input:

```json
{
  "cwd": "~/workspace/example",
  "content": "Bound retries with an explicit budget",
  "kind": "lesson"
}
```

`kind` defaults to `lesson` and accepts only `lesson`, `pattern`, or
`pattern_candidate`. Output contains the resolved `project_id`,
`recorded_count: 1`, and the stored observation with `source: "direct"` and no
session id. Invalid kinds and blank content return a structured error without
writing.

### `chrono_core_record_blocker`

Input:

```json
{
  "cwd": "~/workspace/example",
  "title": "Live smoke requires credentials",
  "detail": "Credential path is not configured.",
  "status": "open"
}
```

Output:

```json
{
  "ok": true,
  "project_id": "example-abc12345",
  "recorded_count": 1,
  "blocker": {
    "title": "Live smoke requires credentials",
    "status": "open",
    "detail": "Credential path is not configured."
  }
}
```

### `chrono_core_resolve_blocker` / `chrono_core_complete_action`

Input:

```json
{
  "blocker_id": "blk_1a2b3c4d5e6f7a8b"
}
```

Output:

```json
{
  "ok": true,
  "blocker_id": "blk_1a2b3c4d5e6f7a8b",
  "status": "resolved"
}
```

`chrono_core_complete_action` takes `action_id` and reports `"status": "done"`.
Unknown ids return `"ok": false` with `"status": "not_found"`.

### Lifecycle tools

Seven more lifecycle verbs mirror the CLI subcommands. All take an entity id
(plus optional fields) and return `{"ok": bool, "<entity>_id": ..., "status": ...}`;
unknown ids report `"status": "not_found"`.

- `chrono_core_cancel_action(action_id, reason?)` — cancels an open action;
  cancelling a superseded action returns `"ok": false` with
  `"error": "already superseded; reopen or supersede instead"`.
- `chrono_core_edit_action(action_id, text)` — rewrites the text, keeping the
  previous wording in history.
- `chrono_core_reopen_action(action_id)` — returns the action to open.
- `chrono_core_supersede_action(action_id, text)` — creates a replacement open
  action linked via `supersedes_id`; the response carries `new_action_id`.
- `chrono_core_cancel_blocker(blocker_id, reason?)`
- `chrono_core_edit_blocker(blocker_id, text)`
- `chrono_core_reopen_blocker(blocker_id)`

### Bug tools

- `chrono_core_report_bug(cwd, title, severity?, detail?, workspace?, workspace_root?)`
  — files a bug for the project at `cwd`, or workspace-wide with
  `"workspace": true`; returns `{"ok": true, "bug_id": ..., "bug": {...}}`.
- `chrono_core_list_bugs(status?, severity?, project_id?)` — defaults to open
  bugs across the workspace; returns `{"ok": true, "count": n, "bugs": [...]}`.
- `chrono_core_update_bug(bug_id, status?, severity?, detail?)` — returns
  `{"ok": bool, "bug_id": ..., "bug": {...}}`.
- `chrono_core_push_bug_to_github(bug_id, repo?, dry_run?, db_path?)` — explicitly
  creates or updates one GitHub issue through the authenticated `gh api` bridge.
  Project bugs infer `origin`; workspace-wide bugs require `repo` in
  `[HOST/]OWNER/REPO` form. GitHub Enterprise hosts are passed to `gh api` via
  `--hostname`. Request JSON is sent through stdin and the returned issue URL and
  number are persisted for retryable updates. This is an external mutation;
  `dry_run` performs no subprocess call or database write.

### Project catalog tools

Same envelopes and error codes as the `chrono project` commands:

- `chrono_core_list_projects(status?, tag?, limit?, dirty?, db_path?)` — returns
  `{"ok": true, "count": n, "projects": [...]}` with decoded `tags` and
  `other_factors`; a missing database reports `database_not_found`.
- `chrono_core_get_project(project, db_path?)` — resolves by exact id,
  absolute path, then relative path; returns
  `{"ok": true, "project": {...}}` or `project_not_found` /
  `ambiguous_project`.
- `chrono_core_update_project_metadata(project, status?, lifecycle_phase?, priority?,
  tags?, owner?, description_usage?, summary?, notes?, other_factors?,
  db_path?)` — validates enums and JSON shapes before mutation, rejects empty
  updates, and returns `{"ok": true, "project": {...}}` refreshed.
- `chrono_core_update_project_progress(project, text, db_path?)` — narrow
  convenience update for `current_progress`.
- `chrono_core_discover_projects(workspace_root?, max_depth=3,
  include_provisional=false, db_path?)` — persist one bounded workspace
  inventory refresh and exact-scope missing reconciliation.
- `chrono_core_refresh_project(project, db_path?)` — refresh one registered
  project's current Git inventory.

### `chrono_core_search_observations`

Input:

```json
{
  "query": "credential",
  "project_id": null,
  "limit": 20
}
```

Output: same shape as `chrono search` — `{"ok": true, "query": ..., "count": n,
"results": [...], "bugs": [...], "bug_count": n}`; the search covers both
observation text and bug title/detail FTS.

### `chrono_core_find_similar_projects`

Input:

```json
{
  "cwd": "~/workspace/example",
  "workspace_root": "~/workspace",
  "limit": 5
}
```

Output: same shape as `chrono similar` — `{"ok": true, "project_id": ...,
"count": n, "results": [...]}`. Read-only like the CLI: an unknown project is
reported structurally and never registered.

### `chrono_core_review_project`

Input:

```json
{
  "cwd": "~/workspace/example",
  "workspace_root": "~/workspace"
}
```

Output: same shape as `chrono review`.

### `chrono_core_distill_project`

Input:

```json
{
  "cwd": "~/workspace/example"
}
```

Output: same shape as `chrono distill`.

### Management Tools

Not MVP persistence-critical, but contract names are reserved:

- `chrono_core_reconcile_docs`
- `chrono_core_review_project_health`
- `chrono_core_find_reusable_patterns`

### Reviewed GearCore pattern promotion

Pattern administration is CLI-only in this slice. A validated pattern can be
previewed and then explicitly applied:

```bash
chrono patterns promotion-plan PATTERN_ID \
  --skill-path PATH --evidence PATH \
  [--scope global|project] [--project-root PATH] [--copy] [--db-path PATH]

chrono patterns promote PATTERN_ID \
  --skill-path PATH --evidence PATH --plan-digest SHA256 \
  [--scope global|project] [--project-root PATH] [--copy] [--db-path PATH]
```

The plan validates the authored `SKILL.md` frontmatter/body and a UTF-8 JSON
before/after evidence file, then returns the exact shell-free `gearcore
add-skill` argv and a SHA-256 digest. Promotion recomputes that plan, refuses
stale inputs without invoking GearCore, and marks the pattern `promoted` only
after a successful registration. No skill prose is generated and evidence is
never copied into command arguments or the local database.
