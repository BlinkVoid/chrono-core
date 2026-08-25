# Chrono Core: Record Export API (`chrono export json`) — Design

Date: 2026-08-26
Status: Implemented (branch `feat/record-export-json`; `chrono_core.export.json`,
`chrono export json`)
Consumer: ProjectA vault sync (`atlas sync chrono`, separate ProjectA spec)

## Problem

ProjectA will sync Chrono records (decisions, blockers, next actions) into an
Obsidian vault, one note per record, idempotently keyed by record ID. The only
machine-readable surface today is `chrono resume --json`, which:

- returns only *recent* decisions (capped), not full history;
- has no date filter;
- mixes current-state snapshot semantics with record data.

The database holds ~1.4k decisions; consumers cannot backfill or incrementally
pull records through the CLI. Direct SQLite reads would couple consumers to
Chrono's internal schema, which both cores evolve independently.

## Goal

A stable, read-only, per-project JSON export of records, filterable by date,
suitable for both one-time backfill and incremental sync.

## Options considered

1. **Extend `resume --json`** with `--since` and lift the recent-decisions cap —
   rejected: resume is a curated *current-state snapshot* (open items, latest
   session). Overloading it with full history muddies its contract.
2. **New `chrono export json` subcommand** (recommended) — sits beside
   `export markdown` in the same `export/` package, shares project resolution,
   keeps `resume` semantics untouched.
3. **Let consumers read `chrono.db` directly** — rejected: schema coupling
   across cores; any migration breaks consumers silently.

## Design

### CLI

```
chrono export json [--project-id ID | --cwd PATH] [--db-path PATH]
                   [--since ISO8601] [--include-closed] [--type {decisions,blockers,next_actions}]...
```

- Exactly one of `--project-id` / `--cwd` resolves the target project (reuse
  the same resolution logic as `resume`).
- Default (no filters): **full history**, all record types — this is the
  backfill path. This intentionally differs from `resume`'s capped view.
- `--since <ISO8601>` filters on each record's `created_at` (all three tables
  have a non-null `created_at`) — inclusive. This is the incremental-sync path;
  consumers store their last-seen watermark.
- `--include-closed`: by default resolved/cancelled blockers and completed
  actions are omitted (matching `resume`); pass the flag to include them with
  their terminal status so consumers can close previously synced notes.
  Decisions are always included in all statuses.
- `--type` restricts output to selected record types; repeatable.

### Output shape

```json
{
  "project_id": "ProjectA-24b1d6cb41",
  "project_name": "ProjectA",
  "project_path": "~/workspace/cores/core-a",
  "exported_at": "2026-08-26T09:00:00+00:00",
  "filters": {"since": null, "include_closed": false},
  "decisions": [
    {"id": "dec_...", "title": "...", "rationale": "",
     "status": "accepted", "created_at": "...", "session_id": null}
  ],
  "blockers": [
    {"id": "blk_...", "title": "...", "status": "open",
     "detail": "", "created_at": "..."}
  ],
  "next_actions": [
    {"id": "act_...", "text": "...", "status": "open",
     "priority": null, "created_at": "..."}
  ]
}
```

- Every array item carries its primary key and timestamps — this is what makes
  consumer-side idempotency possible.
- Arrays are deterministically ordered by (`created_at`, `id`) so repeated
  exports diff cleanly.
- Omitted keys are never emitted as `null` objects; absent record types appear
  as empty arrays when unfiltered, and are dropped entirely when `--type`
  excludes them.

### Errors

Follow existing CLI conventions: non-zero exit with a message on unresolvable
project, bad `--since` format, or unknown `--type`. No partial output on error.

### Implementation notes (deviations, 2026-08-26)

- `--workspace-root` is also accepted (same default as `resume`) since `--cwd`
  resolution is workspace-relative.
- A `--cwd` project that has never been registered in the database exports an
  empty payload with resolver-derived name/path — matching `resume`, which
  exits 0 with "No project found" rather than erroring. An explicit unknown
  `--project-id` still fails non-zero (typo protection).
- `--since` accepts any ISO 8601 timestamp (`Z` suffix or offset; naive values
  are treated as UTC) and comparison happens on parsed datetimes in Python, so
  mixed stored formats cannot silently break the watermark.

## Non-goals

- No writes; export stays strictly read-only.
- No MCP tool parity in this change (follow-up if ProjectA's sync moves to MCP).
- No sessions/observations/documents/bugs export — decisions, blockers, and
  next actions are the sync targets today.
- No cross-project/workspace-wide dump; consumers iterate projects.

## Testing

pytest, following the repo's existing export tests:

1. Full export returns all records incl. closed items excluded by default.
2. `--since` boundary: records exactly at the watermark are included.
3. `--include-closed` surfaces terminal statuses.
4. `--type` filtering drops other arrays from the payload.
5. Deterministic ordering across two consecutive exports.
6. Project resolution via `--cwd` matches `resume`'s resolution.
7. Bad inputs (`--since` malformed, both/neither project selectors) exit non-zero.
