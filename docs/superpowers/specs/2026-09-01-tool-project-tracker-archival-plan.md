# Tool Project Tracker Archival Plan

Date: 2026-09-01
Status: Prepared; not authorized and not executed
Depends on: passing `2026-09-01-workspace-intelligence-migration-acceptance.md`

The dependency passed on 2026-09-01. This plan remains unexecuted and still
requires separate explicit authorization.

## Boundary

This document is a reviewable plan only. It does not authorize any move,
removal, disconnection, registry mutation, or Obsidian export.

The local `tool-project-tracker` bundle is a code plugin/GearCore integration,
not a ChatGPT app. Its lifecycle must therefore be managed through GearCore and
the filesystem; ChatGPT plugin uninstall or permission tools are out of scope.

## Verified current state

- Live source: `/home/r345/workspace/tool-project-tracker`
- The live source is not a Git repository, so archival must create an explicit
  file manifest and digest rather than relying on a commit id.
- GearCore MCP `workspace-intelligence` is active and points to the live
  source's `.venv/bin/python` with `PYTHONPATH` set to its `src` directory.
- GearCore skill `project-tracking` is active and declares the seven
  `workspace_intelligence.*` tools as dependencies.
- The canonical source registry remains
  `~/.local/state/workspace-intelligence/registry.db`.
- The configured Markdown destination is currently unavailable at its mounted
  path; the archive operation must not write to or remove it.
- `/home/r345/workspace/_archive_projects/project-tracking-2026-07-02`
  contains only three historical summary files. It is not a complete snapshot
  of `tool-project-tracker` and must not be treated as one.
- Proposed archive target
  `/home/r345/workspace/_archive_projects/tool-project-tracker-2026-09-01`
  does not currently exist.

## Authorization package

Before requesting authorization, present these exact effects:

1. Back up GearCore's current configuration and installed `project-tracking`
   skill bundle inside the new archive target.
2. Generate a sorted SHA-256 manifest for every regular file in the live source
   and verify the copied/relocated tree against it.
3. Remove only the global GearCore MCP registration
   `workspace-intelligence` and global skill registration `project-tracking`.
4. Move the complete live directory to
   `_archive_projects/tool-project-tracker-2026-09-01/source`.
5. Leave the source registry, workspace-intelligence configuration, configured
   Markdown destination, existing three-file historical snapshot, and Chrono
   database untouched.

The operation must stop before any mutation if the target exists, the source is
missing, the acceptance evidence is stale, the manifest cannot be created, or
either registration does not resolve to the verified live source.

## Proposed execution sequence

After separate explicit authorization:

1. Re-run the isolated migration/export acceptance against the then-current
   source registry and record its digest.
2. Create the new archive directory without overwriting any existing path.
3. Copy the GearCore configuration and installed `project-tracking` skill into
   an `integration-backup/` subdirectory.
4. Create the live-source manifest and record source directory metadata.
5. Run the exact scoped removals:

   ```text
   gearcore remove mcp workspace-intelligence --scope global
   gearcore remove skill project-tracking --scope global
   ```

6. Verify `chrono-core` remains active and the two retired registrations are
   absent.
7. Move the complete live source to the archive's `source/` subdirectory.
8. Verify every archived file against the pre-move manifest.
9. Run Chrono list/show/discover/export smoke tests and `gearcore status`.
10. Record the operation, archive path, registry digest, manifest digest,
    verification results, and rollback window in Chrono.

Do not delete the archived `.venv` during the initial operation. It makes the
first rollback mechanical; size reduction can be proposed later as a separate
authorized cleanup after the rollback window.

## Rollback

Rollback remains available while the original path is free and the archive
manifest verifies:

1. Move `source/` back to `/home/r345/workspace/tool-project-tracker`.
2. Restore the backed-up GearCore configuration and installed skill bundle, or
   re-register the exact saved MCP and skill definitions.
3. Verify `workspace-intelligence` and `project-tracking` are active.
4. Run a read-only source list/get smoke test and compare the registry digest.
5. Record the rollback result in Chrono.

The registry and configured Markdown output are deliberately left in place, so
rollback never depends on reconstructing user data from the archive.

## Post-archive documentation changes

Only after the authorized operation passes verification:

- mark Phase 5 supersession complete in the roadmap and integration document;
- route project tracking instructions exclusively to Chrono Core;
- retain the import command and source-registry compatibility documentation;
- replace language saying the source is live with the verified archive path and
  manifest digest.
