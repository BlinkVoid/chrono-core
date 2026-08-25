# Chrono Core: Record Graph Export — Design (follow-up)

Date: 2026-08-26
Status: Proposed
Origin: raised while implementing `chrono export json` ("does chrono have a
graph DB? can it produce a graph of problems/solutions/decisions?")
Prerequisite: `chrono export json` (see
`2026-08-26-record-export-json-design.md`)

## Problem

Chrono holds the raw material of a problem/solution graph — decisions,
blockers, next actions, sessions — but exposes no way to consume it *as a
graph*. Consumers (ProjectA vault sync, `_MetaFactory` distillation) would
have to re-derive relationships themselves.

There is **no dedicated graph database**, by design (`docs/SYSTEM_DESIGN.md`:
"Start with SQLite, not a dedicated graph database"). The schema already has a
graph-shaped `edges` table, but nothing populates or reads it today.
Relationships exist implicitly:

- `session_id` on every record → records created in the same session are
  candidates for "decision addressed blocker" edges;
- `next_actions.supersedes_id` → explicit supersession chains;
- project/session foreign keys → containment edges.

## Goal

A derived, read-only graph view packaged as a reusable function (and later,
optionally, an MCP tool / CLI flag): nodes = records, edges = typed
relationships, emitted as plain JSON `{nodes, edges}`.

## Design sketch

- `build_record_graph(store, project_id) -> {"nodes": [...], "edges": [...]}`
  in a new module beside `export/json.py`.
- Node: `{"id", "type" (decision|blocker|next_action|session), "label",
  "status", "created_at"}`.
- Edges, in priority order:
  1. `supersedes` from explicit `supersedes_id`;
  2. `co_occurs_in_session` linking each record to its creating session
     (transitive problem↔solution pairs derivable client-side);
  3. future: explicit edges written into the `edges` table as capture grows
     richer (e.g., handoff payloads gain `resolves_blocker` references).
- No traversal engine: consumers get JSON; Kuzu/Neo4j stays out per the
  standing decision until traversal queries justify it.

## Non-goals

- No writes to the `edges` table in v1 (derived view only).
- No similarity/semantic edges (that is Phase 4 pattern-index territory).

## Open questions

- Should session co-occurrence produce direct blocker→decision edges or only
  via the session hub node?
- CLI surface: extend `chrono export json --graph` vs separate subcommand?
