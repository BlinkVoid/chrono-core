# Chrono Core: Reviewed GearCore Pattern Promotion — Design

Date: 2026-09-01
Status: Approved implementation contract
Phase: 4 — Cross-project Intelligence (final roadmap slice)
Related: `2026-08-26-pattern-index-design.md`, `docs/GEARCORE_SKILL_SPEC.md`,
`src/chrono_core/integrations/gearcore.py`

## Problem

Chrono can ingest, mine, validate, recommend, and manually mark reusable
patterns as promoted, but it cannot safely connect a validated pattern to a
tested GearCore skill. A deterministic Markdown generator would be misleading:
Chrono does not perform LLM synthesis, and a database pattern is not proof that
an agent can discover and apply a skill under pressure.

## Goal

Add a reviewed plan/apply boundary that validates an already-authored and
tested skill bundle, previews the exact `gearcore add-skill` mutation, protects
the apply with a content digest, and changes the pattern status to `promoted`
only after GearCore succeeds.

Chrono validates evidence shape and bundle mechanics. It does not claim that
recorded qualitative evidence is true, generate skill prose, run model tests,
or silently mutate GearCore.

## CLI contract

```bash
chrono patterns promotion-plan PATTERN_ID \
  --skill-path PATH --evidence PATH \
  [--scope global|project] [--project-root PATH] [--copy] [--db-path PATH]

chrono patterns promote PATTERN_ID \
  --skill-path PATH --evidence PATH --plan-digest SHA256 \
  [--scope global|project] [--project-root PATH] [--copy] [--db-path PATH]
```

- `promotion-plan` is read-only: no subprocess, GearCore mutation, skill write,
  or database write.
- `promote` is the explicit apply. It recomputes the plan and refuses a stale
  digest before invoking GearCore.
- Default scope is `global`; project scope requires an existing
  `--project-root`.
- Registration uses symlinks by default, consistent with the existing Chrono
  GearCore adapter. `--copy` omits `--symlink`.
- No MCP surface in this slice. Existing pattern administration is CLI-only.

## Eligible pattern

- The pattern must exist and have status `validated`.
- Candidate and retired patterns are rejected before bundle validation.
- A pattern already marked `promoted` returns an `already_promoted` structured
  result without executing GearCore. Chrono does not attempt to infer or repair
  an existing GearCore registration.

## Skill bundle validation

`--skill-path` must be a directory containing a regular `SKILL.md` file no
larger than 256 KiB. Its UTF-8 document must have:

- YAML frontmatter delimited by `---`;
- exactly the keys `name` and `description`, once each;
- a lowercase kebab-case name matching the skill directory basename;
- a description of at most 500 characters beginning with `Use when`;
- a non-empty Markdown body after the frontmatter.

No YAML dependency is added. The accepted frontmatter subset is deliberately
small: one single-line scalar per required key, with optional matching single
or double quotes. Multiline values, aliases, tags, duplicate keys, additional
keys, and malformed quoting are rejected.

## Verification evidence

`--evidence` must be a regular UTF-8 JSON file no larger than 256 KiB:

```json
{
  "pattern_id": "pat_...",
  "baseline": [
    {"scenario": "specific application scenario", "observed_failure": "what failed without the skill"}
  ],
  "verification": [
    {"scenario": "specific application scenario", "observed_pass": "what passed with the skill"}
  ]
}
```

- Only these three top-level keys are accepted.
- `pattern_id` must match the selected pattern.
- Baseline and verification must be non-empty lists of objects with exactly
  the shown non-empty string fields.
- Scenario names must be unique within each list and the two scenario sets
  must match exactly, proving the recorded before/after comparison addresses
  the same cases.
- Evidence content is never copied into command arguments, errors, or the
  Chrono database. Operators remain responsible for sanitizing it before use.

## Plan and digest

The success envelope includes pattern identity, resolved paths, parsed skill
name/description, evidence counts, scope, registration mode, exact GearCore
`argv`, and `plan_digest`.

The SHA-256 digest covers canonical JSON containing:

- pattern id, status, and `updated_at`;
- resolved skill and evidence paths;
- SHA-256 hashes of the exact `SKILL.md` and evidence bytes;
- scope, resolved project root, symlink/copy mode, and exact command argv.

Any source row, bundle, evidence, path, or registration-option change makes the
apply stale.

## Apply and failure semantics

- Execute the planned argv as an argument list with `shell=False`, no stdin,
  captured output, and a 30-second timeout.
- Global argv: `gearcore add-skill --scope global [--symlink] SKILL_PATH`.
- Project argv: `gearcore --project PROJECT_ROOT add-skill --scope project
  [--symlink] SKILL_PATH`.
- Missing GearCore, timeout, or non-zero exit returns a structured, bounded
  error and leaves the pattern `validated`.
- After a zero exit, set the pattern status to `promoted` and return the
  refreshed pattern plus the command metadata.
- If GearCore succeeds but the local status write unexpectedly fails, return a
  partial-success envelope naming the pattern and registration command without
  including skill or evidence content.

## Implementation shape

- Add `src/chrono_core/integrations/pattern_promotion.py` for validation,
  canonical plan/digest construction, subprocess execution, and structured
  errors.
- Add `Store.get_pattern(pattern_id)` rather than filtering full lists.
- Add service-layer `plan_pattern_promotion` and `promote_pattern` so CLI and
  tests share one contract.
- Extend only the existing `patterns` CLI group.
- No schema migration and no dependency change.

## Test-first acceptance

The implementation worker must add focused tests first and record the expected
RED failure before production edits. Tests use temporary skill/evidence files
and an injected runner; they never mutate a real GearCore configuration.

1. Valid plan is read-only and emits the exact global symlink argv.
2. Project/copy plan emits the exact scoped argv and requires project root.
3. Candidate, retired, missing, and already-promoted patterns are structured.
4. Frontmatter rejects extra/duplicate keys, invalid names, directory mismatch,
   non-trigger descriptions, empty bodies, malformed encoding, and oversize.
5. Evidence rejects wrong pattern, unknown keys, empty/mismatched/duplicate
   scenarios, malformed encoding/JSON, and oversize.
6. Digest changes for pattern, content, path, or option changes.
7. Stale apply performs no subprocess and leaves status validated.
8. GearCore missing/timeout/non-zero failures leave status validated and bound
   returned stderr.
9. Successful apply runs exactly one shell-free command and marks promoted.
10. Reapplying a promoted pattern performs no subprocess.
11. CLI parser/dispatch/exit codes and documentation match the contract.
12. Full regression suite, Ruff, and `git diff --check` pass.

## Non-goals and residual risk

- No automatic skill prose or scenario generation.
- No assertion that evidence quality can be mechanically proven.
- No direct edits to GearCore configuration or skill directories.
- No rollback of a successful GearCore registration if the final local status
  write fails; that state is reported as partial for manual reconciliation.
