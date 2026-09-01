# Chrono Core: One-Way GitHub Bug Push — Design

Date: 2026-09-01
Status: Approved implementation contract
Related: `docs/superpowers/specs/2026-08-25-lifecycle-bugs-resume-design.md`,
`docs/ROADMAP.md`, `README.md`

## Problem

Chrono Core stores cross-project bugs locally and already reserves
`remote_url` / `remote_issue_id`, but a bug cannot be published to a project
repository without manually recreating it. Manual copies drift and do not give
the local record a durable link back to the GitHub issue.

## Goal

Add an explicit one-way push from one local bug to one GitHub issue. SQLite
remains authoritative; pushing creates or updates the remote issue and mirrors
the local title, detail, severity, lifecycle status, and provenance. The
adapter must be retryable, inspectable, and safe with sensitive bug details.

## Decisions

1. **Explicit mutation:** no automatic background sync. A user or agent invokes
   `chrono bug push BUG_ID`; `--dry-run` performs no network or database write.
2. **Transport:** use the authenticated GitHub CLI REST bridge (`gh api`). Send
   the JSON request body through stdin with `--input -`; bug title/detail must
   never appear in process arguments or shell strings.
3. **Local authority:** a later push overwrites the GitHub issue title/body and
   open/closed state from the current local record. Remote comments are not
   touched. Remote-only body edits may be overwritten by design.
4. **Repository:** for a project bug, infer the destination from that project's
   Git `origin`. Workspace-wide bugs require `--repo [HOST/]OWNER/REPO`.
   An explicit repository that conflicts with an existing `remote_url` is
   rejected rather than relinking the bug.
5. **Remote identity:** store the GitHub issue number as text in
   `remote_issue_id` and the canonical `html_url` in `remote_url`. A linked bug
   is updated with `PATCH`; an unlinked bug is created with `POST`.
6. **Lifecycle mapping:** `open`, `confirmed`, and `in_progress` map to an open
   issue. `fixed` maps to closed/completed. `wont_fix` and `cancelled` map to
   closed/not-planned. Creating a closed local bug requires POST then PATCH.
7. **Failure recovery:** persist the returned URL/number immediately after a
   successful POST, before an optional closing PATCH. If closing fails, report
   the partial result; retry updates the linked issue instead of creating
   another. The remote-create/local-link atomicity gap cannot be eliminated by
   the GitHub API and is documented as a residual risk.
8. **No schema/dependency change:** reuse the existing nullable columns and the
   external `gh` executable. Missing CLI, auth/API failure, timeout, invalid
   repository/remote URL, and malformed response return structured errors.

## GitHub issue body

The generated Markdown body contains the local detail followed by a bounded
metadata footer with local bug id, project, severity, status, and timestamps.
It ends with a stable hidden marker:

```html
<!-- chrono-core:bug-id=bug_... -->
```

This marker supports human provenance and future recovery tooling. This slice
does not search GitHub by marker before creation because issue search is not a
transactional idempotency mechanism.

## Interfaces

### Store

`Store.link_bug_remote(bug_id, *, remote_url, remote_issue_id) -> dict`

Updates only the existing bug and returns the refreshed bug. Unknown bugs are
reported without insertion.

### Integration adapter

`integrations/github_issues.py` owns repository parsing, Git-origin inference,
body/payload construction, subprocess execution, response validation, and the
create/update sequence. The subprocess runner is injectable for unit tests.

### Shared service

`services.push_bug_to_github(db_path, bug_id, *, repo=None, dry_run=False)`
loads the canonical Store and delegates to the adapter. Return envelopes include
`ok`, `bug_id`, `action` (`create` or `update`), repository, dry-run state,
remote URL/number when known, and structured error/partial-result fields.

### CLI

```bash
chrono bug push BUG_ID [--repo [HOST/]OWNER/REPO] [--dry-run] [--db-path PATH]
```

The command prints JSON and exits non-zero on a structured failure.

### MCP

`chrono_core_push_bug_to_github(bug_id, repo=None, dry_run=False,
db_path=None)` exposes the same service. Its description must make the external
GitHub mutation explicit.

## Non-goals

- Pulling GitHub edits, comments, labels, assignees, or milestones into SQLite.
- Polling, webhooks, scheduled/background synchronization, or bulk push.
- Creating labels or changing remote comments.
- Relinking an already-linked bug to another repository.
- Guaranteeing distributed atomicity between GitHub and SQLite.

## Testing

1. GitHub HTTPS, SCP-style SSH, SSH-URL, and explicit repository forms parse
   deterministically; invalid/non-GitHub-shaped values fail structurally.
2. Create/update payloads carry the body via stdin, not argv.
3. First push creates and links; a second push PATCHes the same issue.
4. A newly created closed bug is linked before the close PATCH; close failure
   returns a recoverable partial result and retry does not POST again.
5. Lifecycle statuses map to the expected state/state reason.
6. Workspace-wide bugs require `--repo`; project bugs infer `origin`.
7. Dry-run invokes no subprocess and changes no remote columns.
8. Missing bug/CLI, timeout, non-zero command, malformed response, and
   repository mismatch return safe structured errors.
9. CLI parsing/dispatch and MCP handler/registration match the service contract.
10. Full regression and lint pass; schema version and dependencies are unchanged.

## Primary references

- <https://cli.github.com/manual/gh_api>
- <https://docs.github.com/en/rest/issues/issues>
