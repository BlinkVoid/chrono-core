# Chrono Core: Reusable Pattern Index — Design

Date: 2026-08-26
Status: Approved design (Approach A); implementation plan to follow.
Phase: 4 — Cross-project Intelligence (first slice)
Related: `docs/INTEGRATION_SUPERSESSION.md` (`_MetaFactory` upstream boundary),
`docs/SQLITE_SCHEMA.md`, roadmap items "reusable pattern index",
"pattern recommendation in resume context".

## Problem

Hard-won patterns live scattered across projects' DISTILL/AGENTS docs and get
consolidated by `_MetaFactory` into per-snapshot `patterns_library.md` files,
but nothing operational reads them. Meanwhile Chrono Core accumulates
decisions and observations that contain recurring themes no one surfaces.
Phase 4's goal is reuse: when an agent resumes a project, relevant validated
patterns should appear without anyone remembering to look.

## Goal

A pattern store inside the continuity database with deterministic ingestion
from MetaFactory, deterministic candidate mining from Chrono's own records,
and FTS-based pattern recommendations embedded in resume context.

## Decisions (brainstorm 2026-08-26)

1. **Sources**: MetaFactory consolidated snapshots *and* self-mined
   candidates from Chrono records. Hand-authoring stays possible via direct
   Store use but gets no dedicated CLI in v1.
2. **Mining is deterministic only** — keyword clustering produces
   *candidates*; confirmation into `validated` happens by editing status
   (CLI flag or direct), not by hidden heuristics.
3. **Primary consumer**: resume recommendations (CLI + MCP inherit).
4. **Relevance**: keyword overlap through the existing FTS machinery; no new
   dependencies, no embeddings.
5. **Lifecycle**: `candidate → validated → promoted → retired`.
   Recommendations surface candidate+validated by default.

## Alternatives rejected

- **Patterns as tagged observations**: no lifecycle/provenance/category
  structure; muddies observations semantics.
- **Separate patterns.db**: splits storage, kills cross-FTS relevance joins,
  extra opener/resolver plumbing for no single-user benefit.

## Data model (schema v4)

```sql
CREATE TABLE patterns (
    id TEXT PRIMARY KEY,              -- pat_<hex16> via make_entity_id
    title TEXT NOT NULL UNIQUE,       -- idempotent-upsert key
    statement TEXT NOT NULL DEFAULT '',
    category TEXT,                    -- e.g. security, architecture
    status TEXT NOT NULL DEFAULT 'candidate',
                                      -- candidate | validated | promoted | retired
    source TEXT NOT NULL,             -- metafactory | mined | authored
    source_ref TEXT,                  -- e.g. consolidated/2026-08-01_090633/patterns_library.md
    projects_json TEXT NOT NULL DEFAULT '[]',  -- display-only source project list
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE pattern_fts USING fts5(
    title, statement, content='patterns', content_rowid='rowid'
);
-- insert/delete/update triggers mirroring observations_fts_*
```

Migration follows the existing `store/migrations.py` apply-pending pattern;
v4 only adds tables (no data backfill).

## Unit 1 — MetaFactory ingestion (`integrations/metafactory.py`)

- CLI: `chrono ingest-patterns [--metafactory-root PATH] [--file PATH]
  [--db-path PATH]`. Default root `~/workspace/_MetaFactory`; picks the newest
  `consolidated/<timestamp>/patterns_library.md` by directory name sort.
- Parser handles the established block format: `## Pattern: <title>`,
  `Category:`, `Frequency:` (ignored), `Projects:` line, `Pattern Statement:`,
  implementation variants, When to Use/Avoid. Statement column carries the
  statement plus variants/when-to-use text; `projects_json` comes from the
  Projects line (worktree markers †/‡ stripped).
- Ingested rows: `status='validated'`, `source='metafactory'`,
  `source_ref='<snapshot-dir-relative path>'`.
- Upsert keyed on `title`: statement/category/source_ref/projects refresh;
  status never regresses away from `promoted` or `retired`.
- Missing root/snapshot/file → non-zero exit with message, no partial writes.

## Unit 2 — Candidate mining (`management/patterns.py`)

- CLI: `chrono mine-patterns [--min-projects N] [--limit K] [--db-path]`
  (defaults 2 / 20). Workspace-wide; takes no project selector.
- Pipeline: load all decisions (title+rationale) and observations across
  projects → tokenize, lowercase, drop stopwords → count distinct projects
  per term → keep terms in ≥ N projects → cap at K by (project count desc,
  total frequency desc, term asc) → insert candidates.
- Candidate shape: title `"Recurring theme: <term>"`, statement naming the
  projects and counts, `source='mined'`, `status='candidate'`.
- Mining never overwrites an existing pattern; a colliding title is skipped
  and reported as such.
- The tokenizer/stopword list lives in a shared small module
  (`chrono_core/textutil.py`) so mining and recommendation scoring use one
  definition; the Store must not import from `management/`.

## Unit 3 — Resume recommendations (`store.get_resume_context`)

- Collect salient terms (same tokenizer/stopwords) from the project's recent
  decision titles, open blocker titles, and open action texts.
- One OR-query against `pattern_fts`; malformed query or empty index returns
  `[]` — recommendation must never fail a resume.
- Rank by hit count then updated_at desc; take top 3 where status in
  (candidate, validated).
- Emitted as `recommended_patterns: [{id, title, category, status}]` in the
  resume context dict/dataclass. MCP `get_resume_context` inherits this with
  no extra wiring.

## CLI additions

- `chrono ingest-patterns` (Unit 1)
- `chrono mine-patterns` (Unit 2)
- `chrono patterns list [--status STATUS] [--limit N]` — visibility helper;
  prints id/title/status/category/source.
- `chrono patterns set-status <pattern_id> {candidate,validated,promoted,retired}`
  — the explicit lifecycle transition (e.g. confirming a mined candidate or
  recording a GearCore promotion).

No new MCP tool in v1; the resume tool carries recommendations.

## Non-goals

- No LLM synthesis inside Chrono (mining stays deterministic; AI
  consolidation remains MetaFactory's job).
- No GearCore skill promotion automation in v1 (`promoted` is a manual
  status change; the promotion pipeline is a later roadmap item).
- No similarity search between projects yet (separate roadmap item).

## Testing

pytest, following existing store/integration test conventions:

1. Migration v4 creates `patterns` + `pattern_fts` with triggers.
2. MetaFactory parser: sample `patterns_library.md` fixture parses into
   expected pattern dicts (title/category/projects/statement).
3. Ingestion idempotency: re-ingest updates in place, no duplicates, and
   does not regress promoted/retired statuses.
4. Ingestion errors: missing root/snapshot exits non-zero, empty output.
5. Mining: threshold respects distinct project count; limit caps output;
   stopwords excluded; existing titles skipped not overwritten.
6. Recommendations: scored ordering, top-3 cap, retired/promoted filtered,
   empty DB → [], malformed query → [] without failing resume.
7. Resume payload includes `recommended_patterns` (unit + budget check).
8. `patterns list` filters by status; `patterns set-status` transitions
   lifecycle states and rejects unknown statuses/ids non-zero.
