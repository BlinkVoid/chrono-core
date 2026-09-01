# Workspace Intelligence Migration and Export Acceptance

Date: 2026-09-01
Status: Passed
Phase: 5 — Supersession / Consolidation, Stage 3
Related: `2026-09-01-workspace-intelligence-absorption-design.md`,
`2026-09-01-live-project-inventory-design.md`

## Safety boundary

Acceptance reads the live workspace-intelligence SQLite registry but never writes
it. Import targets a new temporary Chrono database and Markdown targets a new
temporary directory. The configured Obsidian export and both the live and
archived project-tracking source trees remain untouched. Archival is a separate,
explicitly authorized operation and is not part of this run.

## Source snapshot

- Registry: `~/.local/state/workspace-intelligence/registry.db`
- Projects: 80 unique ids, paths, and relative paths
- Statuses: 69 active, 11 missing
- Lifecycle phases: 79 prototype, 1 validation
- Git rows: 80, including 48 dirty rows
- JSON validity: all source `tags` and `other_factors` values are valid

The acceptance run records and rechecks the source registry digest so a passing
result also proves the source was not changed by migration.

## Acceptance contract

1. Import succeeds into an empty temporary schema-v6 database.
2. All 80 source records match Chrono by `relative_path` for name, derived
   absolute path, status, priority, tags, owner, description/usage, summary,
   current progress, notes, lifecycle phase, and other factors.
3. The legacy project-tracking snapshot is retained as one separate archived
   source-evidence project; therefore the target contains 81 projects.
4. Source Git values remain historical observations. They are not mislabeled as
   current `project_inventory`; live state is populated only by explicit Chrono
   discover/refresh operations.
5. Markdown export completes atomically enough to report success and produces
   one page per target project plus `Projects.md` and `ReviewQueue.md`.
6. The index contains one link per target project, and representative pages
   retain canonical catalog fields without exposing raw source observations.
7. The source registry digest is unchanged after import and export.
8. Export is derived output: after any authorized schema initialization, it
   does not create projects, re-resolve stored paths, rewrite catalog fields,
   or persist a new distillation/review state.

## Acceptance finding: repeated schema initialization

The first real-registry export exposed a scalability defect: only 10 of 81
project pages were written during a 60-second bounded run. A second durable run
timed out after 300 seconds at the same 10 pages. The next project was HIVE,
whose tree contains 35,654 Markdown files, including 31,198 below `data`, 3,719
below `honeycomb`, and generated files below `.worktrees` and `.venv`.

Two repeated-work boundaries require repair:

1. Routine export calls `review_project` once per project, and each call reruns
   full schema initialization even though `export_markdown` already initialized
   the shared store. Standalone review must still initialize/migrate its store,
   while the already-initialized export loop performs initialization once.
2. Review recursively materializes and reads every `*.md` below a project,
   including generated, dependency, worktree, and bulk-data trees. Review must
   use a deterministic bounded document scope that still includes root project
   Markdown and canonical project documentation under `docs/`, while pruning
   generated/hidden/dependency trees and enforcing a documented file/byte
   ceiling so an adversarial or data-heavy repository cannot stall export.

Regressions must cover both boundaries, and the real 81-project export must then
complete within the durable acceptance window.

## Acceptance finding: export must preserve registered identity

After the performance repairs, the real export completed in 0.608 seconds but
reported 82 projects instead of the 81 imported records. One stored source path
was a symlink. Embedded review/distillation resolved that path to its physical
target, created a second project under the target-relative path, and also
rewrote fields on the archived source-evidence project. Markdown export must
render review/health information from the already-registered project id and
stored path without invoking the mutating resolve/register/distill workflow.
Standalone `chrono review` and `chrono distill` retain their existing explicit
mutation semantics.

## Archival authorization gate

A passing acceptance run permits an archival plan to be prepared. It does not
permit moving, deleting, disabling, unregistering, or rewriting
`tool-project-tracker`, its GearCore registration, the source registry, its
configuration, or the configured Markdown export. Those targets and rollback
steps must be reviewed separately before any archival action.

## Final acceptance evidence

The final run used a fresh temporary root at
`/tmp/chrono-stage3-final.Z6QszN`; it did not reuse either database that exposed
the earlier performance and identity defects.

- Import: 80 workspace-intelligence projects and one legacy
  project-tracking evidence project, with zero skips.
- Canonical parity: all 80 source rows matched by `relative_path`; each compared
  field reported zero mismatches.
- Derived-state boundary: 81 projects, 545 observations, and zero inventory,
  session, decision, blocker, next-action, or bug rows before and after export.
- Database content digest before and after export:
  `d412f94d3845f4bb9fb7ac4859d79081e16a69805ca4cd9d642689e65f9b2b27`.
- Export: 81 project pages and two indexes (83 files), 81 project-index links,
  and catalog sections on all 81 pages; elapsed time was 0.408 seconds.
- Raw `workspace_intelligence_metadata`, `workspace_intelligence_git`, and
  `archived_source_evidence` observation kinds did not appear in the export.
- Source registry digest before and after acceptance:
  `1974aa89e67a4f79706a9ce86ec501fd392f94a25fa56bd590fadc14d4318755`.
- Regression validation: 453 tests passed; Ruff and `git diff --check` passed.

Stage 3 is accepted. This satisfies the technical prerequisite for presenting
the archival plan, but does not authorize executing it.
